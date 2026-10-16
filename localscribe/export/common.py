"""Shared helpers for exporters: time formatting, sentence rows, subtitle cues, uncertain words."""

from __future__ import annotations

from dataclasses import dataclass
from typing import NamedTuple

from ..core.align import ends_sentence
from ..core.transcript import Gap, Segment, Transcript, TWord
from ..i18n import tr_in

_CJK_LANGUAGES = {"zh", "ja", "ko", "yue"}

# Words Whisper gave a lower probability than this are marked when ExportOptions.mark_uncertain
# is on. Chosen on synthetic recordings with known text (see the README): below 0.4 most marked
# words were wrong, between 0.4 and 0.5 most were right. Keep it at or below 0.5, the
# probability asr gives a whole segment that came without word timings.
UNCERTAIN_BELOW = 0.4
UNCERTAIN_MARK = "(?)"
_LEADING = "\"'“‘„‚([{¿¡«‹「『《〈（【［｛"
_TRAILING = ".,;:!?…。，、；：？！\"'”’“‘)]}»›」』》〉）】］｝—–"


@dataclass
class ExportOptions:
    lang: str = "en"               # language of headings
    timestamps: bool = True        # txt / md / docx
    subtitle_speakers: bool = True
    mark_uncertain: bool = False   # txt / md / docx / xlsx / csv; subtitles stay as they are


def clock(seconds: float, millis: bool = False, sep: str = ".") -> str:
    total = max(int(round(seconds * 1000)), 0)
    h, rest = divmod(total, 3_600_000)
    m, rest = divmod(rest, 60_000)
    s, ms = divmod(rest, 1000)
    text = f"{h:02d}:{m:02d}:{s:02d}"
    return f"{text}{sep}{ms:03d}" if millis else text


def sentences(*parts: str) -> str:
    """Sentences on one line: a space between them, but none after a Chinese full stop."""
    line = ""
    for part in parts:
        line += part if not line or line.endswith(("。", "！", "？")) else " " + part
    return line


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


def _words_match(seg: Segment) -> bool:
    return bool(seg.words) and _join(seg.words) == " ".join(seg.text.split())


def segment_words(seg: Segment) -> list[TWord]:
    """Timed words while they still say what `seg.text` says, else the text as one piece
    (see the text rule in core.transcript). That piece has probability 1.0: once the text is
    edited, no confidence is left to mark."""
    if _words_match(seg):
        return seg.words
    return [TWord(seg.start, seg.end, seg.text, 1.0)]


def is_uncertain(word: TWord) -> bool:
    # Rounded as _transcript.json keeps it, so a re-export marks the same words.
    return round(word.prob, 3) < UNCERTAIN_BELOW and any(ch.isalnum() for ch in word.text)


def _split_word(text: str) -> tuple[str, str, str]:
    """(punctuation before, the word, punctuation after). An abbreviation keeps its last
    period ("U.S."), and a plural possessive its apostrophe ("students'")."""
    core = text.lstrip(_LEADING)
    lead = text[:len(text) - len(core)]
    word = core.rstrip(_TRAILING)
    trail = core[len(word):]
    if "." in word and word[-1:].isalpha() and trail.startswith("."):
        word, trail = word + ".", trail[1:]
    elif not lead and word.endswith("s") and trail[:1] in ("'", "’"):
        word, trail = word + trail[0], trail[1:]
    return lead, word, trail


def marked_runs(seg: Segment, options: ExportOptions) -> list[tuple[str, bool]]:
    """The segment's text as (text, uncertain) runs: each uncertain word without its
    punctuation (uncertain words with nothing between them, as in Chinese, form one run), and
    everything between them merged. One run of `seg.text` when marking is off, the words no
    longer say what the text says, or the marks would change its spacing."""
    if not options.mark_uncertain or not _words_match(seg):
        return [(seg.text, False)]
    runs: list[tuple[str, bool]] = []

    def add(text: str, uncertain: bool) -> None:
        if text and runs and runs[-1][1] == uncertain:
            runs[-1] = (runs[-1][0] + text, uncertain)
        elif text:
            runs.append((text, uncertain))

    space = False  # a space is owed before the next visible text (spaced the way _join does)
    for w in seg.words:
        visible = " ".join(w.text.split())
        if not visible:
            space = space or bool(w.text)
            continue
        before = " " if runs and (space or w.text[0].isspace()) else ""
        if is_uncertain(w):
            lead, word, trail = _split_word(visible)
            add(before + lead, False)
            add(word, True)
            add(trail, False)
        else:
            add(before + visible, False)
        space = w.text[-1].isspace()
    if "".join(text for text, _ in runs) != seg.text:  # e.g. a line break typed into the text
        return [(seg.text, False)]
    return runs


def marked_text(seg: Segment, options: ExportOptions) -> str:
    """The segment's text with UNCERTAIN_MARK after each uncertain word."""
    return "".join(text + (UNCERTAIN_MARK if uncertain else "") for text, uncertain in marked_runs(seg, options))


def with_gaps(t: Transcript) -> list[Segment | Gap]:
    """The segments with the gaps between them, in time order. A gap that a segment now
    overlaps (an editor filled it in) is left out: the text is the truth."""
    gaps = sorted((g for g in t.gaps if not any(s.start < g.end and s.end > g.start for s in t.segments)),
                  key=lambda g: g.start)
    items: list[Segment | Gap] = []
    for seg in t.segments:
        while gaps and gaps[0].start < seg.start:
            items.append(gaps.pop(0))
        items.append(seg)
    return items + gaps


def gap_text(gap: Gap, lang: str) -> str:
    """"[Nothing transcribed 00:40:30–00:42:05]", or "[Speech detected, …]" where lost_speech
    heard speech, in the headings' language. The times stay even without timestamps: they say
    where to listen."""
    key = "exp_gap_speech" if gap.speech else "exp_gap_silence"
    return tr_in(lang, key, start=clock(gap.start), end=clock(gap.end))


class Row(NamedTuple):
    start: float
    end: float
    speaker: str      # display name
    text: str
    uncertain: list[str]  # the words Whisper was unsure of, without their punctuation


def sentence_rows(t: Transcript) -> list[Row]:
    """One row per sentence."""
    rows = []
    for seg in t.segments:
        current: list[TWord] = []
        for w in segment_words(seg):
            current.append(w)
            if ends_sentence(w.text):
                rows.append(_row(current, t.speaker_name(seg.speaker)))
                current = []
        if current:
            rows.append(_row(current, t.speaker_name(seg.speaker)))
    return rows


def _row(words: list[TWord], speaker: str) -> Row:
    text = _join(words)
    runs = marked_runs(Segment("", words[0].start, words[-1].end, text, words), ExportOptions(mark_uncertain=True))
    return Row(words[0].start, words[-1].end, speaker, text, [run for run, uncertain in runs if uncertain])


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
