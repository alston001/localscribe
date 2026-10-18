"""Look and feel: light and dark themes (palette and style sheet), fonts and the app icon (all drawn;
no image files)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (QColor, QFont, QIcon, QLinearGradient, QPainter, QPainterPath, QPalette,
                           QPen, QPixmap)
from PySide6.QtWidgets import QApplication

from .. import paths


@dataclass(frozen=True)
class Theme:
    name: str
    accent: str         # filled buttons, checked boxes, focus; white text sits on it
    accent_dark: str    # the same, hovered
    accent_soft: str    # the same, disabled
    accent_text: str    # accent-colored text on a surface
    danger: str
    success: str
    warning: str
    border: str
    strong_border: str
    surface: str        # panels, fields, lists
    window: str         # behind the panels
    hover: str          # hovered buttons, read-only fields
    row_hover: str      # a hovered row in a list
    selection: str      # selected rows
    text: str
    muted: str
    disabled: str
    info_bg: str        # the update strip
    info_border: str
    alternate: str      # every other row
    log: str            # behind the log's light text, in both themes

    @property
    def status_colors(self) -> dict[str, str]:
        return {"done": self.success, "failed": self.danger, "stopped": self.warning, "running": self.accent_text}


# Every text color reads at 4.5:1 or more on the backgrounds it sits on (tests/test_theme.py).
LIGHT = Theme(name="light", accent="#2563EB", accent_dark="#1D4ED8", accent_soft="#93C5FD", accent_text="#2563EB",
              danger="#DC2626", success="#15803D", warning="#B45309", border="#D1D5DB", strong_border="#9CA3AF",
              surface="#FFFFFF", window="#F3F4F6", hover="#F9FAFB", row_hover="#F3F4F6", selection="#DBEAFE",
              text="#111827", muted="#646B78", disabled="#9CA3AF", info_bg="#EFF6FF", info_border="#BFDBFE",
              alternate="#F9FAFB", log="#111827")
DARK = Theme(name="dark", accent="#2563EB", accent_dark="#1D4ED8", accent_soft="#1E3A8A", accent_text="#60A5FA",
             danger="#F87171", success="#4ADE80", warning="#FBBF24", border="#374151", strong_border="#4B5563",
             surface="#1F2937", window="#111827", hover="#273449", row_hover="#273449", selection="#1E3A8A",
             text="#F3F4F6", muted="#9CA3AF", disabled="#6B7280", info_bg="#172554", info_border="#1E40AF",
             alternate="#232F3E", log="#0B1220")
current = LIGHT  # what apply() set last; widgets that paint themselves read their colors from it


def resolve(setting: str, scheme: Qt.ColorScheme) -> Theme:
    """The theme for Settings.theme: "light", "dark", or "system", which takes the one Windows uses."""
    if setting == "dark" or (setting == "system" and scheme == Qt.ColorScheme.Dark):
        return DARK
    return LIGHT


def _draw_assets(folder: Path, t: Theme) -> dict[str, str]:
    """Check mark and chevrons for the style sheet, at 1x and 2x for high-DPI screens."""
    folder.mkdir(parents=True, exist_ok=True)

    def save(name: str, size: int, color: str, points: list[tuple[float, float]], width: float) -> str:
        for scale, suffix in ((1, ""), (2, "@2x")):
            pix = QPixmap(size * scale, size * scale)
            pix.fill(Qt.transparent)
            p = QPainter(pix)
            p.setRenderHint(QPainter.Antialiasing)
            p.scale(scale, scale)
            p.setPen(QPen(QColor(color), width, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            p.drawPolyline([QPointF(x, y) for x, y in points])
            p.end()
            pix.save(str(folder / f"{name}{suffix}.png"))
        return (folder / f"{name}.png").as_posix()

    return {
        "check": save("check", 16, "#FFFFFF", [(3.5, 8.5), (6.8, 11.6), (12.5, 4.8)], 2.2),
        "down": save("down", 10, t.muted, [(1.5, 3.5), (5, 7), (8.5, 3.5)], 1.6),
        "up": save("up", 10, t.muted, [(1.5, 6.5), (5, 3), (8.5, 6.5)], 1.6),
    }


def style_sheet(t: Theme, a: dict[str, str]) -> str:
    return f"""
QMainWindow, QDialog {{ background: {t.window}; }}
QGroupBox {{
    background: {t.surface}; border: 1px solid {t.border}; border-radius: 8px;
    margin-top: 18px; padding: 10px 10px 8px 10px; font-weight: 600;
}}
QGroupBox::title {{ subcontrol-origin: margin; subcontrol-position: top left; left: 10px; top: 3px; padding: 0 4px; color: {t.text}; }}
QGroupBox QLabel, QGroupBox QCheckBox, QGroupBox QRadioButton {{ font-weight: normal; }}
QLabel:disabled, QCheckBox:disabled, QRadioButton:disabled {{ color: {t.disabled}; }}
QLabel#hint {{ color: {t.muted}; }}

QTableView {{
    background: {t.surface}; border: 1px solid {t.border}; border-radius: 8px;
    gridline-color: transparent; selection-background-color: {t.selection}; selection-color: {t.text};
    alternate-background-color: {t.alternate};
}}
QHeaderView::section {{
    background: {t.surface}; border: none; border-bottom: 1px solid {t.border};
    padding: 6px 8px; color: {t.muted}; font-weight: 600;
}}

QPushButton {{ background: {t.surface}; border: 1px solid {t.border}; border-radius: 6px; padding: 6px 14px; }}
QPushButton:hover {{ background: {t.hover}; border-color: {t.strong_border}; }}
QPushButton:checked {{ background: {t.selection}; border-color: {t.accent}; }}
QPushButton:disabled {{ color: {t.disabled}; background: {t.hover}; }}
QPushButton#primary {{ background: {t.accent}; color: white; border: none; font-weight: 600; font-size: 11pt; }}
QPushButton#primary:hover {{ background: {t.accent_dark}; }}
QPushButton#primary[running="true"] {{ background: {t.danger}; }}
QPushButton#primary:disabled {{ background: {t.accent_soft}; color: white; }}

QCheckBox, QRadioButton {{ spacing: 8px; }}
QCheckBox::indicator {{ width: 16px; height: 16px; border: 1px solid {t.strong_border}; border-radius: 4px; background: {t.surface}; }}
QCheckBox::indicator:hover {{ border-color: {t.accent}; }}
QCheckBox::indicator:checked {{ background: {t.accent}; border-color: {t.accent}; image: url({a["check"]}); }}
QCheckBox::indicator:disabled {{ background: {t.window}; border-color: {t.border}; }}
QCheckBox::indicator:checked:disabled {{ background: {t.accent_soft}; border-color: {t.accent_soft}; }}
QRadioButton::indicator {{ width: 16px; height: 16px; border: 1px solid {t.strong_border}; border-radius: 9px; background: {t.surface}; }}
QRadioButton::indicator:hover {{ border-color: {t.accent}; }}
QRadioButton::indicator:checked {{ width: 8px; height: 8px; border: 5px solid {t.accent}; }}
QRadioButton::indicator:disabled {{ background: {t.window}; border-color: {t.border}; }}
QRadioButton::indicator:checked:disabled {{ border-color: {t.accent_soft}; }}

QComboBox, QSpinBox, QLineEdit {{
    background: {t.surface}; border: 1px solid {t.border}; border-radius: 6px; padding: 4px 8px; min-height: 22px;
}}
QComboBox:hover, QSpinBox:hover, QLineEdit:hover {{ border-color: {t.strong_border}; }}
QComboBox:focus, QSpinBox:focus, QLineEdit:focus {{ border-color: {t.accent}; }}
QComboBox:disabled, QSpinBox:disabled, QLineEdit:disabled {{ color: {t.disabled}; background: {t.hover}; }}
QLineEdit:read-only {{ background: {t.hover}; color: {t.muted}; }}
QComboBox {{ padding-right: 26px; }}
QComboBox::drop-down {{ subcontrol-origin: padding; subcontrol-position: center right; width: 24px; border: none; }}
QComboBox::down-arrow {{ image: url({a["down"]}); width: 10px; height: 10px; }}
QComboBox QAbstractItemView {{
    background: {t.surface}; border: 1px solid {t.border}; outline: 0; padding: 4px;
    selection-background-color: {t.selection}; selection-color: {t.text};
}}
QSpinBox {{ padding-right: 22px; }}
QSpinBox::up-button {{ subcontrol-origin: border; subcontrol-position: top right; width: 20px; border: none; }}
QSpinBox::down-button {{ subcontrol-origin: border; subcontrol-position: bottom right; width: 20px; border: none; }}
QSpinBox::up-arrow {{ image: url({a["up"]}); width: 9px; height: 9px; }}
QSpinBox::down-arrow {{ image: url({a["down"]}); width: 9px; height: 9px; }}

QPlainTextEdit {{
    background: {t.log}; color: #E5E7EB; border-radius: 8px; padding: 6px;
    font-family: Consolas, "Microsoft JhengHei UI", monospace; font-size: 9pt;
}}
QPlainTextEdit#terms {{
    background: {t.surface}; color: {t.text}; border: 1px solid {t.border}; border-radius: 6px; padding: 4px 6px;
    font-family: "Segoe UI", "Microsoft JhengHei UI"; font-size: 10pt;
}}
QPlainTextEdit#terms:focus {{ border-color: {t.accent}; }}

QFrame#vocabularyPopup {{ background: {t.surface}; border: 1px solid {t.strong_border}; }}
QFrame#vocabularyPopup QListWidget {{ background: {t.surface}; border: none; outline: 0; padding: 0; }}
QFrame#vocabularyLine {{ background: {t.border}; border: none; }}
QPushButton#vocabularyNew {{ border: none; border-radius: 4px; text-align: left; padding: 7px 10px; color: {t.accent_text}; font-weight: 600; }}
QPushButton#vocabularyNew:hover {{ background: {t.row_hover}; }}
QFrame#updateBar {{ background: {t.info_bg}; border: 1px solid {t.info_border}; border-radius: 8px; }}
QPushButton#updateAction {{ background: {t.accent}; color: white; border: none; font-weight: 600; }}
QPushButton#updateAction:hover {{ background: {t.accent_dark}; }}
QPushButton#updateAction:disabled {{ background: {t.accent_soft}; color: white; }}
QStatusBar {{ background: {t.surface}; border-top: 1px solid {t.border}; }}
QStatusBar QLabel {{ color: {t.muted}; padding: 0 10px; }}
QStatusBar::item {{ border: none; }}
QScrollArea {{ border: none; background: transparent; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}
QToolTip {{ background: {t.surface}; color: {t.text}; border: 1px solid {t.border}; padding: 4px 6px; }}
"""


def _palette(t: Theme) -> QPalette:
    """For what the style sheet doesn't reach: message boxes, menus, scroll bars."""
    palette = QPalette()
    for role, color in ((QPalette.Window, t.window), (QPalette.Base, t.surface), (QPalette.AlternateBase, t.alternate),
                        (QPalette.Text, t.text), (QPalette.WindowText, t.text), (QPalette.ButtonText, t.text),
                        (QPalette.Button, t.surface), (QPalette.Highlight, t.accent),
                        (QPalette.HighlightedText, "#FFFFFF"), (QPalette.ToolTipBase, t.surface),
                        (QPalette.ToolTipText, t.text), (QPalette.Link, t.accent_text),
                        (QPalette.LinkVisited, t.accent_text), (QPalette.PlaceholderText, t.disabled),
                        (QPalette.Mid, t.border), (QPalette.Dark, t.strong_border), (QPalette.Light, t.hover)):
        palette.setColor(role, QColor(color))
    for role in (QPalette.Text, QPalette.WindowText, QPalette.ButtonText):
        palette.setColor(QPalette.Disabled, role, QColor(t.disabled))
    return palette


_setting = "system"  # the Settings.theme that apply() got last
_applying = False
_following = False   # connected to Windows' color scheme changes


def apply(app: QApplication, setting: str = "system") -> Theme:
    """Gives the app the theme Settings.theme names. With "system" it also follows Windows when
    the user switches between light and dark there."""
    global current, _setting, _applying, _following
    _setting, _applying = setting, True
    try:
        hints = app.styleHints()
        try:  # Qt 6.8 and later: the title bars follow too
            if setting == "system":
                hints.unsetColorScheme()
            else:
                hints.setColorScheme(Qt.ColorScheme.Dark if setting == "dark" else Qt.ColorScheme.Light)
        except AttributeError:
            pass
        if not _following:
            hints.colorSchemeChanged.connect(lambda scheme: _follow(app, scheme))
            _following = True
        current = resolve(setting, hints.colorScheme())
        app.setStyle("Fusion")
        app.setPalette(_palette(current))
        font = QFont()
        font.setFamilies(["Segoe UI", "Microsoft JhengHei UI", "Microsoft JhengHei"])
        font.setPointSize(10)
        app.setFont(font)
        app.setStyleSheet(style_sheet(current, _draw_assets(paths.user_data_dir() / "ui" / current.name, current)))
    finally:
        _applying = False
    return current


def _follow(app: QApplication, scheme: Qt.ColorScheme) -> None:
    if not _applying and _setting == "system" and resolve("system", scheme) is not current:
        apply(app, "system")


def draw_icon(size: int) -> QPixmap:
    """Rounded blue tile with a sound wave and a speech bubble."""
    pix = QPixmap(size, size)
    pix.fill(Qt.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.Antialiasing)
    s = size / 64.0
    grad = QLinearGradient(0, 0, size, size)
    grad.setColorAt(0, QColor("#3B82F6"))
    grad.setColorAt(1, QColor("#1E40AF"))
    p.setPen(Qt.NoPen)
    p.setBrush(grad)
    p.drawRoundedRect(QRectF(2 * s, 2 * s, 60 * s, 60 * s), 14 * s, 14 * s)
    p.setPen(QPen(QColor("white"), 4.2 * s, Qt.SolidLine, Qt.RoundCap))
    for i, h in enumerate((10, 20, 30, 20, 12)):
        x = (14 + i * 7) * s
        p.drawLine(QPointF(x, (32 - h / 2) * s), QPointF(x, (32 + h / 2) * s))
    p.setPen(Qt.NoPen)
    p.setBrush(QColor("#FDE68A"))
    bubble = QPainterPath()
    bubble.addRoundedRect(QRectF(40 * s, 38 * s, 18 * s, 13 * s), 4 * s, 4 * s)
    p.drawPath(bubble)
    p.setBrush(QColor("#1E40AF"))
    for dx in (45, 51):
        p.drawEllipse(QPointF(dx * s, 44.5 * s), 1.6 * s, 1.6 * s)
    p.end()
    return pix


def app_icon() -> QIcon:
    icon = QIcon()
    for size in (16, 24, 32, 48, 64, 128, 256):
        icon.addPixmap(draw_icon(size))
    return icon
