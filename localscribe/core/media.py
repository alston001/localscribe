"""Decode any audio/video file to 16 kHz mono float32 with the bundled ffmpeg."""

from __future__ import annotations

import re
import subprocess
import sys
import threading
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .errors import Cancelled, UserError

SAMPLE_RATE = 16000

# Files with other extensions are still accepted when ffmpeg finds an audio stream in them.
MEDIA_EXTENSIONS = {
    ".wav", ".mp3", ".m4a", ".aac", ".flac", ".ogg", ".opus", ".wma", ".aiff", ".aif", ".aifc", ".amr",
    ".qta", ".caf", ".m4b", ".mka", ".ac3", ".mp2",  # .qta: iPhone Voice Memos (iOS 18.2+)
    ".mp4", ".m4v", ".mov", ".mkv", ".avi", ".wmv", ".webm", ".flv", ".mpg", ".mpeg", ".3gp", ".3g2",
    ".mts", ".m2ts", ".vob", ".asf", ".ogv", ".dv",
}

_NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
# Anchored to the start of a line: a metadata tag such as a title can contain the same text.
_DURATION_RE = re.compile(r"(?m)^\s*Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)")
_AUDIO_RE = re.compile(r"(?m)^\s*Stream #\d+:\d+\S*: Audio: (.+)")
# Put before "-i": a playlist or other crafted file must not make ffmpeg open network URLs.
LOCAL_INPUT_ONLY = ["-protocol_whitelist", "file,pipe"]
_PARTIAL_TOLERANCE_S = 2.0  # container durations are not sample-exact
_CHANNEL_WORDS = {"mono": 1, "stereo": 2, "quad": 4, "hexagonal": 6, "octagonal": 8}


def _channel_count(layout: str) -> int:
    """ffmpeg layout text -> channels: 'stereo' 2, '4.0' 4, '5.1(side)' 6, '6 channels' 6."""
    layout = layout.strip().lower()
    word = layout.split("(")[0].strip()
    if word in _CHANNEL_WORDS:
        return _CHANNEL_WORDS[word]
    match = re.match(r"(\d+)\.(\d+)", word)
    if match:
        return int(match.group(1)) + int(match.group(2))
    match = re.match(r"(\d+) channels", word)
    if match:
        return int(match.group(1))
    match = re.match(r"ambisonic (\d+)", word)
    return (int(match.group(1)) + 1) ** 2 if match else 2


def ffmpeg_exe() -> str:
    import imageio_ffmpeg

    return imageio_ffmpeg.get_ffmpeg_exe()


@dataclass
class AudioStream:
    index: int     # position among the file's audio streams, for "-map 0:a:<index>"
    codec: str     # ffmpeg's description, e.g. "aac (LC) (mp4a / 0x6134706D)"
    channels: int

    @property
    def decodable(self) -> bool:
        # iPhone spatial recordings (.qta) carry Apple Positional Audio ("apac"), which ffmpeg
        # cannot decode (its "apac" decoder is an unrelated codec), next to a stereo AAC copy.
        text = self.codec.lower()
        return not (text.startswith(("none", "apac")) or "apac /" in text)


@dataclass
class MediaInfo:
    duration: float | None
    audio: list[AudioStream]


def probe(path: str | Path) -> MediaInfo:
    """Duration and audio streams from ffmpeg's header dump (fast, no decoding)."""
    try:
        proc = subprocess.run([ffmpeg_exe(), "-hide_banner", "-nostdin", *LOCAL_INPUT_ONLY, "-i", str(path)],
                              capture_output=True, stdin=subprocess.DEVNULL,
                              creationflags=_NO_WINDOW, timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        return MediaInfo(None, [])
    text = proc.stderr.decode("utf-8", "replace")
    duration = None
    match = _DURATION_RE.search(text)
    if match:
        h, m, s = match.groups()
        duration = int(h) * 3600 + int(m) * 60 + float(s)
    streams = []
    for i, found in enumerate(_AUDIO_RE.finditer(text)):
        parts = [p.strip() for p in found.group(1).split(",")]
        streams.append(AudioStream(i, parts[0], _channel_count(parts[2]) if len(parts) > 2 else 2))
    return MediaInfo(duration, streams)


def probe_duration(path: str | Path) -> float | None:
    return probe(path).duration


def best_audio_stream(streams: list[AudioStream]) -> AudioStream | None:
    """A decodable stream, preferring mono/stereo (a proper downmix) over surround or ambisonics."""
    if not streams:
        return None
    return max(streams, key=lambda s: (s.decodable, s.channels <= 2, -s.index))


def audio_filters(normalize: bool, denoise: bool) -> list[str]:
    filters = []
    if normalize or denoise:
        filters.append("highpass=f=70")  # remove rumble and desk thumps
    if denoise:
        filters.append("afftdn=nr=10:nf=-40")  # mild: strong denoising hurts recognition
    if normalize:
        # Evens out loud and quiet voices (people far from the mic, remote callers).
        filters.append("dynaudnorm=f=250:g=15:p=0.9:m=8")
    return filters


def _mmss(seconds: float) -> str:
    seconds = int(round(seconds))
    return f"{seconds // 60}:{seconds % 60:02d}"


def load_audio(path: str | Path, normalize: bool = False, denoise: bool = False,
               cancel: threading.Event | None = None, warnings: list[dict] | None = None) -> np.ndarray:
    """Decoded samples. A file ffmpeg could only partly read is still returned, with a
    "warn_partial_decode" entry appended to `warnings`."""
    info = probe(path)
    if info.audio and not any(s.decodable for s in info.audio):
        raise UserError("err_codec", detail=info.audio[0].codec.split(" (")[0])
    stream = best_audio_stream(info.audio)
    cmd = [ffmpeg_exe(), "-hide_banner", "-nostdin", "-loglevel", "error", *LOCAL_INPUT_ONLY, "-i", str(path)]
    if stream is not None and len(info.audio) > 1:
        cmd += ["-map", f"0:a:{stream.index}"]
    cmd += ["-vn", "-sn", "-dn", "-ac", "1", "-ar", str(SAMPLE_RATE)]
    filters = audio_filters(normalize, denoise)
    if filters:
        cmd += ["-af", ",".join(filters)]
    cmd += ["-f", "f32le", "-acodec", "pcm_f32le", "pipe:1"]

    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            stdin=subprocess.DEVNULL, creationflags=_NO_WINDOW)
    errors: list[bytes] = []
    reader = threading.Thread(target=lambda: errors.append(proc.stderr.read()), daemon=True)
    reader.start()
    chunks = []
    try:
        while True:
            if cancel is not None and cancel.is_set():
                proc.kill()
                raise Cancelled()
            chunk = proc.stdout.read(1 << 22)
            if not chunk:
                break
            chunks.append(chunk)
    finally:
        proc.stdout.close()
        proc.wait()
        reader.join(timeout=5)

    data = b"".join(chunks)
    usable = len(data) - len(data) % 4
    if proc.returncode != 0 and usable == 0:
        detail = b"".join(errors).decode("utf-8", "replace").strip().splitlines()
        raise UserError("err_decode", detail=detail[-1] if detail else f"ffmpeg exit {proc.returncode}")
    if usable == 0:
        raise UserError("err_no_audio")
    decoded = usable / 4 / SAMPLE_RATE
    # ffmpeg exits non-zero on damaged files but still hands over what it could read. Small
    # glitches are common and harmless; a missing stretch of audio is not.
    if (proc.returncode != 0 and warnings is not None and info.duration
            and decoded < info.duration - _PARTIAL_TOLERANCE_S):
        warnings.append({"key": "warn_partial_decode", "decoded": _mmss(decoded),
                         "expected": _mmss(info.duration)})
    return np.frombuffer(data[:usable], dtype=np.float32).copy()
