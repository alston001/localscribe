"""Plain text, Markdown and subtitle exporters."""

from __future__ import annotations

from pathlib import Path

from ..core.transcript import Transcript
from ..i18n import tr_in
from .common import ExportOptions, clock, metadata, subtitle_cues


def export_txt(t: Transcript, path: Path, options: ExportOptions) -> None:
    meta = " · ".join(f"{k}: {v}" for k, v in metadata(t, options.lang)[:3])
    lines = [t.source_name, meta, ""]
    for seg in t.segments:
        stamp = f"[{clock(seg.start)}] " if options.timestamps else ""
        lines += [f"{stamp}{t.speaker_name(seg.speaker)}: {seg.text}", ""]
    Path(path).write_text("\n".join(lines), encoding="utf-8")


def export_md(t: Transcript, path: Path, options: ExportOptions) -> None:
    lines = [f"# {t.source_name}", ""]
    lines += [f"- **{k}**: {v}" for k, v in metadata(t, options.lang)]
    lines += ["", f"*{tr_in(options.lang, 'exp_generated')}*", "", "---", ""]
    for seg in t.segments:
        stamp = f" `{clock(seg.start)}`" if options.timestamps else ""
        lines += [f"**{t.speaker_name(seg.speaker)}**{stamp}  ", seg.text, ""]
    Path(path).write_text("\n".join(lines), encoding="utf-8")


def export_srt(t: Transcript, path: Path, options: ExportOptions) -> None:
    blocks = []
    for i, cue in enumerate(subtitle_cues(t, options), start=1):
        blocks.append(f"{i}\n{clock(cue.start, True, ',')} --> {clock(cue.end, True, ',')}\n"
                      + "\n".join(cue.lines) + "\n")
    Path(path).write_text("\n".join(blocks), encoding="utf-8")


def export_vtt(t: Transcript, path: Path, options: ExportOptions) -> None:
    blocks = ["WEBVTT\n"]
    for cue in subtitle_cues(t, options):
        blocks.append(f"{clock(cue.start, True)} --> {clock(cue.end, True)}\n" + "\n".join(cue.lines) + "\n")
    Path(path).write_text("\n".join(blocks), encoding="utf-8")
