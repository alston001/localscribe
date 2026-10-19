"""Proofreading: the edits the proofreading window makes to a Transcript, and saving them.

No Qt here. Segment.text is the truth (see core.transcript): an edited segment keeps its words,
and the exporters use them again only once the text says what they say.
"""

from __future__ import annotations

import bisect
import os
import shutil
import tempfile
from dataclasses import replace
from pathlib import Path

from ..export import FORMATS, output_base
from ..export.common import ExportOptions
from .errors import UserError
from .transcript import Transcript

# An export saved this many seconds or more after its transcript was changed since, probably by
# hand, so the window asks before writing over it.
_CHANGED_AFTER = 2.0


def _clean(text: str) -> str:
    return " ".join(text.split())


def set_text(t: Transcript, index: int, text: str) -> bool:
    """Gives segment `index` new text; False when nothing changed. Empty text is refused: deleting
    a segment is delete_segment."""
    text, seg = _clean(text), t.segments[index]
    if not text or text == seg.text:
        return False
    seg.text = text
    return True


def delete_segment(t: Transcript, index: int) -> None:
    del t.segments[index]


def set_speaker(t: Transcript, index: int, speaker_id: str) -> bool:
    seg = t.segments[index]
    if speaker_id not in t.speakers or seg.speaker == speaker_id:
        return False
    seg.speaker = speaker_id
    return True


def add_speaker(t: Transcript, name: str) -> str:
    """A new speaker's id (S1, S2, … as the pipeline numbers them)."""
    n = 1
    while f"S{n}" in t.speakers:
        n += 1
    t.speakers[f"S{n}"] = _clean(name) or f"S{n}"
    return f"S{n}"


def rename_speaker(t: Transcript, speaker_id: str, name: str) -> bool:
    name = _clean(name)
    if not name or speaker_id not in t.speakers or t.speakers[speaker_id] == name:
        return False
    t.speakers[speaker_id] = name
    return True


def merge_speakers(t: Transcript, source: str, target: str) -> int:
    """Gives `source`'s segments to `target` and removes `source`; how many segments moved."""
    if source == target or source not in t.speakers or target not in t.speakers:
        return 0
    moved = 0
    for seg in t.segments:
        if seg.speaker == source:
            seg.speaker = target
            moved += 1
    del t.speakers[source]
    return moved


def unused_speakers(t: Transcript) -> list[str]:
    used = {seg.speaker for seg in t.segments}
    return [sid for sid in t.speakers if sid not in used]


def drop_unused_speakers(t: Transcript) -> None:
    """Exports list every speaker, so one whose segments all went elsewhere is removed on saving."""
    for sid in unused_speakers(t):
        del t.speakers[sid]


def segment_at(t: Transcript, seconds: float) -> int | None:
    """The segment heard at `seconds`: the last one that has started by then."""
    i = bisect.bisect_right([seg.start for seg in t.segments], seconds) - 1
    return i if i >= 0 else None


def talk_time(t: Transcript) -> dict[str, float]:
    total = {sid: 0.0 for sid in t.speakers}
    for seg in t.segments:
        total[seg.speaker] = total.get(seg.speaker, 0.0) + seg.end - seg.start
    return total


def find_recording(t: Transcript, json_path: Path, hint: Path | None = None) -> Path | None:
    """The recording `t` came from: `hint` (the file its job ran on) while it is still there, else
    the file named t.source next to the transcript. Transcripts keep only the file name, since
    folder names can identify people."""
    for candidate in ([Path(hint)] if hint else []) + [Path(json_path).with_name(t.source_name)]:
        if candidate.is_file():
            return candidate
    return None


def outputs_of(json_path: Path) -> dict[str, Path]:
    """The formats saved next to `json_path` under its name, by format id."""
    json_path = Path(json_path)
    found = {fmt: json_path.with_name(json_path.stem + ext) for fmt, (ext, _) in FORMATS.items()}
    return {fmt: path for fmt, path in found.items() if path.is_file()}


def changed_since(json_path: Path) -> list[Path]:
    """The files of outputs_of(json_path) changed after it was saved, probably by hand."""
    saved = Path(json_path).stat().st_mtime
    return [path for path in outputs_of(json_path).values() if path.stat().st_mtime > saved + _CHANGED_AFTER]


def transcript_path(path: Path) -> Path:
    """The file Save As writes for a name typed as `path`: a '<name>_transcript.json', as
    LocalScribe names transcripts and the Proofread… dialog lists them."""
    path = Path(path)
    stem = path.name[:-len(".json")] if path.name.lower().endswith(".json") else path.name
    if "_transcript" not in stem.lower():
        stem += "_transcript"
    return path.with_name(stem + ".json")


def save_as_name(json_path: Path) -> Path:
    """What Save As suggests for a copy of `json_path`: next to it, numbered as another run of the
    same recording would be ('class_transcript (2).json'), so it replaces nothing."""
    json_path = Path(json_path)
    cut = json_path.stem.lower().rfind("_transcript")
    stem = json_path.stem[:cut] if cut >= 0 else json_path.stem
    return json_path.with_name(output_base(json_path.parent, stem, list(outputs_of(json_path))) + ".json")


def _formats_as(json_path: Path, new_path: Path) -> dict[str, Path]:
    new_path = Path(new_path)
    return {fmt: new_path.with_name(new_path.stem + FORMATS[fmt][0]) for fmt in outputs_of(json_path)}


def save_as_files(json_path: Path, new_path: Path) -> list[Path]:
    """The files save_as writes: `json_path`'s formats under the new name, then the transcript."""
    return [*_formats_as(json_path, new_path).values(), Path(new_path)]


def save(t: Transcript, json_path: Path, options: ExportOptions) -> list[Path]:
    """Writes `t` over `json_path` and its formats (outputs_of) again, so the files from its run
    say what the proofread transcript says; returns them. Everything is written to a staging
    folder first, and nothing is replaced while a file is held open by another program (Word
    locks a document it shows). The transcript goes last, so the exports are never newer.
    Speakers left without segments are not written; `t` itself keeps them."""
    json_path = Path(json_path)
    return _write(t, json_path, outputs_of(json_path), options)


def save_as(t: Transcript, json_path: Path, new_path: Path, options: ExportOptions) -> list[Path]:
    """Writes `t` as `new_path`, in the formats saved next to `json_path`, the way save does
    (save_as_files); the files at `json_path` stay as they were."""
    return _write(t, Path(new_path), _formats_as(json_path, new_path), options)


def _write(t: Transcript, json_path: Path, targets: dict[str, Path], options: ExportOptions) -> list[Path]:
    used = {seg.speaker for seg in t.segments}
    t = replace(t, speakers={sid: name for sid, name in t.speakers.items() if sid in used})
    for path in [*targets.values(), json_path]:
        if path.exists():
            try:
                with open(path, "r+b"):
                    pass
            except PermissionError as exc:
                raise UserError("err_file_in_use", path=str(path)) from exc
    try:
        staging = Path(tempfile.mkdtemp(prefix=".localscribe-", dir=json_path.parent))
    except OSError as exc:  # a folder this user may not write to
        raise UserError("err_write", path=str(json_path)) from exc
    try:
        for fmt, path in targets.items():
            FORMATS[fmt][1](t, staging / path.name, options)
        t.save(staging / json_path.name)
        written = []
        for path in [*targets.values(), json_path]:
            os.replace(staging / path.name, path)
            written.append(path)
        return written
    except OSError as exc:
        failed = Path(exc.filename) if exc.filename else json_path
        if failed.parent == staging:
            failed = json_path.parent / failed.name  # name the real file, not the staging copy
        raise UserError("err_write", path=str(failed)) from exc
    finally:
        shutil.rmtree(staging, ignore_errors=True)
