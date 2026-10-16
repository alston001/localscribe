"""One file through decode -> transcribe -> diarize -> align -> export.

The Engine keeps models loaded between files; it is not thread-safe, so use it from one
worker thread only.
"""

from __future__ import annotations

import gc
import os
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, Sequence, TypeVar

from .. import __version__
from . import device as dev
from .align import DEFAULT_SPEAKER, assign_speakers, group_utterances, join_words, smooth_speakers
from .asr import AsrResult, drop_sign_offs, lost_speech, text_gaps
from .diarization import SpeakerCount, Turn
from .errors import Cancelled, UserError
from .media import SAMPLE_RATE, load_audio, mmss
from .models import ModelStore
from .transcript import Gap, Segment, Transcript, TWord


@dataclass
class EngineSettings:
    models_dir: Path
    extra_model_dirs: list[Path] = field(default_factory=list)
    whisper_model: str = "auto"
    device: str = "auto"      # auto | cuda | cpu
    diarizer: str = "auto"    # auto | pyannote | sherpa
    cpu_threads: int = 0      # 0 = library default


@dataclass
class JobOptions:
    language: str | None = "en"   # None = detect
    speakers: SpeakerCount = field(default_factory=SpeakerCount)
    normalize: bool = False
    denoise: bool = False
    hotwords: str = ""
    speaker_prefix: str = "Speaker"


@dataclass
class Progress:
    stage: str          # decode | download | load | transcribe | diarize | export | done
    overall: float      # 0..1 for the whole file
    detail: str = ""


ProgressFn = Callable[[Progress], None]
T = TypeVar("T")


class _Reporter:
    def __init__(self, callback: ProgressFn | None, with_diarization: bool):
        self.callback = callback
        spans = [("decode", 0.04), ("transcribe", 0.66), ("diarize", 0.27), ("export", 0.03)]
        if not with_diarization:
            spans = [("decode", 0.05), ("transcribe", 0.92), ("diarize", 0.0), ("export", 0.03)]
        self.offsets, start = {}, 0.0
        for name, width in spans:
            self.offsets[name] = (start, width)
            start += width
        self.current = "decode"

    def __call__(self, stage: str, fraction: float = 0.0, detail: str = "") -> None:
        if stage in self.offsets:
            self.current = stage
        start, width = self.offsets[self.current]
        if self.callback:
            self.callback(Progress(stage, min(start + width * max(0.0, min(fraction, 1.0)), 1.0), detail))


def _is_gpu_failure(exc: Exception) -> bool:
    # Names from the CUDA stack only: a bare "gpu" also matched unrelated errors.
    text = f"{type(exc).__name__} {exc}".lower()
    return any(k in text for k in ("cuda", "cublas", "cudnn", "out of memory"))


def _gb(n: int) -> str:
    return f"{n / 2**30:.2f} GB" if n >= 2**30 else f"{n / 2**20:.0f} MB"


class Engine:
    def __init__(self, settings: EngineSettings, log: Callable[[str], None] | None = None):
        dev.prepare_environment()
        self.log = log or (lambda message: None)
        self.settings = settings
        self.store = ModelStore(settings.models_dir, settings.extra_model_dirs)
        self._transcriber = None
        self._transcriber_key = None
        self._diarizer = None
        self._diarizer_key = None
        self._gpu_failed = False

    def update_settings(self, settings: EngineSettings) -> None:
        self.settings = settings
        self.store = ModelStore(settings.models_dir, settings.extra_model_dirs)
        self._gpu_failed = False  # cached models are swapped lazily when their key changes

    # ---- what will run ---------------------------------------------------
    def device(self) -> str:
        return "cpu" if self._gpu_failed else dev.resolve(self.settings.device)

    def whisper_name(self) -> str:
        # "auto" follows the hardware, not a CPU fallback: losing the GPU should cost speed,
        # not accuracy.
        name = self.settings.whisper_model
        return dev.auto_whisper_model(dev.resolve(self.settings.device)) if name == "auto" else name

    def diarizer_name(self) -> str:
        choice = self.settings.diarizer
        if choice in ("pyannote", "sherpa"):
            return choice
        return "pyannote" if self.store.pyannote_path() else "sherpa"

    # ---- model management -------------------------------------------------
    def _transcriber_for(self, device: str, report: _Reporter, cancel) -> "object":
        name = self.whisper_name()
        key = (name, device, str(self.store.root))
        if self._transcriber is not None and self._transcriber_key == key:
            return self._transcriber
        self.release_transcriber()
        path = self.store.whisper_path(name)
        if path is None:
            self.log(f"Downloading Whisper model '{name}'")

            def on_bytes(done: int, total: int) -> None:
                report("download", 0.0, f"{name}: {_gb(done)} / {_gb(total)}" if total else name)

            path = self.store.ensure_whisper(name, progress=on_bytes, cancel=cancel)
        report("load", 0.0, name)
        from .asr import Transcriber

        started = time.monotonic()
        self._transcriber = Transcriber(path, device, dev.compute_type(device), self.settings.cpu_threads)
        self._transcriber_key = key
        self.log(f"Loaded Whisper {name} on {device} ({self._transcriber.compute_type}) "
                 f"in {time.monotonic() - started:.1f}s")
        return self._transcriber

    def release_transcriber(self) -> None:
        if self._transcriber is not None:
            self._transcriber = None
            self._transcriber_key = None
            gc.collect()

    def _diarizer_for(self, name: str, device: str, report: _Reporter, cancel):
        key = (name, device, str(self.store.root))
        if self._diarizer is not None and self._diarizer_key == key:
            return self._diarizer
        self.release_diarizer()
        if name == "pyannote":
            path = self.store.pyannote_path()
            if path is None:
                raise UserError("err_pyannote_missing")
            report("load", 0.0, "pyannote")
            from .diarization.pyannote_backend import PyannoteDiarizer

            self._diarizer = PyannoteDiarizer(path, device)
        else:
            def on_bytes(done: int, total: int) -> None:
                report("download", 0.0, f"sherpa-onnx: {_gb(done)} / {_gb(total)}" if total else "sherpa-onnx")

            seg, emb = self.store.ensure_sherpa(progress=on_bytes, cancel=cancel)
            from .diarization.sherpa import SherpaDiarizer

            self._diarizer = SherpaDiarizer(seg, emb, num_threads=max(1, min(8, os.cpu_count() or 4)))
        self._diarizer_key = key
        self.log(f"Speaker diarization: {self._diarizer.name} on {device if name == 'pyannote' else 'cpu'}")
        return self._diarizer

    def release_diarizer(self) -> None:
        if self._diarizer is not None:
            close = getattr(self._diarizer, "close", None)
            if close:
                close()
            self._diarizer = None
            self._diarizer_key = None
            gc.collect()

    def release_all(self) -> None:
        self.release_transcriber()
        self.release_diarizer()

    # ---- steps ---------------------------------------------------------------
    def _asr(self, audio, opts: JobOptions, device: str, report: _Reporter, cancel) -> AsrResult:
        transcriber = self._transcriber_for(device, report, cancel)
        report("transcribe", 0.0, self.whisper_name())
        return transcriber.transcribe(
            audio, language=opts.language, hotwords=opts.hotwords.strip() or None,
            progress=lambda f: report("transcribe", f, self.whisper_name()), cancel=cancel)

    def _run_with_gpu_fallback(self, device: str, step: Callable[[str], T], what: str) -> tuple[T, str]:
        """step(device), retried once on the CPU when the GPU fails and the user left the
        device on "auto". Returns the result and the device that produced it."""
        try:
            return step(device), device
        except (Cancelled, UserError):
            raise
        except Exception as exc:
            if device != "cuda" or self.settings.device == "cuda" or not _is_gpu_failure(exc):
                raise
            self.log(f"GPU {what} failed ({exc}); continuing on CPU")
            self._gpu_failed = True
            self.release_all()
            return step("cpu"), "cpu"

    def transcribe_file(self, path: str | Path, opts: JobOptions, progress: ProgressFn | None = None,
                        cancel: threading.Event | None = None) -> Transcript:
        path = Path(path).resolve()
        diarize = not opts.speakers.single
        report = _Reporter(progress, diarize)
        timings: dict[str, float] = {}

        report("decode", 0.0)
        started = time.monotonic()
        warnings: list[dict] = []
        audio = load_audio(path, normalize=opts.normalize, denoise=opts.denoise, cancel=cancel,
                           warnings=warnings)
        duration = len(audio) / SAMPLE_RATE
        timings["decode"] = time.monotonic() - started
        if duration < 0.3:
            raise UserError("err_no_audio")
        self.log(f"{path.name}: {duration / 60:.1f} min of audio")

        device = self.device()
        started = time.monotonic()
        asr, device = self._run_with_gpu_fallback(
            device, lambda on: self._asr(audio, opts, on, report, cancel), "transcription")
        timings["transcribe"] = time.monotonic() - started
        report("transcribe", 1.0)
        if cancel is not None and cancel.is_set():
            raise Cancelled()
        heard = len(asr.words)
        asr.words = drop_sign_offs(asr.words)
        if len(asr.words) < heard:
            self.log(f"{path.name}: removed {heard - len(asr.words)} word(s) of invented sign-offs (\"Thank you.\")")
        if not asr.words:
            raise UserError("err_no_speech")

        turns: list[Turn] = []
        diarizer_name = "none"
        if diarize:
            diarizer_name = self.diarizer_name()
            diarize_device = device if diarizer_name == "pyannote" else "cpu"
            if diarize_device == "cuda" and dev.detect().vram_gb < 12:
                self.release_transcriber()  # make room for pyannote on smaller GPUs
            started = time.monotonic()
            report("diarize", 0.0, diarizer_name)
            if opts.normalize or opts.denoise:
                # Clean-up filters help recognition but distort voice characteristics
                # (volume levelling made a 3-person panel cluster as 4), so diarize the original.
                audio = load_audio(path, cancel=cancel)

            def diarize_on(on_device: str) -> tuple[str, list[Turn]]:
                diarizer = self._diarizer_for(diarizer_name, on_device, report, cancel)
                return diarizer.name, diarizer.diarize(audio, opts.speakers, cancel=cancel,
                                                       progress=lambda f: report("diarize", f, diarizer.name))

            (diarizer_name, turns), diarize_device = self._run_with_gpu_fallback(
                diarize_device, diarize_on, "diarization")
            if diarize_device == "cuda":
                import torch

                torch.cuda.empty_cache()  # hand cached memory back before Whisper reloads
            timings["diarize"] = time.monotonic() - started

        lost = lost_speech(asr.speech, asr.words)  # for the warning and the gap markers
        transcript = build_transcript(path, duration, asr, turns, opts, lost)
        if self._gpu_failed:
            warnings.append({"key": "warn_gpu_fallback"})
        elif self.settings.device == "cuda" and device == "cpu":
            self.log("Settings ask for the GPU, but no CUDA GPU is available; running on CPU")
            warnings.append({"key": "warn_cuda_unavailable"})
        warnings += _lost_speech_warnings(lost)
        if diarize:
            warnings += _speaker_warnings(turns, len(transcript.speakers), opts.speakers)
        transcript.warnings = warnings
        transcript.settings.update({
            "whisper_model": self.whisper_name(), "device": device,
            "compute_type": dev.compute_type(device),
            "diarizer": diarizer_name, "timings_s": {k: round(v, 1) for k, v in timings.items()},
        })
        self.log(f"{path.name}: {len(transcript.speakers)} speaker(s), "
                 + ", ".join(f"{k} {v:.1f}s" for k, v in timings.items()))
        return transcript


def _lost_speech_warnings(stretches: list[tuple[float, float]]) -> list[dict]:
    if not stretches:
        return []
    return [{"key": "warn_lost_speech", "times": ", ".join(f"{mmss(s)}–{mmss(e)}" for s, e in stretches)}]


def _speaker_warnings(turns: list[Turn], found: int, count: SpeakerCount) -> list[dict]:
    if not turns:
        return [{"key": "warn_no_turns"}]
    requested = count.exact or count.min
    if requested and found < requested:
        return [{"key": "warn_fewer_speakers", "found": found, "requested": requested}]
    return []


def build_transcript(path: Path, duration: float, asr: AsrResult, turns: list[Turn],
                     opts: JobOptions, lost: Sequence[tuple[float, float]] = ()) -> Transcript:
    """`lost`: where speech was heard but no words came out (asr.lost_speech)."""
    words = asr.words
    if turns:
        labels, coverage = assign_speakers(words, turns)
        labels = smooth_speakers(words, labels, coverage)
    else:
        labels = [DEFAULT_SPEAKER] * len(words)
    groups = group_utterances(words, labels)

    order: list[str] = []  # speakers numbered by first appearance
    for group in groups:
        if labels[group[0]] not in order:
            order.append(labels[group[0]])
    ids = {raw: f"S{i + 1}" for i, raw in enumerate(order)}
    prefix = opts.speaker_prefix.strip() or "Speaker"
    speakers = {ids[raw]: f"{prefix} {i + 1}" for i, raw in enumerate(order)}

    segments = []
    for group in groups:
        ws = [words[k] for k in group]
        segments.append(Segment(speaker=ids[labels[group[0]]], start=ws[0].start, end=ws[-1].end,
                                text=join_words(ws),
                                words=[TWord(w.start, w.end, w.text, w.prob) for w in ws]))
    # Only the file name: folder names (a client's, a course's) can identify people.
    return Transcript(
        source=path.name, duration=duration, language=asr.language,
        created=datetime.now().isoformat(timespec="seconds"), app_version=__version__,
        settings={"language_requested": opts.language or "auto",
                  "speakers_requested": {"exact": opts.speakers.exact, "min": opts.speakers.min,
                                         "max": opts.speakers.max},
                  "normalize": opts.normalize, "denoise": opts.denoise},
        speakers=speakers, segments=segments,
        gaps=[Gap(start, end, heard) for start, end, heard in text_gaps(words, duration, list(lost))])
