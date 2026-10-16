"""User settings, saved as JSON in %LOCALAPPDATA%\\LocalScribe\\settings.json."""

from __future__ import annotations

import json
import logging
import os
import shutil
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

from . import paths
from .core.diarization import SpeakerCount
from .core.pipeline import EngineSettings, JobOptions
from .export import FORMATS
from .export.common import ExportOptions

log = logging.getLogger("localscribe")

# Scenario presets fill in the speaker count and audio clean-up. Keep caps generous: on a
# real class with 7 voices, capping pyannote at 5 split the lecturer into two speakers.
PRESETS = {
    "interview": {"speaker_mode": "exact", "speakers_exact": 2, "normalize": False, "denoise": False},
    "focus_group": {"speaker_mode": "range", "speakers_min": 2, "speakers_max": 10, "normalize": True, "denoise": False},
    "lecture": {"speaker_mode": "auto", "normalize": True, "denoise": False},
    "online": {"speaker_mode": "auto", "normalize": True, "denoise": True},
}
PRESET_ORDER = ["interview", "focus_group", "lecture", "online", "custom"]

# Transcription languages offered in the main window; code None means detect.
LANGUAGE_CHOICES = [("en", "English"), ("auto", None), ("zh", "中文"), ("ja", "日本語"),
                    ("ko", "한국어"), ("es", "Español"), ("fr", "Français"), ("de", "Deutsch")]

WHISPER_CHOICES = ["auto", "large-v3", "large-v3-turbo", "medium", "small", "base"]


@dataclass
class Settings:
    ui_language: str = ""          # "" = follow Windows on first start
    whisper_model: str = "auto"
    device: str = "auto"
    diarizer: str = "auto"
    hotwords: str = ""
    vocabulary: str = ""           # chosen word bank's name; "" = none
    speaker_label: str = "Speaker"
    subtitle_speakers: bool = True
    models_dir: str = ""           # "" = default location
    preset: str = "interview"
    language: str = "en"
    speaker_mode: str = "exact"    # auto | exact | range
    speakers_exact: int = 2
    speakers_min: int = 2
    speakers_max: int = 6
    normalize: bool = False
    denoise: bool = False
    formats: list[str] = field(default_factory=lambda: ["docx", "txt"])
    timestamps: bool = True
    mark_uncertain: bool = False
    save_mode: str = "same"        # same | custom
    save_dir: str = ""
    convert_format: str = "m4a"
    convert_save_mode: str = "same"
    convert_save_dir: str = ""
    convert_add_queue: bool = False
    geometry: str = ""             # Qt window geometry, hex

    @classmethod
    def load(cls, path: Path | None = None) -> "Settings":
        path = Path(path or paths.settings_path())
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            return cls()  # first start
        try:
            data = json.loads(text)
            if not isinstance(data, dict):
                raise ValueError(f"expected an object, got {type(data).__name__}")
        except ValueError as exc:
            backup = path.with_name(path.name + ".bad")
            try:
                shutil.copyfile(path, backup)
            except OSError:
                backup = None
            log.warning("Ignoring unreadable settings file %s (%s); saved a copy as %s",
                        path.name, exc, backup.name if backup else "nothing")
            return cls()
        defaults = cls()
        clean = {}
        for f in fields(cls):
            value, wanted = data.get(f.name), type(getattr(defaults, f.name))
            # bool is an int subclass: "speakers_exact": true must not count as a number.
            if isinstance(value, wanted) and (wanted is bool or not isinstance(value, bool)):
                clean[f.name] = value
        settings = cls(**clean)
        settings.formats = [f for f in settings.formats if isinstance(f, str) and f in FORMATS]
        if settings.preset not in PRESET_ORDER:
            settings.preset = "custom"
        if settings.preset in PRESETS:
            # A preset's values can change between versions (0.1.0's lecture capped at 5
            # speakers). Hand edits already switch the preset to "custom", so re-apply.
            for key, value in PRESETS[settings.preset].items():
                setattr(settings, key, value)
        return settings

    def save(self, path: Path | None = None) -> None:
        target = Path(path or paths.settings_path())
        tmp = target.with_suffix(".tmp")
        tmp.write_text(json.dumps(asdict(self), ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, target)

    # ---- conversions for the pipeline -------------------------------------
    def models_path(self) -> Path:
        return Path(self.models_dir) if self.models_dir else paths.default_models_dir()

    def speaker_count(self) -> SpeakerCount:
        if self.speaker_mode == "exact":
            return SpeakerCount(exact=max(1, self.speakers_exact))
        if self.speaker_mode == "range":
            lo, hi = sorted((max(1, self.speakers_min), max(1, self.speakers_max)))
            return SpeakerCount(min=lo, max=hi)
        return SpeakerCount()

    def engine_settings(self) -> EngineSettings:
        bundled = paths.bundled_models_dir()
        return EngineSettings(models_dir=self.models_path(), extra_model_dirs=[bundled] if bundled else [],
                              whisper_model=self.whisper_model, device=self.device,
                              diarizer=self.diarizer)

    def job_options(self, hotwords: str | None = None) -> JobOptions:
        """`hotwords`: the word bank's terms combined with this field's (see vocabulary.prompt_terms)."""
        return JobOptions(language=None if self.language == "auto" else self.language,
                          speakers=self.speaker_count(), normalize=self.normalize, denoise=self.denoise,
                          hotwords=self.hotwords if hotwords is None else hotwords,
                          speaker_prefix=self.speaker_label)

    def export_options(self, ui_language: str) -> ExportOptions:
        return ExportOptions(lang=ui_language, timestamps=self.timestamps,
                             subtitle_speakers=self.subtitle_speakers, mark_uncertain=self.mark_uncertain)

    def matches_preset(self, name: str) -> bool:
        preset = PRESETS.get(name)
        return bool(preset) and all(getattr(self, k) == v for k, v in preset.items())
