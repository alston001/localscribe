"""Renders the app icon (drawn in code) to packaging/localscribe.ico."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PIL import Image  # noqa: E402
from PySide6.QtGui import QGuiApplication  # noqa: E402

from localscribe.ui.style import draw_icon  # noqa: E402

app = QGuiApplication(sys.argv)
png = ROOT / "packaging" / "icon_256.png"
draw_icon(256).save(str(png))
Image.open(png).save(ROOT / "packaging" / "localscribe.ico",
                     sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
png.unlink()
print("wrote packaging/localscribe.ico")
