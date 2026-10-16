"""Combine Whisper words with diarization turns into speaker-attributed utterances."""

from __future__ import annotations

import re

import numpy as np

from .asr import Word
from .diarization import Turn

DEFAULT_SPEAKER = "SPEAKER_00"
_SENTENCE_END = (".", "?", "!", "…", "。", "？", "！")
_CLAUSE_MARK = (",", ";", ":", "-", "–", "—", "，", "、", "；", "：")
_SPACES = re.compile(r"\s+")


def ends_sentence(text: str) -> bool:
    return text.rstrip().rstrip("\"'”’)]").endswith(_SENTENCE_END)


def join_words(words: list[Word]) -> str:
    return _SPACES.sub(" ", "".join(w.text for w in words)).strip()


def assign_speakers(words: list[Word], turns: list[Turn]) -> tuple[list[str], np.ndarray]:
    """Speaker for every word by largest time overlap; words in gaps take the nearest turn.

    Returns (labels, coverage); coverage is the fraction of each word covered by its speaker.
    """
    n = len(words)
    if n == 0:
        return [], np.zeros(0)
    if not turns:
        return [DEFAULT_SPEAKER] * n, np.ones(n)

    speakers = sorted({t.speaker for t in turns})
    index = {s: i for i, s in enumerate(speakers)}
    t_start = np.array([t.start for t in turns])
    t_end = np.array([t.end for t in turns])
    t_spk = np.array([index[t.speaker] for t in turns])
    onehot = np.zeros((len(turns), len(speakers)))
    onehot[np.arange(len(turns)), t_spk] = 1.0

    w_start = np.array([w.start for w in words])
    w_end = np.maximum(np.array([w.end for w in words]), w_start + 0.02)
    labels = np.empty(n, dtype=int)
    coverage = np.empty(n)
    step = 1024
    for i in range(0, n, step):
        ws, we = w_start[i:i + step, None], w_end[i:i + step, None]
        overlap = np.clip(np.minimum(we, t_end) - np.maximum(ws, t_start), 0.0, None)
        per_speaker = overlap @ onehot
        best = per_speaker.argmax(axis=1)
        best_val = per_speaker[np.arange(len(best)), best]
        gap = best_val <= 0
        if gap.any():
            mid = ((ws + we) / 2)[gap]
            distance = np.clip(np.maximum(t_start - mid, mid - t_end), 0.0, None)
            best[gap] = t_spk[distance.argmin(axis=1)]
        labels[i:i + step] = best
        coverage[i:i + step] = best_val / (we - ws)[:, 0]
    return [speakers[k] for k in labels], coverage


def sentence_spans(words: list[Word], pause: float = 1.5) -> list[tuple[int, int]]:
    """[start, end) word ranges split at sentence punctuation or pauses over `pause` s."""
    spans, start = [], 0
    for k, word in enumerate(words):
        last = k == len(words) - 1
        if last or ends_sentence(word.text) or words[k + 1].start - word.end > pause:
            spans.append((start, k + 1))
            start = k + 1
    return spans


def _runs(labels: list[str], start: int, end: int):
    run_start = start
    for k in range(start + 1, end + 1):
        if k == end or labels[k] != labels[run_start]:
            yield run_start, k
            run_start = k


def _no_break(prev: Word, word: Word) -> bool:
    """True if nothing separates two words: they touch (Whisper gives such words one
    shared boundary) and no comma or other mark stands between them."""
    return word.start - prev.end <= 0.01 \
        and not prev.text.rstrip().rstrip("\"'”’)]").endswith(_CLAUSE_MARK)


def smooth_speakers(words: list[Word], labels: list[str], coverage: np.ndarray,
                    max_words: int = 2, max_duration: float = 1.0,
                    majority: float = 0.7, pause: float = 0.3) -> list[str]:
    """Fix boundary jitter: Whisper timestamps are ~0.1-0.3 s off and diarization turns
    start or end a little late or early, so the first or last words of a sentence often
    land in the neighbouring speaker's turn.

    Up to max_words words move at a time. In the sentence-majority pass they span at most
    max_duration seconds; in the sentence-edge pass they hold at most that long inside
    their speaker's turns, and a silence over `pause` seconds ends a stretch the way a
    sentence end does.
    """
    given, labels = labels, list(labels)
    spans = sentence_spans(words)
    for s, e in spans:
        share: dict[str, float] = {}
        for k in range(s, e):
            share[labels[k]] = share.get(labels[k], 0.0) + max(words[k].end - words[k].start, 0.02)
        if len(share) < 2:
            continue
        major, major_dur = max(share.items(), key=lambda kv: kv[1])
        if major_dur / sum(share.values()) < majority:
            continue  # genuinely mixed sentence; leave it split
        for rs, re_ in list(_runs(labels, s, e)):
            if labels[rs] != major and re_ - rs <= max_words \
                    and words[re_ - 1].end - words[rs].start <= max_duration:
                labels[rs:re_] = [major] * (re_ - rs)

    def held(k: int) -> float:
        """Seconds of word k inside its current speaker's turns. For a word the first pass
        relabelled, the part outside its old speaker's turns stands in."""
        part = coverage[k] if labels[k] == given[k] else 1.0 - coverage[k]
        return part * max(words[k].end - words[k].start, 0.02)

    # Sentence-edge pass: a sentence, or a stretch between pauses, split one or two words
    # from its start or end goes whole to the speaker of the rest, with no majority needed,
    # so the change lands at the sentence end or pause instead of "Show / me the result".
    # Only a change inside fluent speech moves: a reply after a silence or a comma
    # ("you know, / Right.") stays. The part that moves may hold at most 1.5 times as long
    # in its speaker's turns as the other part, since turn edges run late or early; if
    # both parts qualify, the one holding less moves.
    for s, e in sentence_spans(words, pause):
        runs = list(_runs(labels, s, e))
        if len(runs) != 2 or not _no_break(words[runs[1][0] - 1], words[runs[1][0]]):
            continue
        seconds = [sum(held(k) for k in range(rs, re_)) for rs, re_ in runs]
        movable = [i for i, (rs, re_) in enumerate(runs) if re_ - rs <= max_words
                   and seconds[i] <= min(max_duration, 1.5 * seconds[1 - i])]
        if movable:
            moved = min(movable, key=lambda i: seconds[i])
            rs, re_ = runs[moved]
            labels[rs:re_] = [labels[runs[1 - moved][0]]] * (re_ - rs)

    # A lone weakly-covered word between two words of the same speaker joins them,
    # unless it is a whole sentence on its own ("Yes.").
    whole_sentence = {s for s, e in spans if e - s == 1}
    for k in range(1, len(labels) - 1):
        if labels[k - 1] == labels[k + 1] != labels[k] and coverage[k] < 0.5 \
                and k not in whole_sentence:
            labels[k] = labels[k - 1]
    return labels


def group_utterances(words: list[Word], labels: list[str], max_gap: float = 3.0,
                     max_duration: float = 60.0, max_pause: float = 10.0) -> list[list[int]]:
    """Word-index groups: one per speaker turn. A long monologue is broken into
    paragraphs at sentence ends after long pauses or every ~minute, and anywhere after a
    silence over `max_pause` seconds: Whisper often leaves out the period before one, and
    inside a paragraph the silence would not show in the timestamps (nor leave room for a
    gap marker). 10 s is the pause that also ends a stretch of speech in asr.lost_speech."""
    groups: list[list[int]] = []
    current: list[int] = []
    for k, word in enumerate(words):
        if current:
            prev = words[current[-1]]
            pause = word.start - prev.end
            if labels[k] != labels[current[0]] or pause > max_pause:
                groups.append(current)
                current = []
            elif ends_sentence(prev.text) and (pause > max_gap or
                                               word.start - words[current[0]].start > max_duration):
                groups.append(current)
                current = []
        current.append(k)
    if current:
        groups.append(current)
    return groups
