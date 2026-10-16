"""Look and feel: palette, style sheet, fonts and the app icon (all drawn; no image files)."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (QColor, QFont, QIcon, QLinearGradient, QPainter, QPainterPath, QPalette,
                           QPen, QPixmap)
from PySide6.QtWidgets import QApplication

from .. import paths

ACCENT = "#2563EB"
ACCENT_DARK = "#1D4ED8"
DANGER = "#DC2626"
BORDER = "#D1D5DB"
STRONG_BORDER = "#9CA3AF"
SURFACE = "#FFFFFF"
WINDOW = "#F3F4F6"
TEXT = "#111827"
MUTED = "#6B7280"
DISABLED = "#9CA3AF"

STATUS_COLORS = {"done": "#15803D", "failed": DANGER, "stopped": "#B45309", "running": ACCENT}


def _draw_assets(folder: Path) -> dict[str, str]:
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
        "down": save("down", 10, MUTED, [(1.5, 3.5), (5, 7), (8.5, 3.5)], 1.6),
        "up": save("up", 10, MUTED, [(1.5, 6.5), (5, 3), (8.5, 6.5)], 1.6),
    }


def style_sheet(a: dict[str, str]) -> str:
    return f"""
QMainWindow, QDialog {{ background: {WINDOW}; }}
QGroupBox {{
    background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 8px;
    margin-top: 18px; padding: 10px 10px 8px 10px; font-weight: 600;
}}
QGroupBox::title {{ subcontrol-origin: margin; subcontrol-position: top left; left: 10px; top: 3px; padding: 0 4px; color: {TEXT}; }}
QGroupBox QLabel, QGroupBox QCheckBox, QGroupBox QRadioButton {{ font-weight: normal; }}
QLabel:disabled, QCheckBox:disabled, QRadioButton:disabled {{ color: {DISABLED}; }}
QLabel#hint {{ color: {MUTED}; }}

QTableView {{
    background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 8px;
    gridline-color: transparent; selection-background-color: #DBEAFE; selection-color: {TEXT};
    alternate-background-color: #F9FAFB;
}}
QHeaderView::section {{
    background: {SURFACE}; border: none; border-bottom: 1px solid {BORDER};
    padding: 6px 8px; color: {MUTED}; font-weight: 600;
}}

QPushButton {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 6px; padding: 6px 14px; }}
QPushButton:hover {{ background: #F9FAFB; border-color: {STRONG_BORDER}; }}
QPushButton:checked {{ background: #DBEAFE; border-color: {ACCENT}; }}
QPushButton:disabled {{ color: {DISABLED}; background: #F9FAFB; }}
QPushButton#primary {{ background: {ACCENT}; color: white; border: none; font-weight: 600; font-size: 11pt; }}
QPushButton#primary:hover {{ background: {ACCENT_DARK}; }}
QPushButton#primary[running="true"] {{ background: {DANGER}; }}
QPushButton#primary:disabled {{ background: #93C5FD; color: white; }}

QCheckBox, QRadioButton {{ spacing: 8px; }}
QCheckBox::indicator {{ width: 16px; height: 16px; border: 1px solid {STRONG_BORDER}; border-radius: 4px; background: {SURFACE}; }}
QCheckBox::indicator:hover {{ border-color: {ACCENT}; }}
QCheckBox::indicator:checked {{ background: {ACCENT}; border-color: {ACCENT}; image: url({a["check"]}); }}
QCheckBox::indicator:disabled {{ background: {WINDOW}; border-color: {BORDER}; }}
QCheckBox::indicator:checked:disabled {{ background: #93C5FD; border-color: #93C5FD; }}
QRadioButton::indicator {{ width: 16px; height: 16px; border: 1px solid {STRONG_BORDER}; border-radius: 9px; background: {SURFACE}; }}
QRadioButton::indicator:hover {{ border-color: {ACCENT}; }}
QRadioButton::indicator:checked {{ width: 8px; height: 8px; border: 5px solid {ACCENT}; }}
QRadioButton::indicator:disabled {{ background: {WINDOW}; border-color: {BORDER}; }}
QRadioButton::indicator:checked:disabled {{ border-color: #93C5FD; }}

QComboBox, QSpinBox, QLineEdit {{
    background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 6px; padding: 4px 8px; min-height: 22px;
}}
QComboBox:hover, QSpinBox:hover, QLineEdit:hover {{ border-color: {STRONG_BORDER}; }}
QComboBox:focus, QSpinBox:focus, QLineEdit:focus {{ border-color: {ACCENT}; }}
QComboBox:disabled, QSpinBox:disabled, QLineEdit:disabled {{ color: {DISABLED}; background: #F9FAFB; }}
QLineEdit:read-only {{ background: #F9FAFB; color: {MUTED}; }}
QComboBox {{ padding-right: 26px; }}
QComboBox::drop-down {{ subcontrol-origin: padding; subcontrol-position: center right; width: 24px; border: none; }}
QComboBox::down-arrow {{ image: url({a["down"]}); width: 10px; height: 10px; }}
QComboBox QAbstractItemView {{
    background: {SURFACE}; border: 1px solid {BORDER}; outline: 0; padding: 4px;
    selection-background-color: #DBEAFE; selection-color: {TEXT};
}}
QSpinBox {{ padding-right: 22px; }}
QSpinBox::up-button {{ subcontrol-origin: border; subcontrol-position: top right; width: 20px; border: none; }}
QSpinBox::down-button {{ subcontrol-origin: border; subcontrol-position: bottom right; width: 20px; border: none; }}
QSpinBox::up-arrow {{ image: url({a["up"]}); width: 9px; height: 9px; }}
QSpinBox::down-arrow {{ image: url({a["down"]}); width: 9px; height: 9px; }}

QPlainTextEdit {{
    background: #111827; color: #E5E7EB; border-radius: 8px; padding: 6px;
    font-family: Consolas, "Microsoft JhengHei UI", monospace; font-size: 9pt;
}}
QPlainTextEdit#terms {{
    background: {SURFACE}; color: {TEXT}; border: 1px solid {BORDER}; border-radius: 6px; padding: 4px 6px;
    font-family: "Segoe UI", "Microsoft JhengHei UI"; font-size: 10pt;
}}
QPlainTextEdit#terms:focus {{ border-color: {ACCENT}; }}

QFrame#vocabularyPopup {{ background: {SURFACE}; border: 1px solid {STRONG_BORDER}; }}
QFrame#vocabularyPopup QListWidget {{ background: {SURFACE}; border: none; outline: 0; padding: 0; }}
QFrame#vocabularyLine {{ background: {BORDER}; border: none; }}
QPushButton#vocabularyNew {{ border: none; border-radius: 4px; text-align: left; padding: 7px 10px; color: {ACCENT}; font-weight: 600; }}
QPushButton#vocabularyNew:hover {{ background: {WINDOW}; }}
QStatusBar {{ background: {SURFACE}; border-top: 1px solid {BORDER}; }}
QStatusBar QLabel {{ color: {MUTED}; padding: 0 10px; }}
QStatusBar::item {{ border: none; }}
QScrollArea {{ border: none; background: transparent; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}
QToolTip {{ background: {SURFACE}; color: {TEXT}; border: 1px solid {BORDER}; padding: 4px 6px; }}
"""


def apply(app: QApplication) -> None:
    app.setStyle("Fusion")
    palette = QPalette()
    for role, color in ((QPalette.Window, WINDOW), (QPalette.Base, SURFACE), (QPalette.AlternateBase, "#F9FAFB"),
                        (QPalette.Text, TEXT), (QPalette.WindowText, TEXT), (QPalette.ButtonText, TEXT),
                        (QPalette.Button, SURFACE), (QPalette.Highlight, ACCENT),
                        (QPalette.HighlightedText, "#FFFFFF"), (QPalette.ToolTipBase, SURFACE),
                        (QPalette.ToolTipText, TEXT), (QPalette.Link, ACCENT), (QPalette.LinkVisited, ACCENT_DARK),
                        (QPalette.PlaceholderText, DISABLED)):
        palette.setColor(role, QColor(color))
    app.setPalette(palette)
    font = QFont()
    font.setFamilies(["Segoe UI", "Microsoft JhengHei UI", "Microsoft JhengHei"])
    font.setPointSize(10)
    app.setFont(font)
    app.setStyleSheet(style_sheet(_draw_assets(paths.user_data_dir() / "ui")))


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
