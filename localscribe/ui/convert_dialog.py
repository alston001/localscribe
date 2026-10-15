"""Converter dialog: turn recordings (e.g. iPhone .qta voice memos) into M4A / MP3 / WAV / FLAC."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QAbstractItemView, QButtonGroup, QCheckBox, QComboBox, QDialog, QFileDialog,
                               QFormLayout, QHBoxLayout, QLabel, QLineEdit, QListView, QListWidget,
                               QListWidgetItem, QProgressBar, QPushButton, QRadioButton, QStyle, QVBoxLayout)

from .. import paths
from ..core.convert import CONVERT_FORMATS
from ..core.media import MEDIA_EXTENSIONS
from ..i18n import tr
from .settings_dialog import _fill
from .threads import ConvertThread

_PATH = Qt.UserRole
_OUTPUT = Qt.UserRole + 1


class ConvertDialog(QDialog):
    def __init__(self, settings, files: list[Path], parent=None):
        super().__init__(parent)
        self.settings = settings
        self.worker: ConvertThread | None = None
        self.outputs: list[str] = []
        self.counts = {"ok": 0, "bad": 0, "warn": 0}
        self.setWindowTitle(tr("convert_title"))
        self.setMinimumSize(640, 520)
        self.setAcceptDrops(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.addWidget(QLabel(tr("convert_intro"), objectName="hint", wordWrap=True))

        self.list = QListWidget()
        self.list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        # Long rows (a warning, a long file name) wrap to the list's width instead of scrolling.
        self.list.setWordWrap(True)
        self.list.setResizeMode(QListView.Adjust)
        self.list.itemDoubleClicked.connect(self._reveal)
        layout.addWidget(self.list, 1)
        self.lbl_empty = QLabel(tr("convert_drop_hint"), objectName="hint", alignment=Qt.AlignCenter)
        layout.addWidget(self.lbl_empty)
        row = QHBoxLayout()
        self.btn_add = QPushButton(tr("add_files"), clicked=self._add_dialog)
        self.btn_remove = QPushButton(tr("remove"), clicked=self._remove_selected)
        row.addWidget(self.btn_add)
        row.addWidget(self.btn_remove)
        row.addStretch(1)
        layout.addLayout(row)

        form = QFormLayout()
        self.cmb_format = QComboBox()
        _fill(self.cmb_format, [(f, tr(f"cfmt_{f}")) for f in CONVERT_FORMATS], settings.convert_format)
        form.addRow(tr("convert_format"), self.cmb_format)
        self.rad_same = QRadioButton(tr("save_same"))
        self.rad_custom = QRadioButton(tr("save_custom"))
        group = QButtonGroup(self)
        group.addButton(self.rad_same)
        group.addButton(self.rad_custom)
        (self.rad_same if settings.convert_save_mode == "same" else self.rad_custom).setChecked(True)
        folder_row = QHBoxLayout()
        self.txt_dir = QLineEdit(settings.convert_save_dir, readOnly=True)
        self.btn_choose = QPushButton(tr("choose"), clicked=self._choose_dir)
        folder_row.addWidget(self.txt_dir, 1)
        folder_row.addWidget(self.btn_choose)
        save_box = QVBoxLayout()
        save_box.addWidget(self.rad_same)
        save_box.addWidget(self.rad_custom)
        save_box.addLayout(folder_row)
        form.addRow(tr("save_to"), save_box)
        self.chk_queue = QCheckBox(tr("convert_add_queue"))
        self.chk_queue.setChecked(settings.convert_add_queue)
        form.addRow("", self.chk_queue)
        layout.addLayout(form)
        self.rad_same.toggled.connect(self._update_state)

        self.progress = QProgressBar(maximum=1000, textVisible=False)
        self.lbl_status = QLabel(objectName="hint")
        layout.addWidget(self.progress)
        layout.addWidget(self.lbl_status)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.btn_start = QPushButton(tr("convert_start"), objectName="primary", clicked=self._start_or_cancel)
        self.btn_close = QPushButton(tr("close"), clicked=self.close)
        buttons.addWidget(self.btn_start)
        buttons.addWidget(self.btn_close)
        layout.addLayout(buttons)

        self.add_files(files)
        self._update_state()

    # ---- file list -------------------------------------------------------
    def add_files(self, files: list[Path]) -> None:
        present = {self.list.item(i).data(_PATH) for i in range(self.list.count())}
        for path in files:
            if path.is_file() and str(path) not in present:
                item = QListWidgetItem(path.name)
                item.setData(_PATH, str(path))
                item.setToolTip(str(path))
                self.list.addItem(item)
                present.add(str(path))
        self._update_state()

    def _add_dialog(self) -> None:
        patterns = " ".join(f"*{ext}" for ext in sorted(MEDIA_EXTENSIONS))
        files, _ = QFileDialog.getOpenFileNames(
            self, tr("file_dialog_title"), "",
            f"{tr('file_filter_media')} ({patterns});;{tr('file_filter_all')} (*.*)")
        self.add_files([Path(f) for f in files])

    def _remove_selected(self) -> None:
        for item in self.list.selectedItems():
            self.list.takeItem(self.list.row(item))
        self._update_state()

    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasUrls() and self.worker is None:
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:
        paths = []
        for url in event.mimeData().urls():
            p = Path(url.toLocalFile())
            paths += sorted(x for x in p.rglob("*") if x.suffix.lower() in MEDIA_EXTENSIONS) if p.is_dir() else [p]
        self.add_files(paths)
        event.acceptProposedAction()

    def _choose_dir(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, tr("save_to"), self.txt_dir.text() or str(Path.home()))
        if folder:
            self.txt_dir.setText(str(Path(folder)))
            self._update_state()

    def _reveal(self, item: QListWidgetItem) -> None:
        target = item.data(_OUTPUT) or item.data(_PATH)
        subprocess.Popen([paths.explorer_exe(), "/select,", os.path.normpath(target)])

    # ---- running ---------------------------------------------------------
    def _update_state(self) -> None:
        running = self.worker is not None
        empty = self.list.count() == 0
        self.lbl_empty.setVisible(empty)
        for w in (self.btn_add, self.btn_remove, self.cmb_format, self.rad_same, self.rad_custom, self.chk_queue):
            w.setEnabled(not running)
        custom = self.rad_custom.isChecked()
        self.txt_dir.setEnabled(custom and not running)
        self.btn_choose.setEnabled(custom and not running)
        self.btn_start.setText(tr("cancel") if running else tr("convert_start"))
        self.btn_start.setEnabled(running or (not empty and (not custom or bool(self.txt_dir.text()))))

    def _start_or_cancel(self) -> None:
        if self.worker is not None:
            self.worker.cancel.set()
            self.btn_start.setEnabled(False)
            return
        s = self.settings
        s.convert_format = self.cmb_format.currentData()
        s.convert_save_mode = "custom" if self.rad_custom.isChecked() else "same"
        s.convert_save_dir = self.txt_dir.text()
        s.convert_add_queue = self.chk_queue.isChecked()
        items = []
        for i in range(self.list.count()):
            item = self.list.item(i)
            if not item.data(_OUTPUT):  # skip files already converted in this session
                item.setIcon(self.style().standardIcon(QStyle.SP_FileIcon))
                items.append((i, Path(item.data(_PATH))))
        if not items:
            return
        self.total_files = len(items)
        self.completed = 0
        self.counts = {"ok": 0, "bad": 0, "warn": 0}
        self.progress.setValue(0)
        folder = Path(s.convert_save_dir) if s.convert_save_mode == "custom" else None
        self.worker = ConvertThread(items, folder, s.convert_format, self)
        self.worker.file_started.connect(self._on_started)
        self.worker.file_progress.connect(self._on_progress)
        self.worker.file_done.connect(self._on_done)
        self.worker.file_failed.connect(self._on_failed)
        self.worker.file_stopped.connect(self._on_stopped)
        self.worker.finished.connect(self._on_finished)
        self.worker.start()
        self._update_state()

    def _on_started(self, row: int) -> None:
        item = self.list.item(row)
        item.setIcon(self.style().standardIcon(QStyle.SP_BrowserReload))
        self.lbl_status.setText(item.text())

    def _on_progress(self, row: int, fraction: float) -> None:
        self.progress.setValue(int((self.completed + fraction) / self.total_files * 1000))

    def _on_done(self, row: int, output: str, warnings: list) -> None:
        item = self.list.item(row)
        icon = QStyle.SP_MessageBoxWarning if warnings else QStyle.SP_DialogApplyButton
        item.setIcon(self.style().standardIcon(icon))
        item.setData(_OUTPUT, output)
        # Warnings go on lines of their own: after the file names they ran off the list's edge.
        item.setText("\n".join([f"{Path(item.data(_PATH)).name}  →  {Path(output).name}", *warnings]))
        item.setToolTip("\n".join([output, *warnings]))
        self.outputs.append(output)
        self.completed += 1
        self.counts["ok"] += 1
        self.counts["warn"] += bool(warnings)

    def _on_failed(self, row: int, message: str) -> None:
        item = self.list.item(row)
        item.setIcon(self.style().standardIcon(QStyle.SP_MessageBoxCritical))
        item.setToolTip(message)
        item.setText(f"{Path(item.data(_PATH)).name}  —  {message}")
        self.completed += 1
        self.counts["bad"] += 1

    def _on_stopped(self, row: int) -> None:
        item = self.list.item(row)
        item.setIcon(self.style().standardIcon(QStyle.SP_MediaStop))  # not the red ✕ used for failures
        item.setText(f"{Path(item.data(_PATH)).name}  —  {tr('st_stopped')}")

    def _on_finished(self) -> None:
        stopped = self.worker.cancel.is_set()
        self.worker = None
        self.progress.setValue(int(self.completed / max(self.total_files, 1) * 1000))
        summary = tr("convert_stopped" if stopped else "convert_done", ok=self.counts["ok"], bad=self.counts["bad"])
        if self.counts["warn"]:
            summary += " " + tr("convert_warn_note", n=self.counts["warn"])
        self.lbl_status.setText(summary)
        self._update_state()

    def _stop_worker(self) -> bool:
        """Cancels a running conversion. False while it is still running after the wait."""
        if self.worker is None:
            return True
        self.worker.cancel.set()
        if self.worker.wait(10000):
            return True
        self.lbl_status.setText(tr("still_stopping"))
        return False

    def reject(self) -> None:
        # Esc during a conversion works like Cancel: the dialog stays to show what stopped.
        # (QDialog.closeEvent also calls this, after _stop_worker has already waited.)
        if self.worker is not None and self.worker.isRunning():
            self._start_or_cancel()
            return
        super().reject()

    def closeEvent(self, event) -> None:
        if self._stop_worker():
            super().closeEvent(event)
        else:
            event.ignore()
