"""Plain text, Markdown and subtitle exporters."""

from __future__ import annotations

from pathlib import Path

from ..core.transcript import Gap, Transcript
from ..i18n import tr_in
from .common import (UNCERTAIN_MARK, ExportOptions, any_marked, clock, gap_text, marked_text, metadata, sentences,
                     subtitle_cues, with_gaps)


def _legend(t: Transcript, options: ExportOptions) -> list[str]:
    return [tr_in(options.lang, "exp_uncertain_note_mark", mark=UNCERTAIN_MARK)] if any_marked(t, options) else []


def export_txt(t: Transcript, path: Path, options: ExportOptions) -> None:
    meta = " · ".join(f"{k}: {v}" for k, v in metadata(t, options.lang)[:3])
    lines = [t.source_name, meta, *_legend(t, options), ""]
    for item in with_gaps(t):
        if isinstance(item, Gap):
            lines += [gap_text(item, options.lang), ""]
            continue
        stamp = f"[{clock(item.start)}] " if options.timestamps else ""
        lines += [f"{stamp}{t.speaker_name(item.speaker)}: {marked_text(item, options)}", ""]
    Path(path).write_text("\n".join(lines), encoding="utf-8")


def export_md(t: Transcript, path: Path, options: ExportOptions) -> None:
    lines = [f"# {t.source_name}", ""]
    lines += [f"- **{k}**: {v}" for k, v in metadata(t, options.lang)]
    note = sentences(tr_in(options.lang, "exp_generated"), *_legend(t, options))
    lines += ["", f"*{note}*", "", "---", ""]
    for item in with_gaps(t):
        if isinstance(item, Gap):
            lines += [f"*{gap_text(item, options.lang)}*", ""]
            continue
        stamp = f" `{clock(item.start)}`" if options.timestamps else ""
        lines += [f"**{t.speaker_name(item.speaker)}**{stamp}  ", marked_text(item, options), ""]
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
