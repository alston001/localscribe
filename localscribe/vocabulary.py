"""Word banks: small named lists of technical terms, e.g. one per course, that help Whisper
spell jargon it otherwise mishears.

Saved as JSON in %LOCALAPPDATA%\\LocalScribe\\vocabularies.json, never in the project folder.
"""

from __future__ import annotations

import json
import logging
import math
import os
import re
import shutil
from dataclasses import asdict, dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Iterable

from . import paths

log = logging.getLogger("localscribe")

FORMAT_VERSION = 1
# faster-whisper's get_prompt keeps the first max_length // 2 - 1 = 448 // 2 - 1 tokens of the
# hotwords and silently drops the rest.
PROMPT_LIMIT = 223
# Estimates without the model's tokenizer, from large-v3 and small: 54 real NLP terms joined
# with ", " took 210 tokens; Chinese terms take about 1.5 tokens a character, plus the comma,
# and the Latin letters in a mixed term such as "BERT 模型" about 0.35 each.
TOKENS_PER_TERM = 4
TOKENS_PER_CJK_CHAR = 1.5
TOKENS_PER_MIXED_CHAR = 0.35

_SEPARATORS = re.compile(r"[\n\r\t,，、]")
_CJK = re.compile(r"[\u2e80-\u9fff\uac00-\ud7af\uf900-\ufaff\uff00-\uffef]")  # also kana, Hangul, full-width


@dataclass
class Vocabulary:
    name: str
    terms: list[str] = field(default_factory=list)


def unique_terms(terms: Iterable[str]) -> list[str]:
    """Terms with tidy spaces, without empty ones and without repeats in any letter case;
    the first spelling wins."""
    seen: set[str] = set()
    result = []
    for term in terms:
        term = " ".join(term.split())
        if term and term.casefold() not in seen:
            seen.add(term.casefold())
            result.append(term)
    return result


def parse_terms(text: str) -> list[str]:
    """One term per line; commas (also ，and 、) and tabs separate terms too, as in a pasted list."""
    return unique_terms(_SEPARATORS.split(text))


def join_terms(terms: Iterable[str]) -> str:
    """The hotwords text Whisper gets."""
    return ", ".join(terms)


def prompt_terms(vocabulary: Vocabulary | None, hotwords: str) -> list[str]:
    """Terms for Whisper: the word bank's first, then the Names and terms field's (Settings)."""
    return unique_terms([*(vocabulary.terms if vocabulary else []), *parse_terms(hotwords)])


def find_vocabulary(vocabularies: Iterable[Vocabulary], name: str) -> Vocabulary | None:
    """The word bank with this name in any letter case; None for "" or a deleted one."""
    key = name.strip().casefold()
    return next((v for v in vocabularies if key and v.name.casefold() == key), None)


def replace_vocabulary(vocabularies: list[Vocabulary], old_name: str,
                       new: Vocabulary | None) -> list[Vocabulary]:
    """The list with `new` in place of the bank called old_name (last if there is none) and
    without any other bank of new's name; new=None deletes old_name."""
    names = {name.strip().casefold() for name in (old_name, new.name if new else "") if name.strip()}
    result, placed = [], new is None
    for vocabulary in vocabularies:
        if vocabulary.name.casefold() not in names:
            result.append(vocabulary)
        elif not placed:
            result.append(new)
            placed = True
    return result if placed else [*result, new]


# ---- the prompt limit -------------------------------------------------------------------
class TokenCounter:
    """Counts the tokens a list of terms takes in Whisper's prompt: exactly with the model's
    tokenizer, otherwise as an estimate."""

    def __init__(self, tokenizer=None):
        self.tokenizer = tokenizer  # a tokenizers.Tokenizer, or None to estimate

    @property
    def exact(self) -> bool:
        return self.tokenizer is not None

    def count(self, terms: list[str]) -> int:
        if not terms:
            return 0
        if self.tokenizer is None:
            return sum(_estimate(term) for term in terms)
        # The same text faster-whisper encodes: " " + hotwords.strip(), no special tokens.
        return len(self.tokenizer.encode(" " + join_terms(terms).strip(), add_special_tokens=False).ids)


def _estimate(term: str) -> int:
    cjk = len(_CJK.findall(term))
    if not cjk:
        return TOKENS_PER_TERM
    other = len("".join(_CJK.sub("", term).split()))
    return max(TOKENS_PER_TERM, 1 + math.ceil(TOKENS_PER_CJK_CHAR * cjk + TOKENS_PER_MIXED_CHAR * other))


@lru_cache(maxsize=4)
def _load_tokenizer(path: str):
    import tokenizers

    return tokenizers.Tokenizer.from_file(path)


def token_counter(store, model: str) -> TokenCounter:
    """A counter for this Whisper model (a ModelStore name such as "large-v3"). Models don't
    share tokenizers: small's splits some words into more pieces than large-v3's."""
    folder = store.whisper_path(model) if model else None
    file = folder / "tokenizer.json" if folder else None
    if file is not None and file.is_file():
        try:
            return TokenCounter(_load_tokenizer(str(file)))
        except Exception:
            log.warning("Could not read %s for %s; estimating token counts", file.name, model, exc_info=True)
    return TokenCounter()


def fit_terms(terms: Iterable[str], counter: TokenCounter,
              limit: int = PROMPT_LIMIT) -> tuple[list[str], list[str]]:
    """(terms that fit in Whisper's prompt, terms past the limit). A term that would only
    partly fit counts as past the limit: Whisper would get a fragment of it."""
    terms = list(terms)
    if counter.count(terms) <= limit:
        return terms, []
    kept: list[str] = []
    for i, term in enumerate(terms):
        if counter.count(kept + [term]) > limit:
            return kept, terms[i:]
        kept.append(term)
    return kept, []


# ---- storage --------------------------------------------------------------------------
def load_vocabularies(path: Path | None = None) -> list[Vocabulary]:
    """The saved word banks. A damaged file, or one with parts this version can't keep, is copied
    to .bad and logged, like settings.json. A file that exists but can't be read raises OSError
    instead of passing for "none yet", which the next save would overwrite."""
    path = Path(path or paths.vocabularies_path())
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        return []  # none made yet
    try:
        data = json.loads(raw.decode("utf-8-sig"))  # Notepad may add a BOM
        if not isinstance(data, dict) or not isinstance(data.get("vocabularies"), list):
            raise ValueError("expected an object with a list of vocabularies")
    except ValueError as exc:  # UnicodeDecodeError too: saved as UTF-16 or cp950
        _back_up(path, str(exc))
        return []
    vocabularies, names, lost = [], set(), 0
    for item in data["vocabularies"]:
        name = item.get("name") if isinstance(item, dict) else None
        if not isinstance(name, str) or not name.strip() or name.strip().casefold() in names:
            lost += 1
            continue
        terms = item.get("terms", [])
        if isinstance(terms, str):  # edited by hand as one comma-separated string
            terms = parse_terms(terms)
        elif not isinstance(terms, list):
            lost, terms = lost + 1, []
        good = [t for t in terms if isinstance(t, str)]
        lost += (len(good) < len(terms)) + bool(item.keys() - {"name", "terms"})
        names.add(name.strip().casefold())
        vocabularies.append(Vocabulary(name.strip(), unique_terms(good)))
    version = data.get("format_version", FORMAT_VERSION)
    if lost or data.keys() - {"format_version", "vocabularies"}:
        _back_up(path, "parts this version can't keep")  # the next save would lose them for good
    elif not isinstance(version, int) or version > FORMAT_VERSION:
        _back_up(path, f"format {version} is newer than this version reads")
    return vocabularies


def _back_up(path: Path, reason: str) -> None:
    backup = path.with_name(path.name + ".bad")
    try:
        shutil.copyfile(path, backup)
    except OSError:
        backup = None
    log.warning("Ignoring unreadable parts of %s (%s); saved a copy as %s",
                path.name, reason, backup.name if backup else "nothing")


def save_vocabularies(vocabularies: list[Vocabulary], path: Path | None = None) -> None:
    """Written to a temporary file first, so a failed save never destroys the old one."""
    target = Path(path or paths.vocabularies_path())
    tmp = target.with_name(target.name + ".tmp")
    data = {"format_version": FORMAT_VERSION, "vocabularies": [asdict(v) for v in vocabularies]}
    try:
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, target)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
