"""The strip above the file list that offers a new version, downloads it and restarts into it."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton

from ..core import update
from ..i18n import tr
from .threads import UpdateDownload

_ACTIONS = {"available": "upd_update", "manual": "upd_page", "ready": "upd_restart", "failed": "upd_retry"}


class UpdateBar(QFrame):
    restart_requested = Signal(object)  # the downloaded installer, a Path, checked just now

    def __init__(self, parent=None):
        super().__init__(parent, objectName="updateBar")
        self.release: update.Release | None = None
        self.mode = "installed"            # update.install_mode()
        self.installer: Path | None = None  # set once every file is downloaded
        self.worker: UpdateDownload | None = None
        self.restart_after = False          # the worker checks the files before a restart
        self.pending: tuple | None = None   # a newer (release, mode), found while a download ran
        self.stopping = False
        self.error = ""
        self.busy = False                   # a transcription runs: restarting would stop it
        self.progress_text = ""
        row = QHBoxLayout(self)
        row.setContentsMargins(12, 6, 6, 6)
        row.setSpacing(8)
        self.lbl_text = QLabel(wordWrap=True)
        self.btn_notes = QPushButton(clicked=self._open_page)
        self.btn_action = QPushButton(objectName="updateAction", clicked=self._on_action)
        self.btn_dismiss = QPushButton(clicked=self._on_dismiss)
        row.addWidget(self.lbl_text, 1)
        for button in (self.btn_notes, self.btn_action, self.btn_dismiss):
            row.addWidget(button)
        self.setVisible(False)

    def phase(self) -> str:
        if self.mode != "installed" or (self.release is not None and self.release.kind == "page"):
            return "manual"  # unzipped, run as administrator, from source, or an unknown latest.json
        if self.worker is not None:
            return "verifying" if self.restart_after else "downloading"
        if self.installer is not None:
            return "ready"
        return "failed" if self.error else "available"

    def offer(self, release: update.Release, mode: str) -> None:
        if self.worker is not None:  # a download is under way; a newer release takes over after it
            if update.parse_version(release.version) > update.parse_version(self.release.version):
                self.pending = (release, mode)
            return
        self.release, self.mode, self.error = release, mode, ""
        self.installer = update.downloaded(release) if mode == "installed" else None
        self.retranslate()
        self.setVisible(True)

    def set_busy(self, busy: bool) -> None:
        self.busy = busy
        self.retranslate()

    def stop(self) -> bool:
        """Stops a download, which resumes next time. False when it doesn't stop in time."""
        if self.worker is None:
            return True
        self.worker.cancel.set()
        return self.worker.wait(15000)

    def retranslate(self) -> None:
        if self.release is None:
            return
        phase, version = self.phase(), self.release.version
        if phase in ("downloading", "verifying"):
            key = "upd_stopping" if self.stopping else f"upd_{phase}"
            text = tr(key, version=version, progress=self.progress_text).rstrip()
        elif phase == "available":
            text = tr("upd_available", version=version, size=update.size_text(self.release.size))
        elif phase == "manual":
            text = tr("upd_available_manual", version=version)
        elif phase == "ready":
            text = tr("upd_ready", version=version)
        else:
            text = tr("upd_failed", detail=self.error)
        self.lbl_text.setText(text)
        self.btn_action.setVisible(phase in _ACTIONS)
        self.btn_action.setText(tr(_ACTIONS.get(phase, "upd_update")))
        waiting = phase == "ready" and self.busy
        self.btn_action.setEnabled(not waiting)
        self.btn_action.setToolTip(tr("upd_busy") if waiting else "")
        self.btn_notes.setText(tr("upd_whats_new"))
        self.btn_notes.setVisible(phase != "manual")  # there the action button opens the same page
        self.btn_dismiss.setText(tr("cancel") if self.worker is not None else tr("upd_later"))
        self.btn_dismiss.setEnabled(not self.stopping)

    def _open_page(self) -> None:
        QDesktopServices.openUrl(QUrl(self.release.page))

    def _on_action(self) -> None:
        phase = self.phase()
        if phase == "manual":
            self._open_page()
        elif phase in ("available", "failed", "ready"):
            # "ready": files kept since an earlier session are checked against their SHA-256 again
            # (and fetched anew if they don't match) right before LocalScribe quits for them.
            self.error, self.progress_text, self.stopping = "", "", False
            self.restart_after = phase == "ready"
            self.worker = UpdateDownload(self.release, self)
            self.worker.progress.connect(self._on_progress)
            self.worker.done.connect(self._on_done)
            self.worker.start()
            self.retranslate()

    def _on_dismiss(self) -> None:
        if self.worker is not None:
            self.stopping = True
            self.worker.cancel.set()
            self.retranslate()
        else:
            self.setVisible(False)  # until the next start

    def _on_progress(self, done, total) -> None:
        if total:
            self.progress_text = f"{done * 100 // total}%  ({update.size_text(done)} / {update.size_text(total)})"
            self.retranslate()

    def _on_done(self, installer, error: str) -> None:
        restart = self.restart_after and installer is not None and not self.busy
        self.worker, self.stopping, self.restart_after = None, False, False
        self.installer, self.error = installer, error
        if self.pending is not None:  # the newer release replaces the one that just finished
            release, mode = self.pending
            self.pending = None
            self.offer(release, mode)
            return
        self.retranslate()
        if restart:
            self.restart_requested.emit(installer)
