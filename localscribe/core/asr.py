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


# The same words this many times in a row make a repeat (see repeats), if they hold at least
# _MIN_CJK Chinese characters or _MIN_WORDS other words; shorter ones after _REPEAT_TIMES_SHORT.
# What repeats is at most _REPEAT_UNIT characters or words long.
_REPEAT_TIMES = 4
_REPEAT_TIMES_SHORT = 15
_MIN_CJK, _MIN_WORDS = 4, 3
_REPEAT_UNIT = 120
_CJK = "\u3400-\u9fff\uf900-\ufaff"
_TOKENS = re.compile(rf"[{_CJK}]|(?:(?![{_CJK}])[^\W_])+")  # a Chinese character, or another word
_ONE_CJK = re.compile(rf"[{_CJK}]")


def repeats(words: list[Word], times: int = _REPEAT_TIMES) -> list[tuple[float, float]]:
    """Stretches in which the same words come out `times` times or more in a row, as (start, end):
    a sentence that comes back again and again, or a phrase looping inside one. Whisper can get
    stuck like this, while people seldom say a thing four times running: on five English
    lectures, three times in a row came out for three short phrases at a speaking pace, four times
    for none. What repeats must hold at least 4 Chinese characters or 3 other words, so 對對對,
    好的好的好的 or "no, no, no" don't count, unless it goes on and on (嗯 or "Thank you." for a
    whole clip). Punctuation and case are ignored."""
    tokens, owner = [], []  # each Chinese character or other word, and the index of its word
    for k, word in enumerate(words):
        for token in _TOKENS.findall(word.text.lower()):
            tokens.append(token)
            owner.append(k)
    index: dict[str, int] = {}
    ids = np.array([index.setdefault(t, len(index)) for t in tokens], dtype=np.int64)
    spans = []
    for unit in range(1, min(_REPEAT_UNIT, len(tokens) // times) + 1):
        same = np.concatenate(([False], ids[:-unit] == ids[unit:], [False]))
        edges = np.flatnonzero(np.diff(same.astype(np.int8)))
        for start, stop in zip(edges[::2], edges[1::2]):  # tokens[start:stop + unit] repeat every `unit`
            repeated = (stop - start) // unit + 1  # how many times in a row
            if repeated >= times and (repeated >= _REPEAT_TIMES_SHORT or _says_enough(tokens[start:start + unit])):
                spans.append((int(start), int(stop) + unit))
    merged: list[list[int]] = []
    for start, end in sorted(spans):
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return [(words[owner[s]].start, words[owner[e - 1]].end) for s, e in merged]


def _says_enough(unit: list[str]) -> bool:
    """Whether a repeating `unit` of tokens is long enough to count (see repeats)."""
    for p in range(1, len(unit) + 1):  # its shortest repeating part: 對對 is 對 twice
        if len(unit) % p == 0 and unit == unit[:p] * (len(unit) // p):
            unit = unit[:p]
            break
    return len(unit) >= (_MIN_CJK if all(_ONE_CJK.fullmatch(t) for t in unit) else _MIN_WORDS)


# Closing lines Whisper writes on its own ("Thank you so much for watching"), longest first (see
# drop_sign_offs). The ones for watching or listening may run on to the end of their sentence.
_SIGN_OFFS = sorted({opening + middle + ending
                     for opening in (("thank", "you"), ("thanks",))
                     for middle in (("so", "much"), ("very", "much"), ())
                     for ending in (("for", "watching"), ("for", "listening"), ())}, key=len, reverse=True)
_RUN_ON = {"watching", "listening"}
_RUN_ON_WORDS = 25
# The Chinese ones, without punctuation and in Simplified characters (see _T2S). 謝謝大家 alone is
# how many lecturers end, so these say what was watched or listened to.
_ZH_SIGN_OFFS = {opening + middle + ending for opening in ("谢谢", "感谢", "多谢")
                 for middle in ("", "大家", "大家的", "您的", "你的") for ending in ("观看", "收看", "收听")}
_ZH_SENTENCE_END = ("。", "！", "？", ".", "!", "?")
_ZH_CLAUSE_END = _ZH_SENTENCE_END + ("，", "、", "；", "：", ",", ";", ":")
_ZH_PAUSE = 1.0  # seconds of silence between Chinese words that part them like a 。
# Whisper writes Chinese in either script. The Traditional characters of the Chinese lines here,
# mapped one for one to Simplified, so the text keeps its length and the positions in it.
_T2S = str.maketrans("請點贊讚訂閱轉發賞鏡與欄歡編區願優獨劇場謝觀聽", "请点赞赞订阅转发赏镜与栏欢编区愿优独剧场谢观听")
# Chinese words come without spaces, so in the text _drop_credits matches, a pause before one is
# marked with this. It is no space: it never sets a name apart from 字幕志愿者.
_PAUSE_MARK = chr(0)
_SEP = rf"[\s,，、{_PAUSE_MARK}]*"
_END = rf"(?=[\s,，.。!！?？{_PAUSE_MARK}]|$)"  # the line ends here
# Credits and appeals from subtitled videos, which nobody says in a recording.
_CREDITS = re.compile(
    r"\b(?:sub)?titles?\s+(?:by|from)\s+(?:the\s+)?amara\.org(?:\s+community)?|\bamara\.org(?:\s+community)?"
    r"|\b(?:transcription|subtitles|captions)\s+by\s+castingwords\b|\bcastingwords\b"
    r"|\btranscription\s+by\s+eso\b[.,]?(?:\s+translation\s+by\b[^.!?]*)?"
    r"|\b(?:please\s+)?(?:don'?t\s+forget\s+to\s+)?like,?\s+(?:share,?\s+)?(?:comment,?\s+)?and\s+subscribe\b"
    r"(?:\s+to\s+(?:our|my|the)\s+channel)?[.!]?"
    r"|\b(?:please\s+)?subscribe\s+to\s+(?:our|my|the)\s+channel\b[.!]?"
    # Chinese ones Whisper writes on silence, music and noise (openai/whisper discussion #2244,
    # SYSTRAN/faster-whisper issue #587): a channel's appeal, subtitle credits, a video site's
    # tag line. Matched in Simplified characters (see _T2S).
    r"|(?:小编)?字幕由\s*amara\.org\s*社区提供"
    rf"|请不吝点赞{_SEP}订阅{_SEP}转发(?:{_SEP}打赏)?(?:{_SEP}支持明镜与点点栏目)?"
    rf"|(?:点赞{_SEP}订阅{_SEP}转发{_SEP})?(?:打赏{_SEP})?支持明镜与点点栏目|明镜与点点栏目"
    rf"|明镜需要[您你]的支持|欢迎订阅明镜{_END}"
    rf"|(?:中文)?字幕志愿者[\s:：]+[{_CJK}]{{2,3}}{_END}"  # and the volunteer's name, set apart
    rf"|(?:优优独播剧场[\s\-—–{_PAUSE_MARK}]*)?yoyo\s+television\s+series\s+exclusive|优优独播剧场",
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

    Chinese credits and appeals (請不吝點贊…, 字幕志願者 and a name) go the same way, in either
    script. Chinese sign-offs (謝謝觀看, 感謝收聽) are held to the English rule but never run
    on: no Chinese test audio made Whisper write them, so the rule rests on the English findings.
    """
    words = _drop_credits(words)
    kept, i = [], 0
    while i < len(words):
        length = (_sign_off_length(words, i) or _zh_sign_off_length(words, i)) if words[i].prob < max_p else 0
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


def _zh_sign_off_length(words: list[Word], i: int) -> int:
    """Like _sign_off_length, for _ZH_SIGN_OFFS. Whisper writes Chinese a character or two per
    word, so the phrase is matched on the words' joined text. It must be a sentence of its own:
    start the text or come after punctuation or a pause (非常感謝收看 stays), and end with a 。,
    ！ or ？, the text or a pause, since Whisper often leaves the 。 out."""
    def bare(word: Word) -> str:
        return re.sub(r"[^\w]", "", word.text).translate(_T2S)

    def pause_before(k: int) -> bool:
        return words[k].start - words[k - 1].end >= _ZH_PAUSE

    if i and not words[i - 1].text.rstrip().endswith(_ZH_CLAUSE_END) and not pause_before(i):
        return 0
    said, k = bare(words[i]), i
    while said and any(phrase.startswith(said) for phrase in _ZH_SIGN_OFFS):
        if said in _ZH_SIGN_OFFS:
            end = k + 1
            while end < len(words) and not bare(words[end]):
                end += 1  # punctuation on its own
            tail = "".join(w.text for w in words[k:end]).rstrip()
            if tail.endswith(_ZH_SENTENCE_END) or end == len(words) or pause_before(end):
                return end - i
            return 0
        if k + 1 == len(words) or words[k].text.rstrip().endswith(_ZH_SENTENCE_END):
            return 0  # the text or the sentence ends before the phrase does
        k += 1
        said += bare(words[k])
    return 0


def _drop_credits(words: list[Word]) -> list[Word]:
    """`words` without the ones a _CREDITS match covers in their joined text. A Chinese word after
    a pause gets _PAUSE_MARK before it, so a line Whisper wrote on its own ends there; English
    words bring their spaces, so their text is joined as it is."""
    pieces, starts, at = [], [], 0
    for k, word in enumerate(words):
        if k and _ONE_CJK.match(word.text) and word.start - words[k - 1].end >= _ZH_PAUSE:
            pieces.append(_PAUSE_MARK)
            at += len(_PAUSE_MARK)
        starts.append(at)
        pieces.append(word.text)
        at += len(word.text)
    text = "".join(pieces)
    covered = [False] * len(text)
    for match in _CREDITS.finditer(text.translate(_T2S)):  # one character for one: positions hold
        covered[match.start():match.end()] = [True] * (match.end() - match.start())
    if not any(covered):
        return words
    return [word for word, start in zip(words, starts)
            if not any(covered[k] and not text[k].isspace() for k in range(start, start + len(word.text)))]


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


# A clip can hold natural pauses up to about 1.6 s (voice regions 1 s apart are joined, each
# padded 0.3 s); the quiet stretches the original's text left inside clips on real lectures
# lasted 6-10 s.
INNER_GAP = 3.0


def inner_gaps(clip: tuple[float, float], words: list[Word], gap: float = INNER_GAP) -> list[tuple[float, float]]:
    """The holes inside `clip` where the text pauses for more than `gap` seconds. Used only for
    the levelled copy's clips (see Transcriber._fill_quiet): there the voice detector heard speech
    all through, so a long pause in the original's text is speech it left out."""
    start, end = clip
    kept = drop_sign_offs(sorted(words, key=lambda w: w.start))
    holes = [(max(prev.end, start), min(nxt.start, end)) for prev, nxt in zip(kept, kept[1:])
             if nxt.start - prev.end > gap]
    return [(a, b) for a, b in holes if b > a]


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


def _union(regions: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """Overlapping or touching time regions merged, in order."""
    merged: list[tuple[float, float]] = []
    for start, end in sorted(regions):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


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

    def transcribe(self, audio: np.ndarray, language: str | None = None,
                   hotwords: str | None = None,
                   progress: Callable[[float], None] | None = None,
                   cancel: threading.Event | None = None, quiet: np.ndarray | None = None) -> AsrResult:
        """Decodes clip by clip (see speech_clips): sequential decoding keeps punctuation and word
        timing best, and speaker attribution depends on both. Batched decoding ("fast mode", ~3x
        faster on a GPU) was removed: in tests it dropped whole sentences without a warning.

        `quiet` is a volume-levelled copy of `audio` ("Even out volume"). It is only used to find
        speech the original leaves without text, which is then decoded from the copy (see
        _fill_quiet). On three real lectures, Whisper on levelled audio got more terms wrong and put
        more speaker changes mid-sentence, while levelling let the voice detector hear quiet
        stretches the original lost entirely (up to 346 words in one lecture)."""
        duration = len(audio) / SAMPLE_RATE
        options = dict(language=language or None, word_timestamps=True, beam_size=5,
                       hotwords=hotwords or None)
        clips = speech_clips(audio)
        if not clips:
            return AsrResult(language or "", 0.0, [])  # "" = unknown, nothing was heard
        pieces, info = self._decode_clips(audio, clips, options)
        speech = list(clips)
        scale = 1.0 if quiet is None else 0.9  # the rest is for the quiet stretches

        words: list[Word] = []
        for piece, done in pieces:  # generator: decoding happens while iterating
            if cancel is not None and cancel.is_set():
                raise Cancelled()
            words += piece
            if progress is not None and duration > 0:
                progress(done * scale)
        if quiet is not None:
            filled, heard = self._fill_quiet(quiet, words, options, info.language, cancel)
            words += filled
            speech = _union(speech + heard)
            if progress is not None:
                progress(1.0)
        words.sort(key=lambda w: w.start)
        return AsrResult(info.language, float(info.language_probability), words, speech)

    def _fill_quiet(self, quiet: np.ndarray, words: list[Word], options: dict, language: str,
                    cancel: threading.Event | None) -> tuple[list[Word], list[tuple[float, float]]]:
        """(words to add, the speech the levelled copy let the voice detector hear). Clips of the
        levelled copy whose parts `words` leave without text, at the edges (see uncovered) or inside
        (see inner_gaps), are decoded from the copy, without the word bank as in its own fallback,
        and those parts filled (see fill_gaps)."""
        clips = speech_clips(quiet)
        by_clip = _in_clip(words, clips)
        gaps = {k: uncovered(clip, by_clip.get(k, [])) + inner_gaps(clip, by_clip.get(k, []))
                for k, clip in enumerate(clips)}
        todo = [k for k, parts in gaps.items() if parts]
        if not todo:
            return [], clips
        plain = {**options, "hotwords": None, "language": language}
        found, _ = self.model.transcribe(quiet, vad_filter=False, clip_timestamps=[t for k in todo for t in clips[k]],
                                         condition_on_previous_text=False, **plain)
        again: list[Word] = []
        for seg in found:  # generator: decoding happens while iterating
            if cancel is not None and cancel.is_set():
                raise Cancelled()
            again += _words_of(seg)
        redone = _in_clip(again, [clips[k] for k in todo])
        filled: list[Word] = []
        for n, k in enumerate(todo):
            kept = drop_sign_offs(sorted(by_clip.get(k, []), key=lambda w: w.start))
            filled += fill_gaps(gaps[k], kept, redone.get(n, []))
        return filled, clips

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
