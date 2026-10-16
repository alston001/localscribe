"""Transcript data model, saved as <name>_transcript.json next to the exports.

Exporters (and a future proofreading editor) only depend on this structure.

Text rule: `Segment.text` is the truth. `words` add timing and confidence, and are only used
while their joined text still equals `text` (export.common.segment_words); once `text` is
edited without updating them, exporters fall back to `text` with the segment's times.

Compatibility: `load` ignores keys it does not know, fills fields added later with their
defaults, and refuses files from a newer FORMAT_VERSION instead of silently dropping data.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

from .errors import UserError

FORMAT_VERSION = 1


@dataclass
class TWord:
    start: float
    end: float
    text: str
    prob: float


@dataclass
class Segment:
    speaker: str  # key into Transcript.speakers
    start: float
    end: float
    text: str
    words: list[TWord] = field(default_factory=list)


@dataclass
class Gap:
    """A long stretch in which no text came out (see asr.text_gaps)."""
    start: float
    end: float
    speech: bool = False  # the voice detector heard speech there, so something may be missing


@dataclass
class Transcript:
    source: str  # the recording's file name (files before 0.2 hold a full path; use source_name)
    duration: float
    language: str
    created: str
    app_version: str
    settings: dict
    speakers: dict[str, str]  # id -> display name, in order of first appearance
    segments: list[Segment]
    # Problems that degraded this transcript without stopping it: {"key": i18n key, **format args}
    warnings: list[dict] = field(default_factory=list)
    # Long stretches without text, in time order. Shown only while no segment overlaps them
    # (an editor may fill one in), like words that no longer match their text.
    gaps: list[Gap] = field(default_factory=list)

    @property
    def source_name(self) -> str:
        return Path(self.source).name

    def speaker_name(self, speaker_id: str) -> str:
        return self.speakers.get(speaker_id, speaker_id)

    def to_dict(self) -> dict:
        data = asdict(self)
        data["format_version"] = FORMAT_VERSION
        for seg in data["segments"]:
            seg["start"], seg["end"] = round(seg["start"], 3), round(seg["end"], 3)
            for w in seg["words"]:
                w["start"], w["end"], w["prob"] = round(w["start"], 3), round(w["end"], 3), round(w["prob"], 3)
        for gap in data["gaps"]:
            gap["start"], gap["end"] = round(gap["start"], 3), round(gap["end"], 3)
        return data

    def save(self, path: Path) -> None:
        """Written to a temporary file first, so a failed save never destroys the old one."""
        path = Path(path)
        tmp = path.with_name(path.name + ".tmp")
        try:
            tmp.write_text(json.dumps(self.to_dict(), ensure_ascii=False, indent=1), encoding="utf-8")
            os.replace(tmp, path)
        except BaseException:
            tmp.unlink(missing_ok=True)
            raise

    @classmethod
    def load(cls, path: Path) -> "Transcript":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        version = data.get("format_version", 1)
        if not isinstance(version, int) or version > FORMAT_VERSION:
            raise UserError("err_transcript_newer", version=version)
        segments = [_known(Segment, {**s, "words": [_known(TWord, w) for w in s.get("words", [])]})
                    for s in data["segments"]]
        # Gaps are extras: a damaged one is dropped rather than making the transcript unreadable.
        gaps = [_known(Gap, g) for g in data.get("gaps") or [] if isinstance(g, dict) and {"start", "end"} <= g.keys()]
        return _known(cls, {**data, "segments": segments, "gaps": gaps})


def _known(cls, data: dict):
    """cls(**data) without the keys cls doesn't have (written by a newer app or an editor)."""
    names = {f.name for f in fields(cls)}
    return cls(**{k: v for k, v in data.items() if k in names})
