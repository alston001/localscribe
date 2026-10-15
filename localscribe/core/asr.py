"""Speech recognition with faster-whisper (word-level timestamps)."""

from __future__ import annotations

import math
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import numpy as np

from .errors import Cancelled
from .media import SAMPLE_RATE


@dataclass
class Word:
    start: float
    end: float
    text: str  # keeps Whisper's leading space, e.g. " hello,"
    prob: float = 1.0


@dataclass
class AsrResult:
    language: str
    language_probability: float
    words: list[Word]
    # (start, end) seconds in which the voice detector heard speech: what Whisper was given.
    speech: list[tuple[float, float]] = field(default_factory=list)


def lost_speech(speech: list[tuple[float, float]], words: list[Word], min_speech: float = 30.0,
                max_pause: float = 10.0) -> list[tuple[float, float]]:
    """Stretches in which the voice detector heard at least `min_speech` seconds of speech but
    Whisper wrote no words; pauses of up to `max_pause` seconds don't end a stretch.

    Real silence holds no detected speech, so it never counts, and scattered noises in a long
    quiet stretch (a cough, a chair) are cut apart by the pauses between them.
    """
    gaps, edge = [], 0.0
    for word in sorted(words, key=lambda w: w.start):
        if word.start > edge:
            gaps.append((edge, word.start))
        edge = max(edge, word.end)
    gaps.append((edge, math.inf))

    stretches = []
    for gap_start, gap_end in gaps:
        if gap_end - gap_start < min_speech:
            continue
        run = None  # [start, end, seconds of speech]
        for start, end in speech:
            start, end = max(start, gap_start), min(end, gap_end)
            if end <= start:
                continue
            if run is not None and start - run[1] <= max_pause:
                run[1], run[2] = end, run[2] + end - start
                continue
            if run is not None and run[2] >= min_speech:
                stretches.append((run[0], run[1]))
            run = [start, end, end - start]
        if run is not None and run[2] >= min_speech:
            stretches.append((run[0], run[1]))
    return stretches


def speech_clips(audio: np.ndarray, threshold: float = 0.2, max_len: float = 28.0,
                 join_gap: float = 1.0) -> list[tuple[float, float]]:
    """Speech regions grouped into clips of at most `max_len` seconds, cut at pauses.

    Whisper decodes each clip on its own. Letting it seek through long audio instead
    skipped whole sentences near its 30 s window edges (a student's question in a class
    recording vanished; the same audio decoded alone came out complete). The low VAD
    threshold keeps quiet, distant voices that the default 0.5 dropped.
    """
    from faster_whisper.vad import VadOptions, get_speech_timestamps

    regions = get_speech_timestamps(audio, VadOptions(threshold=threshold, min_silence_duration_ms=500,
                                                      speech_pad_ms=300, max_speech_duration_s=max_len))
    clips: list[list[float]] = []
    for region in regions:
        start, end = region["start"] / SAMPLE_RATE, region["end"] / SAMPLE_RATE
        if clips and end - clips[-1][0] <= max_len and start - clips[-1][1] <= join_gap:
            clips[-1][1] = end
        else:
            clips.append([start, end])
    return [(s, e) for s, e in clips]


class Transcriber:
    def __init__(self, model_dir: Path, device: str, compute_type: str, cpu_threads: int = 0):
        from faster_whisper import WhisperModel

        self.model_dir = Path(model_dir)
        self.device = device
        self.compute_type = compute_type
        self.model = WhisperModel(str(self.model_dir), device=device, compute_type=compute_type,
                                  cpu_threads=cpu_threads, local_files_only=True)

    def transcribe(self, audio: np.ndarray, language: str | None = None, batch_size: int = 1,
                   hotwords: str | None = None, initial_prompt: str | None = None,
                   progress: Callable[[float], None] | None = None,
                   cancel: threading.Event | None = None) -> AsrResult:
        """batch_size 1 decodes sequentially (best punctuation and word timing, which also
        matters for speaker attribution); larger batches are ~3x faster on a GPU."""
        duration = len(audio) / SAMPLE_RATE
        options = dict(language=language or None, word_timestamps=True, beam_size=5,
                       hotwords=hotwords or None, initial_prompt=initial_prompt)
        if batch_size > 1:
            from faster_whisper import BatchedInferencePipeline
            from faster_whisper.vad import VadOptions, get_speech_timestamps

            # The pipeline's own defaults, spelled out so `speech` holds the regions it decodes.
            vad = VadOptions(max_speech_duration_s=30, min_silence_duration_ms=160)
            segments, info = BatchedInferencePipeline(self.model).transcribe(
                audio, batch_size=batch_size, vad_filter=True, vad_parameters=vad, **options)
            speech = [(r["start"] / SAMPLE_RATE, r["end"] / SAMPLE_RATE)
                      for r in get_speech_timestamps(audio, vad)]
        else:
            clips = speech_clips(audio)
            if not clips:
                return AsrResult(language or "", 0.0, [])  # "" = unknown, nothing was heard
            # Without conditioning, one misheard phrase cannot snowball into a repetition loop.
            segments, info = self.model.transcribe(
                audio, vad_filter=False, clip_timestamps=[t for clip in clips for t in clip],
                condition_on_previous_text=False, **options)
            speech = list(clips)

        words: list[Word] = []
        for seg in segments:  # generator: decoding happens while iterating
            if cancel is not None and cancel.is_set():
                raise Cancelled()
            if seg.words:
                words.extend(Word(float(w.start), float(w.end), w.word, float(w.probability))
                             for w in seg.words)
            elif seg.text.strip():
                words.append(Word(float(seg.start), float(seg.end), " " + seg.text.strip(), 0.5))
            if progress is not None and duration > 0:
                progress(min(seg.end / duration, 1.0))
        words.sort(key=lambda w: w.start)
        return AsrResult(info.language, float(info.language_probability), words, speech)
