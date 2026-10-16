"""Speech recognition with faster-whisper (word-level timestamps)."""

from __future__ import annotations

import bisect
import math
import re
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import numpy as np

from .errors import Cancelled
from .media import SAMPLE_RATE


@dataclass
class Word:
    start: float
    end: float
    text: str  # keeps Whisper's leading space, e.g. " hello,"
    prob: float = 1.0


@dataclass
class AsrResult:
    language: str
    language_probability: float
    words: list[Word]
    # (start, end) seconds in which the voice detector heard speech: what Whisper was given.
    speech: list[tuple[float, float]] = field(default_factory=list)


def lost_speech(speech: list[tuple[float, float]], words: list[Word], min_speech: float = 30.0,
                max_pause: float = 10.0) -> list[tuple[float, float]]:
    """Stretches in which the voice detector heard at least `min_speech` seconds of speech but
    Whisper wrote no words; pauses of up to `max_pause` seconds don't end a stretch.

    Real silence holds no detected speech, so it never counts, and scattered noises in a long
    quiet stretch (a cough, a chair) are cut apart by the pauses between them.
    """
    stretches = []
    for gap_start, gap_end in _without_words(words, math.inf):
        if gap_end - gap_start < min_speech:
            continue
        run = None  # [start, end, seconds of speech]
        for start, end in speech:
            start, end = max(start, gap_start), min(end, gap_end)
            if end <= start:
                continue
            if run is not None and start - run[1] <= max_pause:
                run[1], run[2] = end, run[2] + end - start
                continue
            if run is not None and run[2] >= min_speech:
                stretches.append((run[0], run[1]))
            run = [start, end, end - start]
        if run is not None and run[2] >= min_speech:
            stretches.append((run[0], run[1]))
    return stretches


def text_gaps(words: list[Word], duration: float, lost: list[tuple[float, float]],
              min_length: float = 30.0) -> list[tuple[float, float, bool]]:
    """Stretches of at least `min_length` seconds in which no words came out, as
    (start, end, speech heard). Where lost_speech found speech inside one (`lost`), that part
    is a gap with speech heard, and the silence on either side counts on its own.

    30 s is what lost_speech needs, so both kinds use the same bar. Shorter pauses (writing on
    the board, a long think) are common in classes and would only clutter the text.
    """
    gaps = []
    for start, end in _without_words(words, duration):
        cursor = start
        for heard_start, heard_end in lost:
            heard_start, heard_end = max(heard_start, start), min(heard_end, end)
            if heard_end <= heard_start:
                continue
            if heard_start - cursor >= min_length:
                gaps.append((cursor, heard_start, False))
            gaps.append((heard_start, heard_end, True))
            cursor = heard_end
        if end - cursor >= min_length:
            gaps.append((cursor, end, False))
    return gaps


def _without_words(words: list[Word], end: float) -> list[tuple[float, float]]:
    """The stretches between 0 and `end` that no word covers."""
    stretches, edge = [], 0.0
    for word in sorted(words, key=lambda w: w.start):
        if word.start > edge:
            stretches.append((edge, word.start))
        edge = max(edge, word.end)
    if end > edge:
        stretches.append((edge, end))
    return stretches


# Closing lines Whisper writes on its own ("Thank you so much for watching"), longest first (see
# drop_sign_offs). The ones for watching or listening may run on to the end of their sentence.
_SIGN_OFFS = sorted({opening + middle + ending
                     for opening in (("thank", "you"), ("thanks",))
                     for middle in (("so", "much"), ("very", "much"), ())
                     for ending in (("for", "watching"), ("for", "listening"), ())}, key=len, reverse=True)
_RUN_ON = {"watching", "listening"}
_RUN_ON_WORDS = 25
# Credits and appeals from subtitled videos, which nobody says in a recording.
_CREDITS = re.compile(
    r"\b(?:sub)?titles?\s+(?:by|from)\s+(?:the\s+)?amara\.org(?:\s+community)?|\bamara\.org(?:\s+community)?"
    r"|字幕由\s*amara\.org\s*社[区區]提供"
    r"|\b(?:transcription|subtitles|captions)\s+by\s+castingwords\b|\bcastingwords\b"
    r"|\btranscription\s+by\s+eso\b[.,]?(?:\s+translation\s+by\b[^.!?]*)?"
    r"|\b(?:please\s+)?(?:don'?t\s+forget\s+to\s+)?like,?\s+(?:share,?\s+)?(?:comment,?\s+)?and\s+subscribe\b"
    r"(?:\s+to\s+(?:our|my|the)\s+channel)?[.!]?"
    r"|\b(?:please\s+)?subscribe\s+to\s+(?:our|my|the)\s+channel\b[.!]?",
    re.IGNORECASE)


def drop_sign_offs(words: list[Word], max_p: float = 0.5) -> list[Word]:
    """`words` without the sign-offs Whisper invents where speech stops or there is none.

    Large-v3 closes a clip that was cut mid-sentence, or a clip of hum, murmur or music, with
    a stand-alone "Thank you." or "Thanks for watching!". In synthetic tests it was unsure of
    the first word of these (p 0.02-0.26) and sure of spoken thanks (p 0.79 or more, also
    quiet or over chatter). So a sign-off that ends a sentence and starts with a word below
    `max_p` is dropped; "Thank you for the question" goes on, so it stays.

    With a word bank, such clips also came out as video credits ("Subtitles by the Amara.org
    community", "Transcription by CastingWords") at p 0.6-1.0. Those are dropped whatever the
    probability, and only the credit itself: speech in the same clip stays. With the bank sent
    as a sentence, the sign-off became "Thank you for listening.", sometimes running on.
    """
    words = _drop_credits(words)
    kept, i = [], 0
    while i < len(words):
        length = _sign_off_length(words, i) if words[i].prob < max_p else 0
        if length:
            i += length
        else:
            kept.append(words[i])
            i += 1
    return kept


def _sign_off_length(words: list[Word], i: int) -> int:
    def ends_sentence(k: int) -> bool:
        return words[k].text.rstrip().endswith((".", "!", "?"))

    for phrase in _SIGN_OFFS:
        span = words[i:i + len(phrase)]
        if len(span) < len(phrase) or tuple(re.sub(r"[^\w']", "", w.text.lower()) for w in span) != phrase:
            continue
        end = i + len(phrase)  # one past the sign-off's last word
        if phrase[-1] in _RUN_ON:
            while not ends_sentence(end - 1) and end < len(words) and end - i < _RUN_ON_WORDS:
                end += 1
        if ends_sentence(end - 1):
            return end - i
    return 0


def _drop_credits(words: list[Word]) -> list[Word]:
    """`words` without the ones a _CREDITS match covers in their joined text."""
    text = "".join(w.text for w in words)
    covered = [False] * len(text)
    for match in _CREDITS.finditer(text):
        covered[match.start():match.end()] = [True] * (match.end() - match.start())
    if not any(covered):
        return words
    kept, start = [], 0
    for word in words:
        end = start + len(word.text)
        if not any(covered[k] and not text[k].isspace() for k in range(start, end)):
            kept.append(word)
        start = end
    return kept


# Text that starts or ends further than this inside its clip left speech out (see uncovered).
UNCOVERED_GAP = 1.5


def uncovered(clip: tuple[float, float], words: list[Word], gap: float = UNCOVERED_GAP) -> list[tuple[float, float]]:
    """The parts of `clip` that `words` leave without text: its start or its end when the text
    begins or stops more than `gap` seconds inside it, or all of it when drop_sign_offs would keep
    no word. In classroom-like tests the normal margins (the voice detector's padding, Whisper's
    timing) stayed under 1.4 s, while speech a word bank lost left 9-24 s."""
    start, end = clip
    kept = drop_sign_offs(sorted(words, key=lambda w: w.start))
    if not kept:
        return [(start, end)]
    parts = []
    if kept[0].start - start > gap:
        parts.append((start, kept[0].start))
    last = max(w.end for w in kept)
    if end - last > gap:
        parts.append((last, end))
    return parts


def fill_gaps(parts: list[tuple[float, float]], kept: list[Word], other: list[Word]) -> list[Word]:
    """The words of `other` (the same clip decoded again) whose middle falls in one of `parts`,
    without one that repeats the kept word right next to the part (the same word, timed apart).
    Sign-offs are dropped from `other` first: a piece of one ("very much.") would get past
    drop_sign_offs later."""
    def bare(word: Word) -> str:
        return re.sub(r"[^\w']", "", word.text.lower())

    other = drop_sign_offs(sorted(other, key=lambda w: w.start))
    filled = []
    for start, end in parts:
        picked = [w for w in other if start <= (w.start + w.end) / 2 < end]
        after = next((k for k in kept if k.start >= end - 0.01), None)
        if picked and after and bare(picked[-1]) == bare(after) and picked[-1].end > after.start - 0.5:
            picked.pop()
        before = next((k for k in reversed(kept) if k.end <= start + 0.01), None)
        if picked and before and bare(picked[0]) == bare(before) and picked[0].start < before.end + 0.5:
            picked.pop(0)
        filled += picked
    return filled


def _words_of(seg) -> list[Word]:
    if seg.words:
        return [Word(float(w.start), float(w.end), w.word, float(w.probability)) for w in seg.words]
    if seg.text.strip():
        return [Word(float(seg.start), float(seg.end), " " + seg.text.strip(), 0.5)]
    return []


def _in_clip(words: list[Word], clips: list[tuple[float, float]]) -> dict[int, list[Word]]:
    """`words` by the index of the clip their middle falls in."""
    starts = [start for start, _ in clips]
    out: dict[int, list[Word]] = {}
    for word in words:
        out.setdefault(max(bisect.bisect_right(starts, (word.start + word.end) / 2) - 1, 0), []).append(word)
    return out


def speech_clips(audio: np.ndarray, threshold: float = 0.2, max_len: float = 28.0,
                 join_gap: float = 1.0) -> list[tuple[float, float]]:
    """Speech regions grouped into clips of at most `max_len` seconds, cut at pauses.

    Whisper decodes each clip on its own. Letting it seek through long audio instead
    skipped whole sentences near its 30 s window edges (a student's question in a class
    recording vanished; the same audio decoded alone came out complete). The low VAD
    threshold keeps quiet, distant voices that the default 0.5 dropped.
    """
    from faster_whisper.vad import VadOptions, get_speech_timestamps

    regions = get_speech_timestamps(audio, VadOptions(threshold=threshold, min_silence_duration_ms=500,
                                                      speech_pad_ms=300, max_speech_duration_s=max_len))
    clips: list[list[float]] = []
    for region in regions:
        start, end = region["start"] / SAMPLE_RATE, region["end"] / SAMPLE_RATE
        if clips and end - clips[-1][0] <= max_len and start - clips[-1][1] <= join_gap:
            clips[-1][1] = end
        else:
            clips.append([start, end])
    return [(s, e) for s, e in clips]


class Transcriber:
    def __init__(self, model_dir: Path, device: str, compute_type: str, cpu_threads: int = 0):
        from faster_whisper import WhisperModel

        self.model_dir = Path(model_dir)
        self.device = device
        self.compute_type = compute_type
        self.model = WhisperModel(str(self.model_dir), device=device, compute_type=compute_type,
                                  cpu_threads=cpu_threads, local_files_only=True)

    def transcribe(self, audio: np.ndarray, language: str | None = None, batch_size: int = 1,
                   hotwords: str | None = None, initial_prompt: str | None = None,
                   progress: Callable[[float], None] | None = None,
                   cancel: threading.Event | None = None) -> AsrResult:
        """batch_size 1 decodes sequentially (best punctuation and word timing, which also
        matters for speaker attribution); larger batches are ~3x faster on a GPU."""
        duration = len(audio) / SAMPLE_RATE
        options = dict(language=language or None, word_timestamps=True, beam_size=5,
                       hotwords=hotwords or None, initial_prompt=initial_prompt)
        if batch_size > 1:
            from faster_whisper import BatchedInferencePipeline
            from faster_whisper.vad import VadOptions, get_speech_timestamps

            # The pipeline's own defaults, spelled out so `speech` holds the regions it decodes.
            vad = VadOptions(max_speech_duration_s=30, min_silence_duration_ms=160)
            found, info = BatchedInferencePipeline(self.model).transcribe(
                audio, batch_size=batch_size, vad_filter=True, vad_parameters=vad, **options)
            pieces = ((_words_of(seg), min(seg.end / duration, 1.0)) for seg in found)
            speech = [(r["start"] / SAMPLE_RATE, r["end"] / SAMPLE_RATE)
                      for r in get_speech_timestamps(audio, vad)]
        else:
            clips = speech_clips(audio)
            if not clips:
                return AsrResult(language or "", 0.0, [])  # "" = unknown, nothing was heard
            pieces, info = self._decode_clips(audio, clips, options)
            speech = list(clips)

        words: list[Word] = []
        for piece, done in pieces:  # generator: decoding happens while iterating
            if cancel is not None and cancel.is_set():
                raise Cancelled()
            words += piece
            if progress is not None and duration > 0:
                progress(done)
        words.sort(key=lambda w: w.start)
        return AsrResult(info.language, float(info.language_probability), words, speech)

    def _decode_clips(self, audio: np.ndarray, clips: list[tuple[float, float]], options: dict):
        """(words in pieces, each with the share of the work done so far, info). Every clip is
        decoded on its own and without conditioning, so one misheard phrase cannot snowball into a
        repetition loop.

        With hotwords (a word bank) Whisper sometimes leaves speech out, so:
        - A clip that starts where the previous one ended was cut out of running speech and begins
          mid-sentence; with a bank, Whisper dropped the first words of 8 of 162 such synthetic
          clips (none without). Those clips are decoded without the hotwords.
        - In the other clips, the parts the text leaves out (see uncovered) are decoded again
          without the hotwords and filled from that (see fill_gaps). On a real 79-minute lecture a
          bank lost 5 stretches of speech at clip starts and ends, against 1 without it.
        """
        bank = options["hotwords"]
        cut = {i for i in range(1, len(clips)) if clips[i][0] - clips[i - 1][1] < 0.1}
        groups = [[c for i, c in enumerate(clips) if i not in cut], [c for i, c in enumerate(clips) if i in cut]]
        if not bank or not groups[1]:
            groups = [clips, []]
        total = sum(end - start for start, end in clips)
        share = 0.9 if bank else 1.0  # with a bank, the rest is for decoding left-out speech again

        def decode(group: list[tuple[float, float]], opts: dict):
            return self.model.transcribe(audio, vad_filter=False, clip_timestamps=[t for c in group for t in c],
                                         condition_on_previous_text=False, **opts)

        first, info = decode(groups[0], options)
        plain = {**options, "hotwords": None, "language": info.language}  # both decodes in one language

        def pieces():
            done, banked = 0.0, []
            for group, found in ((groups[0], first), (groups[1], None)):
                if not group:
                    continue
                for seg in found if found is not None else decode(group, plain)[0]:
                    words = _words_of(seg)
                    if bank and group is groups[0]:  # held back until checked (see below)
                        banked, words = banked + words, []
                    covered = sum(max(0.0, min(end, seg.end) - start) for start, end in group)
                    yield words, min((done + covered) / total, 1.0) * share
                done += sum(end - start for start, end in group)
            if not bank:
                return
            by_clip = _in_clip(banked, groups[0])
            gaps = {k: uncovered(clip, by_clip.get(k, [])) for k, clip in enumerate(groups[0])}
            redo = {k: n for n, k in enumerate(k for k, parts in gaps.items() if parts)}
            again, reached = [], share
            if redo:
                last_end = groups[0][max(redo)][1]
                for seg in decode([groups[0][k] for k in redo], plain)[0]:
                    again += _words_of(seg)
                    reached = max(reached, share + (1 - share) * min(seg.end / last_end, 1.0))
                    yield [], reached
            redone = _in_clip(again, [groups[0][k] for k in redo])
            for k in range(len(groups[0])):
                words = by_clip.get(k, [])
                if k in redo:  # only what survives drop_sign_offs, or two decodes' sign-offs could interleave
                    kept = drop_sign_offs(sorted(words, key=lambda w: w.start))
                    words = kept + fill_gaps(gaps[k], kept, redone.get(redo[k], []))
                yield words, reached
            yield [], 1.0

        return pieces(), info
