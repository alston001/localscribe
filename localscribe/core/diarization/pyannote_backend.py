"""pyannote.audio diarization (speaker-diarization-community-1), loaded from a local folder."""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Callable

import numpy as np

from ..device import prepare_environment
from ..errors import Cancelled
from ..media import SAMPLE_RATE
from . import SpeakerCount, Turn

# Share of the progress bar for each pyannote step that reports progress.
_STEP_SPANS = {"segmentation": (0.0, 0.3), "embeddings": (0.3, 0.97)}


class PyannoteDiarizer:
    name = "pyannote"

    def __init__(self, model_dir: Path, device: str):
        prepare_environment()  # disables pyannote telemetry before import
        import torch
        from pyannote.audio import Pipeline

        pipeline = Pipeline.from_pretrained(str(model_dir))
        if pipeline is None:
            raise RuntimeError(f"Could not load pyannote pipeline from {model_dir}")
        self.device = device
        self.pipeline = pipeline.to(torch.device(device))

    def diarize(self, audio: np.ndarray, count: SpeakerCount,
                progress: Callable[[float], None] | None = None,
                cancel: threading.Event | None = None) -> list[Turn]:
        import torch

        kwargs = {}
        if count.exact > 0:
            kwargs["num_speakers"] = count.exact
        else:
            if count.min:
                kwargs["min_speakers"] = count.min
            if count.max:
                kwargs["max_speakers"] = count.max

        def hook(step_name, step_artifact, file=None, total=None, completed=None):
            if cancel is not None and cancel.is_set():
                raise Cancelled()
            span = _STEP_SPANS.get(step_name)
            if progress is not None and span and total:
                lo, hi = span
                progress(lo + (hi - lo) * min((completed or 0) / total, 1.0))

        waveform = torch.from_numpy(np.ascontiguousarray(audio, dtype=np.float32)).unsqueeze(0)
        with torch.inference_mode():
            output = self.pipeline({"waveform": waveform, "sample_rate": SAMPLE_RATE},
                                   hook=hook, **kwargs)
        # The exclusive variant keeps one speaker at a time, which is what word alignment needs.
        annotation = getattr(output, "exclusive_speaker_diarization", None)
        if annotation is None:
            annotation = getattr(output, "speaker_diarization", output)
        turns = [Turn(float(seg.start), float(seg.end), str(label))
                 for seg, _, label in annotation.itertracks(yield_label=True)]
        turns.sort(key=lambda t: t.start)
        if progress is not None:
            progress(1.0)
        return turns

    def close(self) -> None:
        import torch

        del self.pipeline
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
