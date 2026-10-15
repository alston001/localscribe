"""Transcript data model, saved as <name>_transcript.json next to the exports.

Exporters (and a future proofreading editor) only depend on this structure.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

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
class Transcript:
    source: str
    duration: float
    language: str
    created: str
    app_version: str
    settings: dict
    speakers: dict[str, str]  # id -> display name, in order of first appearance
    segments: list[Segment]

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
        return data

    def save(self, path: Path) -> None:
        Path(path).write_text(json.dumps(self.to_dict(), ensure_ascii=False, indent=1), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> "Transcript":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        data.pop("format_version", None)
        segments = [Segment(**{**s, "words": [TWord(**w) for w in s.get("words", [])]})
                    for s in data.pop("segments")]
        return cls(**data, segments=segments)
