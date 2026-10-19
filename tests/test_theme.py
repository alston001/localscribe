"""Light and dark themes: the setting, readable colors in both, and the windows that use them."""

import json
import os
import subprocess
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def luminance(color: str) -> float:
    def channel(value: int) -> float:
        c = value / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = (int(color[i:i + 2], 16) for i in (1, 3, 5))
    return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)


def contrast(a: str, b: str) -> float:
    high, low = sorted((luminance(a), luminance(b)), reverse=True)
    return (high + 0.05) / (low + 0.05)


# ---- the setting ---------------------------------------------------------------------
def test_the_theme_follows_windows_by_default_and_survives_a_restart(tmp_path):
    from localscribe.config import Settings

    assert Settings().theme == "system"
    Settings(theme="dark").save(tmp_path / "settings.json")
    assert Settings.load(tmp_path / "settings.json").theme == "dark"
    (tmp_path / "bad.json").write_text(json.dumps({"theme": "purple"}), encoding="utf-8")
    assert Settings.load(tmp_path / "bad.json").theme == "system"


def test_follow_windows_takes_the_theme_windows_uses():
    from PySide6.QtCore import Qt

    from localscribe.ui import style

    assert style.resolve("system", Qt.ColorScheme.Dark) is style.DARK
    assert style.resolve("system", Qt.ColorScheme.Light) is style.LIGHT
    assert style.resolve("system", Qt.ColorScheme.Unknown) is style.LIGHT
    assert style.resolve("dark", Qt.ColorScheme.Light) is style.DARK
    assert style.resolve("light", Qt.ColorScheme.Dark) is style.LIGHT


# ---- colors ------------------------------------------------------------------------------
@pytest.mark.parametrize("name", ["LIGHT", "DARK"])
def test_text_stays_readable_in_both_themes(name):
    # WCAG AA asks 4.5:1 for normal text (disabled text is exempt).
    from localscribe.ui import style

    t = getattr(style, name)
    for fg, bg in [(t.text, t.surface), (t.text, t.window), (t.text, t.hover), (t.text, t.alternate),
                   (t.text, t.selection), (t.text, t.info_bg), (t.muted, t.surface), (t.muted, t.window),
                   (t.accent_text, t.surface), (t.danger, t.surface), (t.success, t.surface),
                   (t.warning, t.surface), ("#FFFFFF", t.accent), ("#E5E7EB", t.log)]:
        assert contrast(fg, bg) >= 4.5, (name, fg, bg, round(contrast(fg, bg), 2))


def test_the_dark_style_sheet_paints_only_dark_backgrounds():
    import re

    from localscribe.ui import style

    t = style.DARK
    sheet = style.style_sheet(t, {"check": "c.png", "down": "d.png", "up": "u.png"})
    backgrounds = set(re.findall(r"background(?:-color)?:\s*([^;}]+?)\s*[;}]", sheet))
    dark = {t.surface, t.window, t.hover, t.row_hover, t.selection, t.alternate, t.info_bg, t.log, t.border,
            t.accent, t.accent_dark, t.accent_soft, t.danger, "transparent"}
    assert backgrounds and backgrounds <= dark, backgrounds - dark


def test_the_file_list_colors_its_statuses_from_the_theme(monkeypatch):
    from PySide6.QtCore import Qt

    from localscribe.ui import jobs, style

    model = jobs.JobTableModel()
    [job] = model.add([Path("talk.wav")])
    job.status = "done"
    monkeypatch.setattr(style, "current", style.DARK)
    assert model.data(model.index(0, 2), Qt.ForegroundRole).name() == style.DARK.success.lower()
    monkeypatch.setattr(style, "current", style.LIGHT)
    assert model.data(model.index(0, 2), Qt.ForegroundRole).name() == style.LIGHT.success.lower()


# ---- the windows -------------------------------------------------------------------------
def test_changing_the_theme_in_settings_applies_it_at_once(monkeypatch):
    from localscribe.config import Settings
    from localscribe.ui import main_window, style

    applied = []
    monkeypatch.setattr(style, "apply", lambda app, theme="system": applied.append(theme))

    class Dialog:
        Accepted = 1

        def __init__(self, settings, bundled, parent, on_update_checked=None):
            self.settings = Settings(**{**vars(settings), "theme": "dark"})

        def exec(self):
            return self.Accepted

    monkeypatch.setattr(main_window, "SettingsDialog", Dialog)
    window = types.SimpleNamespace(settings=Settings(), _save_settings=lambda: None, retranslate=lambda: None,
                                   _update_status_bar=lambda: None,
                                   engine=types.SimpleNamespace(update_settings=lambda s: None),
                                   _on_manual_update_check=lambda *a: None)
    main_window.MainWindow.open_settings(window)
    assert applied == ["dark"]
    main_window.MainWindow.open_settings(window)  # dark again: nothing to change
    assert applied == ["dark"]


SCRIPT = r'''
import json, sys
from pathlib import Path
from localscribe import paths
paths.user_data_dir = lambda: Path(sys.argv[1])
from PySide6.QtGui import QPalette
from PySide6.QtWidgets import QApplication
app = QApplication([])
from localscribe import i18n
i18n.set_language("zh_TW")
from localscribe.config import Settings
from localscribe.ui import style
from localscribe.ui.settings_dialog import SettingsDialog

out = {}
style.apply(app, "dark")
out["dark"] = [app.palette().color(QPalette.Window).name(), app.palette().color(QPalette.Text).name(),
               style.current.name, "#1f2937" in app.styleSheet().lower()]
out["dark_arrow"] = (Path(sys.argv[1]) / "ui" / "dark" / "down.png").is_file()
style.apply(app, "light")
out["light"] = [app.palette().color(QPalette.Window).name(), style.current.name]
dialog = SettingsDialog(Settings(), [])
out["choices"] = [dialog.cmb_theme.itemText(i) for i in range(dialog.cmb_theme.count())]
out["picked"] = dialog.cmb_theme.currentData()
dialog.cmb_theme.setCurrentIndex(dialog.cmb_theme.findData("dark"))
dialog.accept()
out["saved"] = dialog.settings.theme
print(json.dumps(out))
'''


def test_the_app_switches_theme_and_settings_offer_the_three_choices(tmp_path):
    from localscribe.ui import style

    env = {**os.environ, "QT_QPA_PLATFORM": "offscreen"}
    proc = subprocess.run([sys.executable, "-c", SCRIPT, str(tmp_path)], cwd=ROOT, env=env,
                          capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert proc.returncode == 0, proc.stderr
    out = json.loads(proc.stdout.strip().splitlines()[-1])
    assert out["dark"] == [style.DARK.window.lower(), style.DARK.text.lower(), "dark", True]
    assert out["dark_arrow"]  # the combo boxes' arrows, drawn in the dark theme's color
    assert out["light"] == [style.LIGHT.window.lower(), "light"]
    assert out["choices"] == ["跟隨 Windows", "淺色", "深色"]
    assert out["picked"] == "system" and out["saved"] == "dark"
