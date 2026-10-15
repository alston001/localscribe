"""Speech recognition with faster-whisper (word-level timestamps)."""

from __future__ import annotations

import threading
from dataclasses import dataclass
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

            segments, info = BatchedInferencePipeline(self.model).transcribe(
                audio, batch_size=batch_size, vad_filter=True, **options)
        else:
            clips = speech_clips(audio)
            if not clips:
                return AsrResult(language or "en", 0.0, [])
            # Without conditioning, one misheard phrase cannot snowball into a repetition loop.
            segments, info = self.model.transcribe(
                audio, vad_filter=False, clip_timestamps=[t for clip in clips for t in clip],
                condition_on_previous_text=False, **options)

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
        return AsrResult(info.language, float(info.language_probability), words)
