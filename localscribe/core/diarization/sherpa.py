"""sherpa-onnx diarization: pyannote segmentation + speaker embeddings, CPU, no account needed.

sherpa-onnx 1.13's fixed cluster count has no effect (any num_clusters gives the same
result), so speaker counts are enforced here instead: cluster by threshold, then merge
the most similar speakers using one voice embedding per speaker.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Callable

import numpy as np

from ..errors import Cancelled
from ..media import SAMPLE_RATE
from . import SpeakerCount, Turn

# Speakers with less speech than this (seconds) are clustering noise.
_TINY_SPEAKER_S = 2.0
# A cluster under this share of all speech that sounds like an existing speaker is folded into
# them: one person's short replies ("Right.") can form their own cluster. Truly different
# voices measured 0.18-0.28 cosine similarity; a speaker's own "Right."s measured 0.55.
_SMALL_SHARE = 0.01
_SAME_VOICE_SIM = 0.45


class SherpaDiarizer:
    name = "sherpa-onnx"

    def __init__(self, segmentation_model: Path, embedding_model: Path, num_threads: int = 4,
                 threshold: float = 0.5):
        self.segmentation_model = str(segmentation_model)
        self.embedding_model = str(embedding_model)
        self.num_threads = num_threads
        self.threshold = threshold  # cosine-distance cut; larger merges more voices together
        self._extractor = None

    def _engine(self):
        import sherpa_onnx

        config = sherpa_onnx.OfflineSpeakerDiarizationConfig(
            segmentation=sherpa_onnx.OfflineSpeakerSegmentationModelConfig(
                pyannote=sherpa_onnx.OfflineSpeakerSegmentationPyannoteModelConfig(
                    model=self.segmentation_model),
                num_threads=self.num_threads, provider="cpu"),
            embedding=sherpa_onnx.SpeakerEmbeddingExtractorConfig(
                model=self.embedding_model, num_threads=self.num_threads, provider="cpu"),
            clustering=sherpa_onnx.FastClusteringConfig(num_clusters=-1, threshold=self.threshold),
            min_duration_on=0.2,
            min_duration_off=0.4,
        )
        if not config.validate():
            raise RuntimeError("Invalid sherpa-onnx diarization config")
        engine = sherpa_onnx.OfflineSpeakerDiarization(config)
        assert engine.sample_rate == SAMPLE_RATE
        return engine

    def _embed(self, samples: np.ndarray) -> np.ndarray:
        import sherpa_onnx

        if self._extractor is None:
            self._extractor = sherpa_onnx.SpeakerEmbeddingExtractor(
                sherpa_onnx.SpeakerEmbeddingExtractorConfig(
                    model=self.embedding_model, num_threads=self.num_threads, provider="cpu"))
        stream = self._extractor.create_stream()
        stream.accept_waveform(SAMPLE_RATE, samples)
        stream.input_finished()
        vec = np.asarray(self._extractor.compute(stream), dtype=np.float64)
        return vec / (np.linalg.norm(vec) + 1e-9)

    def _speaker_profiles(self, audio, turns, max_seconds=45.0) -> dict[str, tuple[np.ndarray, float]]:
        """speaker -> (unit embedding of up to `max_seconds` of their longest turns, total speech)."""
        by_speaker: dict[str, list[Turn]] = {}
        for t in turns:
            by_speaker.setdefault(t.speaker, []).append(t)
        profiles = {}
        for speaker, items in by_speaker.items():
            pieces, used = [], 0.0
            for t in sorted(items, key=lambda t: t.end - t.start, reverse=True):
                pieces.append(audio[int(t.start * SAMPLE_RATE):int(t.end * SAMPLE_RATE)])
                used += t.end - t.start
                if used >= max_seconds:
                    break
            total = sum(t.end - t.start for t in items)
            profiles[speaker] = (self._embed(np.concatenate(pieces)), total)
        return profiles

    @staticmethod
    def _merge_pair(profiles, rename, a, b):
        (ea, da), (eb, db) = profiles[a], profiles[b]
        keep, drop = (a, b) if da >= db else (b, a)
        merged = ea * da + eb * db
        profiles[keep] = (merged / (np.linalg.norm(merged) + 1e-9), da + db)
        del profiles[drop]
        for k, v in rename.items():
            if v == drop:
                rename[k] = keep

    def _enforce_count(self, audio, turns: list[Turn], count: SpeakerCount) -> list[Turn]:
        speakers = {t.speaker for t in turns}
        if len(speakers) < 2:
            return turns
        target_max = count.exact or count.max or 0
        profiles = self._speaker_profiles(audio, turns)
        rename = {s: s for s in profiles}

        def most_similar(candidates=None):
            keys = list(profiles)
            pairs = [(float(profiles[a][0] @ profiles[b][0]), a, b)
                     for i, a in enumerate(keys) for b in keys[i + 1:]
                     if candidates is None or a in candidates or b in candidates]
            return max(pairs) if pairs else None

        # Fold specks of speech that formed their own cluster into the closest voice,
        # but never below the requested count (or two voices in automatic mode).
        floor = max(count.exact, count.min, 2)
        while len(profiles) > floor:
            tiny = {s for s, (_, d) in profiles.items() if d < _TINY_SPEAKER_S}
            if not tiny:
                break
            _, a, b = most_similar(tiny)
            self._merge_pair(profiles, rename, a, b)

        total = sum(d for _, d in profiles.values())
        while len(profiles) > floor:
            small = {s for s, (_, d) in profiles.items() if d < _SMALL_SHARE * total}
            pair = most_similar(small) if small else None
            if pair is None or pair[0] < _SAME_VOICE_SIM:
                break
            self._merge_pair(profiles, rename, pair[1], pair[2])

        while target_max and len(profiles) > target_max:
            _, a, b = most_similar()
            self._merge_pair(profiles, rename, a, b)

        merged: list[Turn] = []
        for t in turns:
            speaker = rename[t.speaker]
            if merged and merged[-1].speaker == speaker and t.start - merged[-1].end < 0.3:
                merged[-1].end = max(merged[-1].end, t.end)
            else:
                merged.append(Turn(t.start, t.end, speaker))
        return merged

    def diarize(self, audio: np.ndarray, count: SpeakerCount,
                progress: Callable[[float], None] | None = None,
                cancel: threading.Event | None = None) -> list[Turn]:
        audio = np.ascontiguousarray(audio, dtype=np.float32)

        def callback(done: int, total: int) -> int:
            if cancel is not None and cancel.is_set():
                return 1  # non-zero aborts processing
            if progress is not None and total:
                progress(0.95 * done / total)
            return 0

        result = self._engine().process(audio, callback=callback)
        if cancel is not None and cancel.is_set():
            raise Cancelled()
        turns = [Turn(float(s.start), float(s.end), f"SPEAKER_{int(s.speaker):02d}")
                 for s in result.sort_by_start_time()]
        turns = self._enforce_count(audio, turns, count)
        if progress is not None:
            progress(1.0)
        return turns
