"""Where the app keeps its settings, models and logs."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from . import APP_NAME


def is_frozen() -> bool:
    """True when running from a PyInstaller build."""
    return bool(getattr(sys, "frozen", False))


def project_dir() -> Path:
    """Source checkout root (only meaningful when not frozen)."""
    return Path(__file__).resolve().parent.parent


def resource_dir() -> Path:
    """Read-only files shipped with the app (PyInstaller's _internal folder)."""
    if is_frozen():
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return project_dir()


def explorer_exe() -> str:
    """Full path, so a planted explorer.exe in the working folder or on PATH is never run."""
    return os.path.join(os.environ.get("WINDIR") or r"C:\Windows", "explorer.exe")


def user_data_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    path = Path(base) / APP_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def settings_path() -> Path:
    return user_data_dir() / "settings.json"


def log_path() -> Path:
    return user_data_dir() / "localscribe.log"


def vocabularies_path() -> Path:
    """The user's word banks: kept with the settings, never in the project folder."""
    return user_data_dir() / "vocabularies.json"


def default_models_dir() -> Path:
    """Writable model folder. A source checkout keeps models inside the project."""
    if is_frozen():
        return user_data_dir() / "models"
    return project_dir() / "models"


def bundled_models_dir() -> Path | None:
    """Models shipped inside the installer (read-only), if any."""
    path = resource_dir() / "models"
    return path if is_frozen() and path.is_dir() else None
