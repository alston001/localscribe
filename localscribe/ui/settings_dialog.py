"""Settings dialog: interface language, transcription model, diarization engine, model folder."""

from __future__ import annotations

import copy
import os
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout,
                               QGroupBox, QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout,
                               QWidget)

from .. import i18n
from ..config import WHISPER_CHOICES, Settings
from ..core.models import PYANNOTE_PAGE, ModelStore
from ..i18n import tr
from .threads import PyannoteDownload

_TOKEN_PAGE = "https://huggingface.co/settings/tokens"


def _fill(combo: QComboBox, items: list[tuple[str, str]], current: str) -> None:
    combo.blockSignals(True)
    combo.clear()
    for data, text in items:
        combo.addItem(text, data)
    combo.setCurrentIndex(max(combo.findData(current), 0))
    combo.blockSignals(False)


class SettingsDialog(QDialog):
    def __init__(self, settings: Settings, extra_model_dirs: list[Path], parent=None):
        super().__init__(parent)
        self.settings = copy.deepcopy(settings)
        self.extra_model_dirs = extra_model_dirs
        self.download: PyannoteDownload | None = None
        self.setWindowTitle(tr("settings"))
        self.setMinimumWidth(560)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 8, 14, 12)
        layout.setSpacing(6)

        general = QGroupBox(tr("general"))
        form = QFormLayout(general)
        self.cmb_ui = QComboBox()
        _fill(self.cmb_ui, list(i18n.LANGUAGES.items()), self.settings.ui_language)
        form.addRow(tr("ui_language"), self.cmb_ui)
        self.txt_label = QLineEdit(self.settings.speaker_label)
        self.txt_label.setToolTip(tr("speaker_label_tip"))
        form.addRow(tr("speaker_label"), self.txt_label)
        self.chk_sub_speakers = QCheckBox(tr("subtitle_speakers"))
        self.chk_sub_speakers.setChecked(self.settings.subtitle_speakers)
        form.addRow("", self.chk_sub_speakers)
        layout.addWidget(general)

        asr = QGroupBox(tr("transcription"))
        form = QFormLayout(asr)
        self.cmb_model = QComboBox()
        _fill(self.cmb_model, [(m, tr(f"model_{m}")) for m in WHISPER_CHOICES], self.settings.whisper_model)
        form.addRow(tr("model"), self.cmb_model)
        self.cmb_device = QComboBox()
        _fill(self.cmb_device, [(d, tr(f"device_{d}")) for d in ("auto", "cuda", "cpu")], self.settings.device)
        form.addRow(tr("device"), self.cmb_device)
        self.chk_fast = QCheckBox(tr("fast_mode"))
        self.chk_fast.setToolTip(tr("fast_mode_tip"))
        self.chk_fast.setChecked(self.settings.fast_mode)
        fast_hint = QLabel(tr("fast_mode_tip"), objectName="hint", wordWrap=True)
        form.addRow("", self.chk_fast)
        form.addRow("", fast_hint)
        self.txt_hotwords = QLineEdit(self.settings.hotwords)
        self.txt_hotwords.setPlaceholderText(tr("hotwords_placeholder"))
        self.txt_hotwords.setToolTip(tr("hotwords_tip"))
        form.addRow(tr("hotwords"), self.txt_hotwords)
        layout.addWidget(asr)

        diar = QGroupBox(tr("diarization"))
        form = QFormLayout(diar)
        self.cmb_engine = QComboBox()
        _fill(self.cmb_engine, [(e, tr(f"engine_{e}")) for e in ("auto", "pyannote", "sherpa")],
              self.settings.diarizer)
        form.addRow(tr("engine"), self.cmb_engine)
        self.lbl_pyannote = QLabel()
        form.addRow("", self.lbl_pyannote)
        self.help_box = QWidget()
        help_layout = QVBoxLayout(self.help_box)
        help_layout.setContentsMargins(0, 0, 0, 0)
        help_layout.addWidget(QLabel(tr("pyannote_help"), objectName="hint", wordWrap=True))
        links = QLabel(f'<a href="{PYANNOTE_PAGE}">{tr("open_model_page")}</a> &nbsp;·&nbsp; '
                       f'<a href="{_TOKEN_PAGE}">{tr("create_token")}</a>')
        links.setOpenExternalLinks(True)
        links.setTextInteractionFlags(Qt.TextBrowserInteraction)
        help_layout.addWidget(links)
        token_row = QHBoxLayout()
        self.txt_token = QLineEdit()
        self.txt_token.setEchoMode(QLineEdit.Password)
        self.txt_token.setPlaceholderText("hf_…")
        self.btn_download = QPushButton(tr("download_pyannote"))
        self.btn_download.clicked.connect(self._download_pyannote)
        token_row.addWidget(self.txt_token, 1)
        token_row.addWidget(self.btn_download)
        help_layout.addLayout(token_row)
        self.lbl_download = QLabel(objectName="hint", wordWrap=True)
        help_layout.addWidget(self.lbl_download)
        form.addRow("", self.help_box)
        layout.addWidget(diar)

        folder = QGroupBox(tr("models_folder"))
        row = QHBoxLayout(folder)
        self.txt_models = QLineEdit(str(self.settings.models_path()))
        self.txt_models.setReadOnly(True)
        btn_choose = QPushButton(tr("choose"))
        btn_choose.clicked.connect(self._choose_models_dir)
        btn_open = QPushButton(tr("open"))
        btn_open.clicked.connect(self._open_models_dir)
        row.addWidget(self.txt_models, 1)
        row.addWidget(btn_choose)
        row.addWidget(btn_open)
        layout.addWidget(folder)

        layout.addWidget(QLabel(tr("settings_restart_note"), objectName="hint"))
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("OK" if i18n.current_language() == "en" else "確定")
        buttons.button(QDialogButtonBox.Cancel).setText("Cancel" if i18n.current_language() == "en" else "取消")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self._refresh_pyannote_status()

    def _store(self) -> ModelStore:
        return ModelStore(Path(self.txt_models.text()), self.extra_model_dirs)

    def _refresh_pyannote_status(self) -> None:
        installed = self._store().pyannote_path() is not None
        self.lbl_pyannote.setText(tr("pyannote_installed" if installed else "pyannote_missing"))
        self.lbl_pyannote.setStyleSheet(f"color: {'#15803D' if installed else '#B45309'}; font-weight: 600;")
        self.help_box.setVisible(not installed)

    def _download_pyannote(self) -> None:
        if self.download is not None:
            return
        self.btn_download.setEnabled(False)
        self.txt_token.setEnabled(False)
        self.lbl_download.setText(tr("downloading", v=""))
        self.download = PyannoteDownload(Path(self.txt_models.text()), self.txt_token.text(), self)
        self.download.progress.connect(self._on_download_progress)
        self.download.done.connect(self._on_download_done)
        self.download.start()

    def _on_download_progress(self, done, total) -> None:
        text = f"{done / 2**20:.1f} / {total / 2**20:.1f} MB" if total else f"{done / 2**20:.1f} MB"
        self.lbl_download.setText(tr("downloading", v=text))

    def _on_download_done(self, ok: bool, message: str) -> None:
        self.download = None
        self.txt_token.clear()  # never kept
        self.btn_download.setEnabled(True)
        self.txt_token.setEnabled(True)
        self.lbl_download.setText(message)
        self.lbl_download.setStyleSheet("" if ok else "color: #DC2626;")
        if ok:
            self._refresh_pyannote_status()

    def _choose_models_dir(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, tr("models_folder"), self.txt_models.text())
        if folder:
            self.txt_models.setText(str(Path(folder)))
            self._refresh_pyannote_status()

    def _open_models_dir(self) -> None:
        path = Path(self.txt_models.text())
        path.mkdir(parents=True, exist_ok=True)
        os.startfile(str(path))

    def reject(self) -> None:
        if self.download is not None:
            self.download.cancel.set()
            self.download.wait(5000)
        super().reject()

    def accept(self) -> None:
        if self.download is not None:
            return  # wait for the download to finish
        s = self.settings
        s.ui_language = self.cmb_ui.currentData()
        s.speaker_label = self.txt_label.text().strip() or "Speaker"
        s.subtitle_speakers = self.chk_sub_speakers.isChecked()
        s.whisper_model = self.cmb_model.currentData()
        s.device = self.cmb_device.currentData()
        s.fast_mode = self.chk_fast.isChecked()
        s.hotwords = self.txt_hotwords.text().strip()
        s.diarizer = self.cmb_engine.currentData()
        from .. import paths

        chosen = Path(self.txt_models.text())
        s.models_dir = "" if chosen == paths.default_models_dir() else str(chosen)
        super().accept()
