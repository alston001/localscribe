"""Shared helpers for exporters: time formatting, sentence rows, subtitle cues."""

from __future__ import annotations

from dataclasses import dataclass

from ..core.align import ends_sentence
from ..core.transcript import Segment, Transcript, TWord
from ..i18n import tr_in

_CJK_LANGUAGES = {"zh", "ja", "ko", "yue"}


@dataclass
class ExportOptions:
    lang: str = "en"               # language of headings
    timestamps: bool = True        # txt / md / docx
    subtitle_speakers: bool = True


def clock(seconds: float, millis: bool = False, sep: str = ".") -> str:
    total = max(int(round(seconds * 1000)), 0)
    h, rest = divmod(total, 3_600_000)
    m, rest = divmod(rest, 60_000)
    s, ms = divmod(rest, 1000)
    text = f"{h:02d}:{m:02d}:{s:02d}"
    return f"{text}{sep}{ms:03d}" if millis else text


def duration_text(seconds: float) -> str:
    total = int(round(seconds))
    h, rest = divmod(total, 3600)
    m, s = divmod(rest, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def _join(words: list[TWord]) -> str:
    return " ".join("".join(w.text for w in words).split())


def metadata(t: Transcript, lang: str) -> list[tuple[str, str]]:
    model = t.settings.get("whisper_model", "")
    diarizer = t.settings.get("diarizer", "")
    if diarizer and diarizer != "none":
        model = f"{model} + {diarizer}"
    return [
        (tr_in(lang, "exp_date"), t.created.replace("T", " ")[:16]),
        (tr_in(lang, "exp_duration"), duration_text(t.duration)),
        (tr_in(lang, "exp_speakers"), ", ".join(t.speakers.values())),
        (tr_in(lang, "exp_model"), model),
    ]


def segment_words(seg: Segment) -> list[TWord]:
    return seg.words or [TWord(seg.start, seg.end, seg.text, 1.0)]


def sentence_rows(t: Transcript) -> list[tuple[float, float, str, str]]:
    """(start, end, speaker name, text), one row per sentence."""
    rows = []
    for seg in t.segments:
        current: list[TWord] = []
        for w in segment_words(seg):
            current.append(w)
            if ends_sentence(w.text):
                rows.append((current[0].start, current[-1].end, t.speaker_name(seg.speaker), _join(current)))
                current = []
        if current:
            rows.append((current[0].start, current[-1].end, t.speaker_name(seg.speaker), _join(current)))
    return rows


@dataclass
class Cue:
    start: float
    end: float
    speaker: str | None  # set on the first cue after a speaker change
    lines: list[str]


def _wrap(text: str, width: int, cjk: bool) -> list[str]:
    if len(text) <= width:
        return [text]
    middle = len(text) // 2
    if cjk:
        cut = middle
    else:
        spaces = [i for i, ch in enumerate(text) if ch == " "]
        if not spaces:
            return [text]
        cut = min(spaces, key=lambda i: abs(i - middle))
    return [text[:cut].strip(), text[cut:].strip()]


def subtitle_cues(t: Transcript, options: ExportOptions, max_duration: float = 6.0,
                  max_gap: float = 1.0) -> list[Cue]:
    cjk = t.language in _CJK_LANGUAGES
    line_width = 18 if cjk else 42
    cues: list[Cue] = []
    previous_speaker = None
    for seg in t.segments:
        name = t.speaker_name(seg.speaker)
        buffer: list[TWord] = []

        def flush():
            nonlocal previous_speaker
            if not buffer:
                return
            show = name if options.subtitle_speakers and name != previous_speaker else None
            text = _join(buffer)
            if show:
                text = f"{show}: {text}"
            cues.append(Cue(buffer[0].start, buffer[-1].end, show, _wrap(text, line_width, cjk)))
            previous_speaker = name
            buffer.clear()

        for w in segment_words(seg):
            if buffer:
                labelled = options.subtitle_speakers and name != previous_speaker
                label_room = len(name) + 2 if labelled else 0  # only the first cue of a turn has it
                length = len(_join(buffer + [w])) + label_room
                current = len(_join(buffer)) + label_room
                last = buffer[-1].text.rstrip()
                too_big = length > 2 * line_width or w.end - buffer[0].start > max_duration
                # Let a sentence's last word stay instead of becoming a one-word cue.
                orphan = (ends_sentence(w.text) and length <= 2 * line_width + 12
                          and w.end - buffer[0].start <= max_duration + 1.5)
                if ((too_big and not orphan)
                        or w.start - buffer[-1].end > max_gap
                        or (ends_sentence(last) and current > 0.4 * 2 * line_width)
                        or (last.endswith((",", "，", "、", ";")) and current > 0.6 * 2 * line_width)):
                    flush()
            buffer.append(w)
        flush()

    for i, cue in enumerate(cues):  # readable minimum length, never overlapping the next cue
        nxt = cues[i + 1].start if i + 1 < len(cues) else None
        cue.end = max(cue.end, cue.start + 0.8)
        if nxt is not None and cue.end > nxt - 0.02:
            cue.end = max(nxt - 0.02, cue.start + 0.2)
    return cues
