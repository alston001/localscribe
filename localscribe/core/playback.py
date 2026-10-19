"""Playing part of a recording while proofreading, from memory, with sounddevice (PortAudio).

The recording is decoded once (media.load_audio, as for transcription), so every format LocalScribe
transcribes also plays, and it is held as 16-bit samples: an hour takes 115 MB. Nothing is
written to disk.
"""

from __future__ import annotations

import numpy as np

from .errors import UserError
from .media import SAMPLE_RATE


class Player:
    def __init__(self, audio: np.ndarray, rate: int = SAMPLE_RATE):
        self.rate = rate
        self._samples = (np.clip(audio, -1.0, 1.0) * 32767).astype(np.int16)
        self._stream = None
        self._frame = 0      # the next frame to play
        self._stop_at = 0
        self._done = False   # the stream reached _stop_at (set from PortAudio's thread)

    @property
    def duration(self) -> float:
        return len(self._samples) / self.rate

    @property
    def playing(self) -> bool:
        return self._stream is not None and not self._done

    def position(self) -> float:
        return self._frame / self.rate

    def play(self, start: float, end: float | None = None) -> None:
        """Plays from `start` to `end` (the end of the recording when None), stopping what played."""
        self.stop()
        import sounddevice as sd  # only now: LocalScribe runs without a sound card or PortAudio

        first = min(max(int(round(start * self.rate)), 0), len(self._samples))
        last = len(self._samples) if end is None else min(max(int(round(end * self.rate)), first),
                                                            len(self._samples))
        self._frame, self._stop_at, self._done = first, last, False

        def fill(outdata, frames, time_info, status):
            n = max(min(frames, self._stop_at - self._frame), 0)
            outdata[:n, 0] = self._samples[self._frame:self._frame + n]
            outdata[n:] = 0
            self._frame += n
            if n < frames:
                raise sd.CallbackStop

        try:
            stream = sd.OutputStream(samplerate=self.rate, channels=1, dtype="int16", callback=fill,
                                     finished_callback=self._finished)
            stream.start()
        except Exception as exc:  # PortAudioError, or OSError with no device or PortAudio library
            raise UserError("err_playback", detail=str(exc)) from exc
        self._stream = stream

    def set_end(self, end: float | None) -> None:
        """Moves where the stretch playing now stops: `end`, or the end of the recording when None."""
        self._stop_at = len(self._samples) if end is None else min(max(int(round(end * self.rate)), 0),
                                                                     len(self._samples))

    def _finished(self) -> None:
        self._done = True  # PortAudio's thread may not close its own stream: stop() does that

    def stop(self) -> None:
        stream, self._stream = self._stream, None
        if stream is None:
            return
        try:
            stream.stop()
            stream.close()
        except Exception:  # the device went away; the stream is gone either way
            pass
