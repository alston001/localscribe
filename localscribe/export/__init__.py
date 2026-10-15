"""Exporters: every format is written from a Transcript."""

from __future__ import annotations

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
    """Writes <name>_transcript.json plus each requested format. JSON comes first."""
    folder = Path(folder)
    try:
        folder.mkdir(parents=True, exist_ok=True)
        base = output_base(folder, Path(transcript.source).stem, formats)
        json_path = folder / f"{base}.json"
        transcript.save(json_path)
        written = [json_path]
        for fmt in formats:
            ext, writer = FORMATS[fmt]
            target = folder / f"{base}{ext}"
            writer(transcript, target, options)
            written.append(target)
    except PermissionError as exc:
        raise UserError("err_write", path=str(exc.filename or folder)) from exc
    return written
