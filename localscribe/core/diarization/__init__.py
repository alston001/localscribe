"""Speaker diarization backends: who spoke when."""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Callable, Protocol

import numpy as np


@dataclass
class Turn:
    start: float
    end: float
    speaker: str  # backend label, e.g. "SPEAKER_00"


@dataclass
class SpeakerCount:
    """exact > 0 fixes the count; otherwise min/max bound the automatic estimate (0 = unbounded)."""

    exact: int = 0
    min: int = 0
    max: int = 0

    @property
    def single(self) -> bool:
        return self.exact == 1 or (self.max == 1)


class Diarizer(Protocol):
    name: str

    def diarize(self, audio: np.ndarray, count: SpeakerCount,
                progress: Callable[[float], None] | None = None,
                cancel: threading.Event | None = None) -> list[Turn]: ...
