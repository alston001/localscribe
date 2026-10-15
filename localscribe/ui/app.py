"""Starts the desktop app."""

from __future__ import annotations

import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from ..core import device as dev

dev.prepare_environment()  # before any torch / pyannote import

from PySide6.QtCore import QObject, Signal  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from .. import APP_NAME, __version__, i18n, paths  # noqa: E402
from ..config import Settings  # noqa: E402
from . import style  # noqa: E402

log = logging.getLogger("localscribe")


class _LogBridge(QObject):
    line = Signal(str)


class _QtHandler(logging.Handler):
    """Forwards log records to the window's log panel from any thread."""

    def __init__(self, bridge: _LogBridge):
        super().__init__(logging.INFO)
        self.bridge = bridge
        self.setFormatter(logging.Formatter("%(asctime)s  %(message)s", "%H:%M:%S"))

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.bridge.line.emit(self.format(record).splitlines()[0])
        except Exception:
            pass


def _setup_logging(bridge: _LogBridge) -> None:
    log.setLevel(logging.INFO)
    file_handler = RotatingFileHandler(paths.log_path(), maxBytes=2_000_000, backupCount=2, encoding="utf-8")
    file_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    log.addHandler(file_handler)
    log.addHandler(_QtHandler(bridge))
    log.info("%s %s starting", APP_NAME, __version__)


def _redirect_missing_streams() -> None:
    # A windowed build has no console; libraries that write to stderr would crash.
    if sys.stdout is None or sys.stderr is None:
        sink = open(paths.user_data_dir() / "console.log", "a", encoding="utf-8", buffering=1)
        sys.stdout = sys.stdout or sink
        sys.stderr = sys.stderr or sink


def _excepthook(kind, value, tb) -> None:
    log.error("Unhandled error", exc_info=(kind, value, tb))
    if QApplication.instance() is not None:
        QMessageBox.critical(None, APP_NAME, i18n.tr("err_unexpected", detail=f"{kind.__name__}: {value}"))


def main() -> int:
    _redirect_missing_streams()
    if len(sys.argv) > 1 and sys.argv[1] == "--cli":  # command line inside the packaged app
        from ..cli import main as cli_main

        return cli_main(sys.argv[2:])
    if sys.platform == "win32":
        try:  # own taskbar button and icon instead of python.exe's
            import ctypes

            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(f"{APP_NAME}.App")
        except Exception:
            pass
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(__version__)
    app.setWindowIcon(style.app_icon())
    style.apply(app)

    bridge = _LogBridge()
    _setup_logging(bridge)
    sys.excepthook = _excepthook

    settings = Settings.load()
    if not settings.ui_language:
        settings.ui_language = i18n.default_language()
    i18n.set_language(settings.ui_language)

    from .main_window import MainWindow

    window = MainWindow(settings)
    bridge.line.connect(window._append_log)
    window.show()
    window.add_paths([Path(a) for a in sys.argv[1:] if os.path.exists(a)])  # "Open with…"
    return app.exec()
