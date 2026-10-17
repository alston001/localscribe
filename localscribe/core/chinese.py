"""Chinese transcripts in Traditional characters.

Whisper often writes Chinese in Simplified characters, also for speakers from Taiwan. OpenCC
(Apache 2.0) converts the text: "tw" (the default) changes only the characters (软件 to 軟件);
"tw_phrases" also changes Mainland wording to Taiwan's (软件 to 軟體, 打开 to 開啟), so it can
change the words the speaker said; "off" keeps what Whisper wrote. Words keep their times and
probabilities, and terms from the word bank and Names and terms keep the user's spelling.
"""

from __future__ import annotations

import difflib
import re
from dataclasses import replace
from functools import lru_cache
from typing import Callable, Iterable

from .asr import Word

STYLES = ("tw", "tw_phrases", "off")  # the default first
_CONFIGS = {"tw_phrases": "s2twp", "tw": "s2tw"}
_CJK = re.compile(r"[㐀-鿿豈-﫿]")
_SENTENCE_END = ("。", "！", "？", ".", "!", "?")
_CHUNK_WORDS = 200  # bounds the alignment work; phrases don't run across sentences anyway
_PLACEHOLDER = 0xE000  # private-use characters hold kept terms' places; OpenCC leaves them alone


def normalize_style(style: str) -> str:
    return style if style in STYLES else "tw"


@lru_cache(maxsize=None)
def _converter(config: str) -> Callable[[str], str]:
    import opencc

    return opencc.OpenCC(config).convert


def to_traditional(words: list[Word], style: str, keep: Iterable[str] = ()) -> list[Word]:
    """`words` with their text in Traditional Chinese (see the module docstring for `style`).
    `keep`: terms to spell exactly as given, in whichever script Whisper wrote them."""
    style = normalize_style(style)
    if style == "off" or not words:
        return words
    convert = _converter(_CONFIGS[style])
    variants = _variants(keep)
    out: list[Word] = []
    for chunk in _chunks(words):
        out += _convert_chunk(chunk, convert, variants)
    return out


def _variants(keep: Iterable[str]) -> list[tuple[str, str]]:
    """(spelling Whisper may write, the term to put back), longest first. A term from the word
    bank may come out in Simplified or Traditional characters; either way the user's spelling wins."""
    pairs: dict[str, str] = {}
    for term in keep:
        if not _CJK.search(term):
            continue  # OpenCC leaves Latin letters alone
        for form in (term, _converter("t2s")(term), _converter("s2t")(term)):
            pairs.setdefault(form, term)
    return sorted(pairs.items(), key=lambda pair: len(pair[0]), reverse=True)


def _chunks(words: list[Word]) -> Iterable[list[Word]]:
    chunk: list[Word] = []
    for word in words:
        chunk.append(word)
        if word.text.rstrip().endswith(_SENTENCE_END) or len(chunk) >= _CHUNK_WORDS:
            yield chunk
            chunk = []
    if chunk:
        yield chunk


def _convert_chunk(chunk: list[Word], convert: Callable[[str], str], variants: list[tuple[str, str]]) -> list[Word]:
    original = "".join(w.text for w in chunk)
    if not _CJK.search(original):
        return chunk
    masked, restore = original, {}
    if variants:
        pattern = re.compile("|".join(re.escape(form) for form, _ in variants))
        terms = dict(variants)

        def hold(match: re.Match) -> str:
            mark = chr(_PLACEHOLDER + len(restore))
            restore[mark] = terms[match.group(0)]
            return mark

        masked = pattern.sub(hold, original)
    # OpenCC writes Taiwan's formal 臺; everyday writing, and most people, use 台 (颱 is another word).
    final = convert(masked).replace("臺", "台")
    for mark, term in restore.items():
        final = final.replace(mark, term)
    if final == original:
        return chunk
    return _spread(chunk, original, final)


def _spread(chunk: list[Word], original: str, final: str) -> list[Word]:
    """The converted text dealt back to the words it came from. Where a phrase changed length
    (代码 to 程式碼), its words share the new text in order."""
    owner = [i for i, word in enumerate(chunk) for _ in word.text]  # word index of each original character
    pieces: list[list[str]] = [[] for _ in chunk]
    if len(final) == len(original):
        for k, char in enumerate(final):
            pieces[owner[k]].append(char)
    else:
        for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, original, final, autojunk=False).get_opcodes():
            if tag == "equal":
                for k in range(i2 - i1):
                    pieces[owner[i1 + k]].append(final[j1 + k])
            elif tag == "insert":  # new text with nothing in its place: the word before it takes it
                pieces[owner[max(i1 - 1, 0)]].append(final[j1:j2])
            else:  # replace, delete: the words of the old text share the new text by their share of it
                owners = list(dict.fromkeys(owner[i1:i2]))
                counts = [owner[i1:i2].count(o) for o in owners]
                new, cut, seen = final[j1:j2], 0, 0
                for o, count in zip(owners, counts):
                    seen += count
                    end = round(len(new) * seen / (i2 - i1))
                    pieces[o].append(new[cut:end])
                    cut = end
    out: list[Word] = []
    pending_start = None  # a word left without text hands its time to its neighbours
    for word, piece in zip(chunk, pieces):
        text = "".join(piece)
        if not text:
            if out:
                out[-1] = replace(out[-1], end=max(out[-1].end, word.end))
            else:
                pending_start = word.start if pending_start is None else pending_start
            continue
        start = min(word.start, pending_start) if pending_start is not None else word.start
        out.append(replace(word, text=text, start=start))
        pending_start = None
    return out
