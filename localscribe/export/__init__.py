"""Exporters: every format is written from a Transcript."""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

from ..core.errors import UserError
from ..core.transcript import Transcript
from .common import ExportOptions
from .office import export_csv, export_docx, export_xlsx
from .text import export_md, export_srt, export_txt, export_vtt

# format id -> (file extension, writer); order is the order shown in the UI.
FORMATS = {
    "docx": (".docx", export_docx),
    "txt": (".txt", export_txt),
    "md": (".md", export_md),
    "srt": (".srt", export_srt),
    "vtt": (".vtt", export_vtt),
    "xlsx": (".xlsx", export_xlsx),
    "csv": (".csv", export_csv),
}


def output_base(folder: Path, stem: str, formats: list[str]) -> str:
    """'<stem>_transcript', or '<stem>_transcript (2)' etc. so earlier results are never overwritten."""
    extensions = [".json"] + [FORMATS[f][0] for f in formats]
    base = f"{stem}_transcript"
    n = 1
    while any((folder / f"{base}{ext}").exists() for ext in extensions):
        n += 1
        base = f"{stem}_transcript ({n})"
    return base


def write_outputs(transcript: Transcript, folder: Path, formats: list[str],
                  options: ExportOptions) -> list[Path]:
    """Writes <name>_transcript.json plus each requested format. JSON comes first.

    All files are written into a temporary folder next to them first and moved into place
    only when every one succeeded, so a full disk or a locked file never leaves half a set.
    """
    folder = Path(folder)
    moved: list[Path] = []
    staging: Path | None = None
    try:
        folder.mkdir(parents=True, exist_ok=True)
        base = output_base(folder, Path(transcript.source).stem, formats)
        staging = Path(tempfile.mkdtemp(prefix=".localscribe-", dir=folder))
        names = [f"{base}.json"] + [f"{base}{FORMATS[fmt][0]}" for fmt in formats]
        transcript.save(staging / names[0])
        for fmt, name in zip(formats, names[1:]):
            FORMATS[fmt][1](transcript, staging / name, options)
        for name in names:
            os.replace(staging / name, folder / name)
            moved.append(folder / name)
    except OSError as exc:
        for path in moved:  # this call's files only; earlier results are never touched
            path.unlink(missing_ok=True)
        failed = Path(exc.filename) if exc.filename else folder
        if staging is not None and failed.parent == staging:
            failed = folder / failed.name  # name the real target, not the temporary copy
        raise UserError("err_write", path=str(failed)) from exc
    finally:
        if staging is not None:
            shutil.rmtree(staging, ignore_errors=True)
    return moved
