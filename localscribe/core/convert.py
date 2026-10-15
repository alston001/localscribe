"""Convert recordings to common audio formats, e.g. iPhone Voice Memos .qta -> .m4a.

Transcription itself reads these files directly; conversion is for playing or sharing them
in programs that don't understand the original format.
"""

from __future__ import annotations

import os
import subprocess
import threading
from pathlib import Path
from typing import Callable

from .errors import Cancelled, UserError
from .media import _NO_WINDOW, LOCAL_INPUT_ONLY, best_audio_stream, ffmpeg_exe, length_warning, probe

# id -> (extension, ffmpeg muxer, codec arguments)
CONVERT_FORMATS = {
    "m4a": (".m4a", "ipod", ["-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart"]),
    "mp3": (".mp3", "mp3", ["-c:a", "libmp3lame", "-q:a", "2"]),
    "wav": (".wav", "wav", ["-c:a", "pcm_s16le"]),
    "flac": (".flac", "flac", ["-c:a", "flac"]),
}


def unique_path(folder: Path, stem: str, ext: str) -> Path:
    target = folder / f"{stem}{ext}"
    n = 2
    while target.exists():
        target = folder / f"{stem} ({n}){ext}"
        n += 1
    return target


def convert_file(src: str | Path, folder: str | Path | None, fmt: str,
                 progress: Callable[[float], None] | None = None,
                 cancel: threading.Event | None = None, warnings: list[dict] | None = None) -> Path:
    """Writes the converted file next to the source (or into `folder`) and returns its path.
    Existing files are never overwritten; recording metadata (title, date) is kept. A file
    that came out clearly shorter than the source claims is kept, with a "warn_partial_decode"
    entry appended to `warnings`."""
    src = Path(src)
    ext, muxer, codec_args = CONVERT_FORMATS[fmt]
    info = probe(src)
    stream = best_audio_stream(info.audio)
    if stream is None:
        raise UserError("err_no_audio")
    if not stream.decodable:
        raise UserError("err_codec", detail=stream.codec.split(" (")[0])
    out_dir = Path(folder) if folder else src.parent
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise UserError("err_write", path=str(out_dir)) from exc
    target = unique_path(out_dir, src.stem, ext)
    partial = target.with_name(target.name + ".part")

    cmd = [ffmpeg_exe(), "-hide_banner", "-nostdin", "-loglevel", "error", "-y", *LOCAL_INPUT_ONLY, "-i", str(src),
           "-map", f"0:a:{stream.index}", "-vn", "-map_metadata", "0"]
    if stream.channels > 2:
        cmd += ["-ac", "2"]
    cmd += codec_args + ["-f", muxer, "-progress", "pipe:1", "-nostats", str(partial)]

    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            stdin=subprocess.DEVNULL, creationflags=_NO_WINDOW)
    errors: list[bytes] = []
    reader = threading.Thread(target=lambda: errors.append(proc.stderr.read()), daemon=True)
    reader.start()
    try:
        for raw in proc.stdout:
            if cancel is not None and cancel.is_set():
                proc.kill()
                break
            line = raw.decode("ascii", "replace").strip()
            if line.startswith("out_time_us=") and progress and info.duration:
                try:
                    progress(min(int(line.split("=", 1)[1]) / 1e6 / info.duration, 1.0))
                except ValueError:
                    pass
    finally:
        proc.wait()
        reader.join(timeout=5)

    if cancel is not None and cancel.is_set():
        partial.unlink(missing_ok=True)
        raise Cancelled()
    if proc.returncode != 0 or not partial.exists():
        partial.unlink(missing_ok=True)
        detail = b"".join(errors).decode("utf-8", "replace").strip().splitlines()
        raise UserError("err_convert", detail=detail[-1] if detail else f"ffmpeg exit {proc.returncode}")
    os.replace(partial, target)
    written = probe(target).duration  # measure what was written, not what ffmpeg reported
    warning = length_warning(info, written) if written is not None else None
    if warning and warnings is not None:
        warnings.append(warning)
    if progress:
        progress(1.0)
    return target
