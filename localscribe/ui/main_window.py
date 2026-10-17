"""Main window: file queue on the left, conversion options on the right."""

from __future__ import annotations

import dataclasses
import logging
import os
import subprocess
import time
from pathlib import Path

from PySide6.QtCore import QByteArray, Qt, QTimer, QUrl
from PySide6.QtGui import QAction, QDesktopServices
from PySide6.QtWidgets import (QApplication, QButtonGroup, QCheckBox, QComboBox, QFileDialog, QFormLayout,
                               QGridLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QMainWindow, QMenu,
                               QMessageBox, QPlainTextEdit, QPushButton, QRadioButton, QScrollArea,
                               QSpinBox, QSplitter, QVBoxLayout, QWidget)

from .. import APP_NAME, __version__, i18n, paths
from ..config import LANGUAGE_CHOICES, PRESET_ORDER, PRESETS, Settings
from ..core import device as dev
from ..core import update
from ..core.errors import UserError
from ..core.media import MEDIA_EXTENSIONS, probe
from ..core.pipeline import Engine
from ..export import FORMATS
from ..i18n import tr
from ..vocabulary import (PROMPT_LIMIT, TokenCounter, Vocabulary, find_vocabulary, fit_terms, load_vocabularies,
                          prompt_terms, prompt_text, replace_vocabulary, save_vocabularies, token_counter)
from . import style
from .convert_dialog import ConvertDialog
from .jobs import JobTableModel, QueueView
from .settings_dialog import SettingsDialog, _fill
from .threads import DeviceProbe, DurationProbe, ProcessThread, Task, UpdateCheck
from .update_bar import UpdateBar
from .vocabulary_picker import VocabularyEditor, VocabularyPicker

log = logging.getLogger("localscribe")


class MainWindow(QMainWindow):
    def __init__(self, settings: Settings):
        super().__init__()
        self.settings = settings
        self.engine = Engine(settings.engine_settings(), log=log.info)
        self.device_info = None
        self.worker: ProcessThread | None = None
        self.run_template: Task | None = None  # options captured when Start was pressed
        self.run_results = {"ok": 0, "bad": 0}
        self._helpers: list = []  # keeps short-lived probe threads alive
        self._closing = False  # Quit was confirmed; the worker is stopping
        self._pending_installer: Path | None = None  # started once the window has closed
        self._update_check = None  # the check at start (threads.UpdateCheck)
        self.vocabularies: list[Vocabulary] = []
        self._reload_vocabularies()
        self.model = JobTableModel(self)
        self._build()
        self._load_settings()
        self.retranslate()
        self._restore_geometry()
        probe = DeviceProbe(self)
        probe.ready.connect(self._on_device_ready)
        self._keep(probe)
        probe.start()
        QTimer.singleShot(2000, self._startup_update_check)  # once the window is up

    # ------------------------------------------------------------------ layout
    def _build(self) -> None:
        self.setWindowIcon(style.app_icon())
        self.setAcceptDrops(True)
        self.setMinimumSize(920, 600)
        self.resize(1180, 760)
        central = QWidget()
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setContentsMargins(14, 14, 14, 10)
        root.setSpacing(14)

        left = QVBoxLayout()
        left.setSpacing(8)
        # Above the file list: a strip across the whole window would leave the options panel short.
        self.update_bar = UpdateBar()
        self.update_bar.restart_requested.connect(self._restart_to_update)
        left.addWidget(self.update_bar)
        bar = QHBoxLayout()
        self.btn_add = QPushButton(clicked=self.add_files_dialog)
        self.btn_remove = QPushButton(clicked=self.remove_selected)
        self.btn_clear = QPushButton(clicked=self.clear_finished)
        self.btn_convert = QPushButton(clicked=self.open_converter)
        self.btn_log = QPushButton(checkable=True)
        self.btn_log.toggled.connect(lambda on: self.log_view.setVisible(on))
        self.btn_settings = QPushButton(clicked=self.open_settings)
        for b in (self.btn_add, self.btn_remove, self.btn_clear):
            bar.addWidget(b)
        bar.addSpacing(12)
        bar.addWidget(self.btn_convert)
        bar.addStretch(1)
        bar.addWidget(self.btn_log)
        bar.addWidget(self.btn_settings)
        left.addLayout(bar)

        self.view = QueueView()
        self.view.setModel(self.model)
        self.view.customContextMenuRequested.connect(self._row_menu)
        self.view.doubleClicked.connect(self._row_activated)
        self.log_view = QPlainTextEdit(readOnly=True)
        self.log_view.setMaximumBlockCount(3000)
        self.log_view.setVisible(False)
        split = QSplitter(Qt.Vertical)
        split.addWidget(self.view)
        split.addWidget(self.log_view)
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 1)
        split.setChildrenCollapsible(False)
        left.addWidget(split, 1)
        root.addLayout(left, 1)

        right = QVBoxLayout()
        right.setSpacing(10)
        panel = QWidget()
        opts = QVBoxLayout(panel)
        opts.setContentsMargins(0, 0, 6, 0)
        opts.setSpacing(6)

        self.grp_options = QGroupBox()
        form = QFormLayout(self.grp_options)
        form.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        form.setVerticalSpacing(6)  # 8 left the default window 4 px short once the word bank row came in
        self.lbl_preset = QLabel()
        self.cmb_preset = QComboBox()
        self.cmb_preset.currentIndexChanged.connect(self._on_preset)
        form.addRow(self.lbl_preset, self.cmb_preset)
        self.lbl_preset_hint = QLabel(objectName="hint", wordWrap=True)
        form.addRow("", self.lbl_preset_hint)
        self.lbl_language = QLabel()
        self.cmb_language = QComboBox()
        self.cmb_language.currentIndexChanged.connect(self._on_option_changed)
        form.addRow(self.lbl_language, self.cmb_language)
        self.lbl_vocabulary = QLabel()
        self.cmb_vocabulary = VocabularyPicker()
        self.cmb_vocabulary.picked.connect(self._on_vocabulary_picked)
        self.cmb_vocabulary.new_requested.connect(self._new_vocabulary)
        self.cmb_vocabulary.edit_requested.connect(self._edit_vocabulary)
        self.cmb_vocabulary.delete_requested.connect(self._delete_vocabulary)
        self.cmb_vocabulary.opening.connect(self._on_vocabulary_menu_opening)
        form.addRow(self.lbl_vocabulary, self.cmb_vocabulary)

        self.lbl_speakers = QLabel()
        self.cmb_spk_mode = QComboBox()
        self.cmb_spk_mode.currentIndexChanged.connect(self._on_speaker_control)
        form.addRow(self.lbl_speakers, self.cmb_spk_mode)
        self.spk_numbers = QWidget()
        spk_row = QHBoxLayout(self.spk_numbers)
        spk_row.setContentsMargins(0, 0, 0, 0)
        self.spin_exact = QSpinBox(minimum=1, maximum=20)
        self.spin_min = QSpinBox(minimum=1, maximum=20)
        self.lbl_to = QLabel()
        self.spin_max = QSpinBox(minimum=1, maximum=20)
        for w in (self.spin_exact, self.spin_min, self.lbl_to, self.spin_max):
            spk_row.addWidget(w)
        spk_row.addStretch(1)
        for s in (self.spin_exact, self.spin_min, self.spin_max):
            s.setFixedWidth(72)
            s.valueChanged.connect(self._on_speaker_control)
        form.addRow("", self.spk_numbers)
        self.chk_normalize = QCheckBox()
        self.chk_denoise = QCheckBox()
        self.chk_normalize.toggled.connect(self._on_speaker_control)
        self.chk_denoise.toggled.connect(self._on_speaker_control)
        form.addRow("", self.chk_normalize)
        form.addRow("", self.chk_denoise)
        opts.addWidget(self.grp_options)

        self.grp_formats = QGroupBox()
        grid = QGridLayout(self.grp_formats)
        self.chk_formats: dict[str, QCheckBox] = {}
        for i, fmt in enumerate(FORMATS):
            box = QCheckBox()
            box.toggled.connect(self._on_option_changed)
            self.chk_formats[fmt] = box
            grid.addWidget(box, i // 2, i % 2)
        self.chk_timestamps = QCheckBox()
        self.chk_timestamps.toggled.connect(self._on_option_changed)
        self.chk_uncertain = QCheckBox()
        self.chk_uncertain.toggled.connect(self._on_option_changed)
        # One row for both: another row would give the default window a scroll bar.
        grid.addWidget(self.chk_timestamps, (len(FORMATS) + 1) // 2, 0)
        grid.addWidget(self.chk_uncertain, (len(FORMATS) + 1) // 2, 1)
        opts.addWidget(self.grp_formats)

        self.grp_save = QGroupBox()
        save = QVBoxLayout(self.grp_save)
        self.rad_same = QRadioButton()
        self.rad_custom = QRadioButton()
        group = QButtonGroup(self)
        group.addButton(self.rad_same)
        group.addButton(self.rad_custom)
        self.rad_same.toggled.connect(self._on_option_changed)
        save.addWidget(self.rad_same)
        save.addWidget(self.rad_custom)
        folder_row = QHBoxLayout()
        self.txt_dir = QLineEdit(readOnly=True)
        self.btn_choose_dir = QPushButton(clicked=self._choose_output_dir)
        folder_row.addWidget(self.txt_dir, 1)
        folder_row.addWidget(self.btn_choose_dir)
        save.addLayout(folder_row)
        opts.addWidget(self.grp_save)
        opts.addStretch(1)

        scroll = QScrollArea(widgetResizable=True)
        scroll.setWidget(panel)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        right.addWidget(scroll, 1)
        self.btn_start = QPushButton(objectName="primary", clicked=self.toggle_run)
        self.btn_start.setMinimumHeight(44)
        right.addWidget(self.btn_start)
        holder = QWidget()
        holder.setLayout(right)
        holder.setFixedWidth(372)  # room for "Mark unsure words" beside "Include timestamps"
        root.addWidget(holder)

        self.lbl_device = QLabel()
        self.lbl_model = QLabel()
        self.lbl_diarizer = QLabel()
        for lbl in (self.lbl_device, self.lbl_model, self.lbl_diarizer):
            self.statusBar().addPermanentWidget(lbl)  # stays visible next to temporary messages

    def _keep(self, thread) -> None:
        self._helpers.append(thread)
        thread.finished.connect(lambda: self._helpers.remove(thread) if thread in self._helpers else None)

    # -------------------------------------------------------------- settings
    def _load_settings(self) -> None:
        s = self.settings
        for w in (self.spin_exact, self.spin_min, self.spin_max, self.chk_normalize, self.chk_denoise):
            w.blockSignals(True)
        self.spin_exact.setValue(s.speakers_exact)
        self.spin_min.setValue(s.speakers_min)
        self.spin_max.setValue(s.speakers_max)
        self.chk_normalize.setChecked(s.normalize)
        self.chk_denoise.setChecked(s.denoise)
        for w in (self.spin_exact, self.spin_min, self.spin_max, self.chk_normalize, self.chk_denoise):
            w.blockSignals(False)
        for fmt, box in self.chk_formats.items():
            box.blockSignals(True)
            box.setChecked(fmt in s.formats)
            box.blockSignals(False)
        for box, value in ((self.chk_timestamps, s.timestamps), (self.chk_uncertain, s.mark_uncertain)):
            box.blockSignals(True)
            box.setChecked(value)
            box.blockSignals(False)
        self.rad_same.blockSignals(True)
        (self.rad_same if s.save_mode == "same" else self.rad_custom).setChecked(True)
        self.rad_same.blockSignals(False)
        self.txt_dir.setText(s.save_dir)

    def _save_settings(self) -> None:
        try:
            self.settings.save()
        except OSError:
            log.exception("Could not save settings")

    def retranslate(self) -> None:
        s = self.settings
        self.setWindowTitle(f"{APP_NAME} — {tr('app_subtitle')}")
        self.btn_add.setText(tr("add_files"))
        self.btn_remove.setText(tr("remove"))
        self.btn_clear.setText(tr("clear_finished"))
        self.btn_convert.setText(tr("convert"))
        self.btn_log.setText(tr("show_log"))
        self.btn_settings.setText(tr("settings"))
        self.grp_options.setTitle(tr("options"))
        self.lbl_preset.setText(tr("scenario"))
        _fill(self.cmb_preset, [(p, tr(f"preset_{p}")) for p in PRESET_ORDER], s.preset)
        self.lbl_language.setText(tr("language"))
        _fill(self.cmb_language, [(code, name or tr("lang_auto")) for code, name in LANGUAGE_CHOICES], s.language)
        self.lbl_vocabulary.setText(tr("vocabulary"))
        self.lbl_vocabulary.setToolTip(tr("vocabulary_tip"))
        self.cmb_vocabulary.setToolTip(tr("vocabulary_tip"))
        self.cmb_vocabulary.set_vocabularies(self.vocabularies, s.vocabulary)
        self.lbl_speakers.setText(tr("speakers"))
        _fill(self.cmb_spk_mode, [(m, tr(f"spk_{m}")) for m in ("auto", "exact", "range")], s.speaker_mode)
        self.lbl_to.setText(tr("spk_to"))
        self.chk_normalize.setText(tr("normalize"))
        self.chk_normalize.setToolTip(tr("normalize_tip"))
        self.chk_denoise.setText(tr("denoise"))
        self.chk_denoise.setToolTip(tr("denoise_tip"))
        self.grp_formats.setTitle(tr("formats"))
        for fmt, box in self.chk_formats.items():
            box.setText(tr(f"fmt_{fmt}"))
        self.chk_timestamps.setText(tr("timestamps"))
        self.chk_uncertain.setText(tr("mark_uncertain"))
        self.chk_uncertain.setToolTip(tr("mark_uncertain_tip"))
        self.grp_save.setTitle(tr("save_to"))
        self.rad_same.setText(tr("save_same"))
        self.rad_custom.setText(tr("save_custom"))
        self.btn_choose_dir.setText(tr("choose"))
        self.update_bar.retranslate()
        self.model.retranslate()
        self.view.viewport().update()
        self._update_speaker_widgets()
        self._update_run_button()
        self._update_status_bar()

    def _update_speaker_widgets(self) -> None:
        mode = self.cmb_spk_mode.currentData()
        self.spk_numbers.setVisible(mode in ("exact", "range"))
        self.spin_exact.setVisible(mode == "exact")
        for w in (self.spin_min, self.lbl_to, self.spin_max):
            w.setVisible(mode == "range")
        preset = self.cmb_preset.currentData()
        self.lbl_preset_hint.setText(tr(f"preset_{preset}_tip") if preset in PRESETS else "")
        self.lbl_preset_hint.setVisible(preset in PRESETS)
        custom = self.rad_custom.isChecked()
        self.txt_dir.setEnabled(custom)
        self.btn_choose_dir.setEnabled(custom)

    def _on_preset(self) -> None:
        name = self.cmb_preset.currentData()
        self.settings.preset = name
        if name in PRESETS:
            for key, value in PRESETS[name].items():
                setattr(self.settings, key, value)
            self._load_settings()
            self.cmb_spk_mode.blockSignals(True)
            self.cmb_spk_mode.setCurrentIndex(self.cmb_spk_mode.findData(self.settings.speaker_mode))
            self.cmb_spk_mode.blockSignals(False)
        self._update_speaker_widgets()
        self._save_settings()

    def _on_speaker_control(self) -> None:
        s = self.settings
        s.speaker_mode = self.cmb_spk_mode.currentData() or "auto"
        s.speakers_exact = self.spin_exact.value()
        s.speakers_min = self.spin_min.value()
        s.speakers_max = self.spin_max.value()
        s.normalize = self.chk_normalize.isChecked()
        s.denoise = self.chk_denoise.isChecked()
        if s.preset in PRESETS and not s.matches_preset(s.preset):
            s.preset = "custom"
            self.cmb_preset.blockSignals(True)
            self.cmb_preset.setCurrentIndex(self.cmb_preset.findData("custom"))
            self.cmb_preset.blockSignals(False)
        self._update_speaker_widgets()
        self._save_settings()

    def _on_option_changed(self) -> None:
        s = self.settings
        s.language = self.cmb_language.currentData() or "en"
        s.formats = [f for f, box in self.chk_formats.items() if box.isChecked()]
        s.timestamps = self.chk_timestamps.isChecked()
        s.mark_uncertain = self.chk_uncertain.isChecked()
        s.save_mode = "same" if self.rad_same.isChecked() else "custom"
        self._update_speaker_widgets()
        self._update_status_bar()
        self._save_settings()

    def _choose_output_dir(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, tr("save_to"), self.settings.save_dir or str(Path.home()))
        if folder:
            self.settings.save_dir = str(Path(folder))
            self.txt_dir.setText(self.settings.save_dir)
            self._save_settings()

    # ------------------------------------------------------------ word banks
    def _reload_vocabularies(self) -> None:
        """Reads the word banks again: another LocalScribe window may have changed them. Keeps
        this window's list while the file can't be read (e.g. locked by another program)."""
        try:
            self.vocabularies = load_vocabularies()
        except OSError:
            log.warning("Could not read the word banks", exc_info=True)

    def _on_vocabulary_menu_opening(self) -> None:
        self._reload_vocabularies()
        self.cmb_vocabulary.set_vocabularies(self.vocabularies, self.settings.vocabulary)

    def _on_vocabulary_picked(self, name: str) -> None:
        self.settings.vocabulary = name
        self._save_settings()

    def _new_vocabulary(self, name_hint: str = "") -> None:
        self._open_vocabulary_editor(None, name_hint)

    def _edit_vocabulary(self, name: str) -> None:
        vocabulary = find_vocabulary(self.vocabularies, name)
        if vocabulary is not None:
            self._open_vocabulary_editor(vocabulary)

    def _open_vocabulary_editor(self, original: Vocabulary | None, name_hint: str = "") -> None:
        taken = [v.name for v in self.vocabularies if v is not original]
        VocabularyEditor(original, taken, self._token_counter(), self.settings.hotwords, name_hint, self,
                         on_save=lambda result: self._save_vocabulary(original, result)).exec()

    def _save_vocabulary(self, original: Vocabulary | None, result: Vocabulary) -> str:
        """Adds a new word bank and picks it, or replaces an edited one; a renamed pick stays picked.
        Returns why it couldn't be saved, for the editor to show while it stays open; "" when saved."""
        error = self._change_vocabularies(original.name if original else "", result)
        if error:
            return error
        s = self.settings
        if original is None or find_vocabulary([original], s.vocabulary):
            s.vocabulary = result.name
            self._save_settings()
        self.cmb_vocabulary.set_vocabularies(self.vocabularies, s.vocabulary)
        return ""

    def _delete_vocabulary(self, name: str) -> None:
        vocabulary = find_vocabulary(self.vocabularies, name)
        if vocabulary is None or not self._confirm_delete(vocabulary.name):
            return
        error = self._change_vocabularies(vocabulary.name, None)
        if error:
            QMessageBox.warning(self, APP_NAME, error)
            return
        if find_vocabulary([vocabulary], self.settings.vocabulary):
            self.settings.vocabulary = ""
            self._save_settings()
        self.cmb_vocabulary.set_vocabularies(self.vocabularies, self.settings.vocabulary)

    def _change_vocabularies(self, old_name: str, new: Vocabulary | None) -> str:
        """Applies one change to the file as it is now, so word banks that another LocalScribe
        window saved in the meantime survive. Returns why it failed, or "" when saved."""
        try:
            current = load_vocabularies()
            clash = find_vocabulary(current, new.name) if new else None
            if clash is not None and not find_vocabulary([clash], old_name):  # made in another window
                return tr("vocab_name_taken", name=clash.name)
            changed = replace_vocabulary(current, old_name, new)
            save_vocabularies(changed)
        except OSError as exc:
            log.warning("Could not save the word banks", exc_info=True)
            return tr("vocab_save_failed", detail=str(exc))
        self.vocabularies = changed
        return ""

    def _confirm_delete(self, name: str) -> bool:
        box = QMessageBox(QMessageBox.Question, APP_NAME, tr("vocab_delete_confirm", name=name), parent=self)
        box.setTextFormat(Qt.PlainText)  # a name with "<" must not turn into HTML
        delete = box.addButton(tr("vocab_delete"), QMessageBox.DestructiveRole)
        box.setDefaultButton(box.addButton(tr("cancel"), QMessageBox.RejectRole))
        box.exec()
        return box.clickedButton() is delete

    def open_converter(self) -> None:
        dialog = ConvertDialog(self.settings, [j.path for j in self._selected_jobs()], self)
        dialog.exec()
        self.settings.convert_add_queue = dialog.chk_queue.isChecked()
        self._save_settings()
        if dialog.chk_queue.isChecked() and dialog.outputs:
            self.add_paths([Path(o) for o in dialog.outputs])

    def open_settings(self) -> None:
        bundled = [d for d in [paths.bundled_models_dir()] if d]
        dialog = SettingsDialog(self.settings, bundled, self, on_update_checked=self._on_manual_update_check)
        if dialog.exec() != SettingsDialog.Accepted:
            return
        chosen = dialog.settings
        # Written by update checks while Settings was open, after the dialog took its copy.
        chosen.update_checked_at, chosen.last_version = self.settings.update_checked_at, self.settings.last_version
        language_changed = chosen.ui_language != self.settings.ui_language
        self.settings = chosen
        self._save_settings()
        self.engine.update_settings(self.settings.engine_settings())
        if language_changed:
            i18n.set_language(self.settings.ui_language)
            self.retranslate()
        self._update_status_bar()

    # --------------------------------------------------------------- updates
    def _startup_update_check(self) -> None:
        s = self.settings
        try:
            update.clean_up()
        except OSError:
            log.warning("Could not remove old update downloads", exc_info=True)
        if s.last_version != __version__:
            if s.last_version:
                log.info("Updated from %s to %s", s.last_version, __version__)
                self.statusBar().showMessage(tr("upd_done", version=__version__), 15000)
            s.last_version = __version__
            self._save_settings()
        if not s.update_check or update.install_mode() == "source":  # a checkout updates through git
            return
        fetch = update.due(s.update_checked_at, time.time())
        check = UpdateCheck(fetch, self)
        check.done.connect(lambda release, error: self._on_update_checked(release, error, fetch))
        self._update_check = check  # a daemon thread: quitting never waits for it
        check.start()

    def _on_manual_update_check(self, release, error: str) -> None:
        """"Check now" in Settings; also when Settings closed before the answer came."""
        self._on_update_checked(release, error, True)

    def _on_update_checked(self, release, error: str, fetched: bool) -> None:
        if error:  # offline, or GitHub unreachable: try again at the next start
            log.info("Update check failed: %s", error)
            return
        if fetched:
            self.settings.update_checked_at = int(time.time())
            self._save_settings()
        if release is not None:
            log.info("LocalScribe %s is available (%s installer, %s)", release.version, release.kind,
                     update.size_text(release.size))
            self.update_bar.offer(release, update.install_mode())

    def _restart_to_update(self, installer: Path) -> None:
        """Quits, so the installer can replace LocalScribe's files; it starts LocalScribe again."""
        if self.worker is not None:  # the button waits for the transcription; just in case
            return
        self._pending_installer = installer
        self.close()

    # ---------------------------------------------------------------- status
    def _on_device_ready(self, info) -> None:
        self.device_info = info
        if info is not None:
            log.info("Hardware: %s | CPU: %s (%d threads)", info.summary() if info.cuda else "no CUDA GPU",
                     info.cpu_name, info.cpu_threads)
        self._update_status_bar()

    def _update_status_bar(self) -> None:
        if self.device_info is None:
            self.lbl_device.setText(tr("detecting"))
            self.lbl_model.setText("")
            self.lbl_diarizer.setText("")
            return
        info = self.device_info
        use_gpu = info.cuda and self.engine.device() == "cuda"
        self.lbl_device.setText(tr("sb_device", v=info.summary() if use_gpu else
                                   (tr("cpu_only") if not info.cuda else info.cpu_name)))
        self.lbl_model.setText(tr("sb_model", v=self.engine.whisper_name()))
        names = {"pyannote": "pyannote", "sherpa": "sherpa-onnx"}
        speakers_off = self.settings.speaker_count().single
        self.lbl_diarizer.setText(tr("sb_diarizer", v="—" if speakers_off else names[self.engine.diarizer_name()]))

    def _append_log(self, text: str) -> None:
        self.log_view.appendPlainText(text)

    # ------------------------------------------------------------------ files
    def add_files_dialog(self) -> None:
        patterns = " ".join(f"*{ext}" for ext in sorted(MEDIA_EXTENSIONS))
        files, _ = QFileDialog.getOpenFileNames(
            self, tr("file_dialog_title"), "",
            f"{tr('file_filter_media')} ({patterns});;{tr('file_filter_all')} (*.*)")
        self.add_paths([Path(f) for f in files])

    def add_paths(self, items: list[Path]) -> None:
        files, rejected = [], []
        for item in items:
            if item.is_dir():
                files += sorted(p for p in item.rglob("*") if p.suffix.lower() in MEDIA_EXTENSIONS)
            elif item.suffix.lower() in MEDIA_EXTENSIONS:
                files.append(item)
            elif item.is_file() and any(s.decodable for s in probe(item).audio):
                files.append(item)  # unusual extension, but ffmpeg can read the audio
            elif item.exists():
                rejected.append(item.name)
        pending = {j.path.resolve() for j in self.model.jobs if j.status in ("waiting", "queued", "running")}
        files = [f for f in dict.fromkeys(p.resolve() for p in files) if f not in pending]
        jobs = self.model.add(files)
        if jobs:
            probe = DurationProbe([(j.id, j.path) for j in jobs], self)
            probe.found.connect(self._on_duration)
            self._keep(probe)
            probe.start()
            if self.worker is not None and self.run_template is not None:
                for job in jobs:
                    self._enqueue(job)
        if rejected:
            QMessageBox.information(self, APP_NAME, tr("unsupported_files", names="\n".join(rejected[:15])))

    def _on_duration(self, job_id: int, seconds: float) -> None:
        _, job = self.model.find(job_id)
        if job is not None:
            job.duration = seconds
            self.model.refresh(job_id)

    def _selected_jobs(self):
        rows = sorted({i.row() for i in self.view.selectionModel().selectedRows()})
        return [self.model.jobs[r] for r in rows]

    def remove_selected(self) -> None:
        ids = {j.id for j in self._selected_jobs() if not j.active}
        self.model.remove(ids)

    def clear_finished(self) -> None:
        self.model.remove({j.id for j in self.model.jobs if j.status == "done"})

    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:
        self.add_paths([Path(u.toLocalFile()) for u in event.mimeData().urls() if u.isLocalFile()])
        event.acceptProposedAction()

    # -------------------------------------------------------------- running
    def toggle_run(self) -> None:
        if self.worker is not None:
            self.stop()
        else:
            self.start()

    def start(self, continuing: bool = False) -> None:
        s = self.settings
        pending = [j for j in self.model.jobs if j.status in ("waiting", "stopped")]
        if not pending:
            QMessageBox.information(self, APP_NAME, tr("no_files"))
            return
        if not s.formats:
            QMessageBox.warning(self, APP_NAME, tr("no_formats"))
            return
        if s.save_mode == "custom" and not s.save_dir:
            QMessageBox.warning(self, APP_NAME, tr("no_folder"))
            return
        self.engine.update_settings(s.engine_settings())
        terms = self._terms_for_run(ask=not continuing)
        if terms is None:
            return
        hotwords, vocabulary = terms
        keep = prompt_terms(find_vocabulary(self.vocabularies, vocabulary), s.hotwords)  # spelled as written
        self.run_template = Task(0, Path(), s.job_options(hotwords=hotwords, keep_terms=keep), list(s.formats),
                                 s.export_options(i18n.current_language()),
                                 Path(s.save_dir) if s.save_mode == "custom" else None, vocabulary)
        worker = ProcessThread(self.engine, self)
        worker.job_started.connect(self._on_job_started)
        worker.job_progress.connect(self._on_job_progress)
        worker.job_finished.connect(self._on_job_finished)
        worker.job_failed.connect(self._on_job_failed)
        worker.job_stopped.connect(self._on_job_stopped)
        worker.finished.connect(self._on_worker_done)
        self.worker = worker
        if not continuing:
            self.run_results = {"ok": 0, "bad": 0}
        for job in pending:
            self._enqueue(job)
        worker.start()
        self._set_running(True)

    def _enqueue(self, job) -> None:
        job.status, job.progress, job.stage, job.error, job.error_details = "queued", 0.0, "", "", ""
        self.worker.add(dataclasses.replace(self.run_template, job_id=job.id, path=job.path))
        self.model.refresh(job.id)

    def _terms_for_run(self, ask: bool) -> tuple[str, str] | None:
        """(hotwords for Whisper, word bank name). Terms past Whisper's limit are listed first
        instead of being cut off silently; None when the user goes back to shorten the list."""
        self._reload_vocabularies()
        vocabulary = find_vocabulary(self.vocabularies, self.settings.vocabulary)
        counter = self._token_counter()
        kept, dropped = fit_terms(prompt_terms(vocabulary, self.settings.hotwords), counter)
        if dropped and ask and not self._confirm_dropped_terms(dropped, counter.exact):
            return None
        if dropped and counter.exact:  # the count only: terms can be people's names
            log.info("Left out %d term(s) past Whisper's limit of %d tokens", len(dropped), PROMPT_LIMIT)
        elif dropped:  # an estimate can be off either way, so Whisper keeps what really fits
            kept += dropped
        return prompt_text(kept, self.settings.language), vocabulary.name if vocabulary else ""

    def _token_counter(self) -> TokenCounter:
        """Counts what the run will send, with the tokenizer of the Whisper model that will run
        once that is known."""
        if self.settings.whisper_model == "auto" and self.device_info is None:
            return TokenCounter(language=self.settings.language)  # "auto" waits for the GPU check
        return token_counter(self.engine.store, self.engine.whisper_name(), self.settings.language)

    def _confirm_dropped_terms(self, dropped: list[str], exact: bool) -> bool:
        shown = ", ".join(dropped[:40])
        if len(dropped) > 40:
            shown += " " + tr("vocab_dropped_more", n=len(dropped) - 40)
        intro = tr("vocab_dropped" if exact else "vocab_dropped_estimate", limit=PROMPT_LIMIT, n=len(dropped))
        box = QMessageBox(QMessageBox.Warning, APP_NAME, f"{intro}\n\n{shown}", parent=self)
        box.setTextFormat(Qt.PlainText)
        box.setInformativeText(tr("vocab_dropped_question"))
        start = box.addButton(tr("vocab_start_anyway"), QMessageBox.AcceptRole)
        box.setDefaultButton(box.addButton(tr("vocab_go_back"), QMessageBox.RejectRole))
        box.exec()
        return box.clickedButton() is start

    def stop(self) -> None:
        if self.worker is not None:
            self.worker.cancel.set()
            self.btn_start.setEnabled(False)
            self.btn_start.setText(tr("stopping"))

    def _set_running(self, running: bool) -> None:
        for w in (self.grp_options, self.grp_formats, self.grp_save, self.btn_settings):
            w.setEnabled(not running)
        self.update_bar.set_busy(running)
        self._update_run_button()

    def _update_run_button(self) -> None:
        running = self.worker is not None
        self.btn_start.setEnabled(True)
        self.btn_start.setText(tr("stop") if running else tr("start"))
        self.btn_start.setProperty("running", "true" if running else "false")
        self.btn_start.style().unpolish(self.btn_start)
        self.btn_start.style().polish(self.btn_start)

    def _on_job_started(self, job_id: int) -> None:
        _, job = self.model.find(job_id)
        if job:
            job.status, job.stage, job.progress = "running", "decode", 0.0
            self.model.refresh(job_id)
            log.info("Started %s", job.path.name)
        self._update_status_bar()

    def _on_job_progress(self, job_id: int, stage: str, overall: float, detail: str) -> None:
        _, job = self.model.find(job_id)
        if job:
            job.stage, job.progress, job.detail = stage, overall, detail
            self.model.refresh(job_id)

    def _on_job_finished(self, job_id: int, outputs: list, warnings: list) -> None:
        _, job = self.model.find(job_id)
        if job:
            job.status, job.progress, job.outputs, job.warnings = "done", 1.0, outputs, warnings
            self.model.refresh(job_id)
            log.info("Done: %s", job.path.name)
        self.run_results["ok"] += 1
        self._update_status_bar()

    def _on_job_failed(self, job_id: int, message: str, details: str) -> None:
        _, job = self.model.find(job_id)
        if job:
            job.status, job.error, job.error_details = "failed", message, details
            self.model.refresh(job_id)
            log.warning("Failed: %s: %s", job.path.name, message)
        self.run_results["bad"] += 1

    def _on_job_stopped(self, job_id: int) -> None:
        _, job = self.model.find(job_id)
        if job:
            job.status = "stopped" if job.status == "running" else "waiting"
            job.progress = 0.0 if job.status == "waiting" else job.progress
            self.model.refresh(job_id)

    def _on_worker_done(self) -> None:
        stopped = self.worker.cancel.is_set()
        self.worker = None
        self.run_template = None
        # Files added just as the last job finished were queued after the thread stopped looking.
        leftovers = [j for j in self.model.jobs if j.status == "queued"]
        for job in leftovers:
            job.status = "waiting"
            self.model.refresh(job.id)
        if leftovers and not stopped:
            self.start(continuing=True)
            return
        self._set_running(False)
        results = self.run_results
        if results["ok"] or results["bad"]:
            self.statusBar().showMessage(tr("all_done", ok=results["ok"], bad=results["bad"]), 15000)
            QApplication.alert(self)
        self._update_status_bar()

    # -------------------------------------------------------------- row menu
    def _row_activated(self, index) -> None:
        job = self.model.jobs[index.row()]
        if job.status == "done":
            self._open_transcript(job)
        elif job.status == "failed":
            self._show_error(job)

    def _row_menu(self, pos) -> None:
        index = self.view.indexAt(pos)
        if not index.isValid():
            return
        job = self.model.jobs[index.row()]
        menu = QMenu(self)
        if job.outputs:
            menu.addAction(tr("open_transcript"), lambda: self._open_transcript(job))
            menu.addAction(tr("open_folder"), lambda: self._open_folder(job))
        if job.status == "failed":
            menu.addAction(tr("show_error"), lambda: self._show_error(job))
        if job.status in ("done", "failed", "stopped") and self.worker is None:
            menu.addAction(tr("run_again"), lambda: self._reset(job))
        if not job.active:
            menu.addSeparator()
            menu.addAction(tr("remove"), lambda: self.model.remove({job.id}))
        menu.exec(self.view.viewport().mapToGlobal(pos))

    def _reset(self, job) -> None:
        job.status, job.progress, job.error, job.outputs, job.warnings = "waiting", 0.0, "", [], []
        self.model.refresh(job.id)

    def _open_transcript(self, job) -> None:
        documents = [p for p in job.outputs if not p.endswith(".json")] or job.outputs
        if documents:
            QDesktopServices.openUrl(QUrl.fromLocalFile(documents[0]))

    def _open_folder(self, job) -> None:
        target = job.outputs[0] if job.outputs else str(job.path)
        subprocess.Popen([paths.explorer_exe(), "/select,", os.path.normpath(target)])

    def _show_error(self, job) -> None:
        box = QMessageBox(QMessageBox.Warning, tr("error_title"), job.error, parent=self)
        if job.error_details:
            box.setDetailedText(job.error_details)
        box.exec()

    # ----------------------------------------------------------------- window
    def _restore_geometry(self) -> None:
        if self.settings.geometry:
            try:
                self.restoreGeometry(QByteArray.fromHex(self.settings.geometry.encode()))
            except Exception:
                pass

    def closeEvent(self, event) -> None:
        installer, self._pending_installer = self._pending_installer, None  # for this close only
        if self.worker is not None and not self._closing:
            answer = QMessageBox.question(self, APP_NAME, tr("confirm_quit"))
            if answer != QMessageBox.Yes:
                event.ignore()
                return
            self._closing = True
            self.worker.cancel.set()
        # Destroying a QThread that is still running crashes the app: wait, or stay open. An update
        # download is stopped last (it resumes next time), only once nothing else holds the close up.
        threads = ([self.worker] if self.worker is not None else []) + list(self._helpers)
        if not all(thread.wait(15000) for thread in threads) or not self.update_bar.stop():  # e.g. the probe importing torch
            QMessageBox.information(self, APP_NAME, tr("still_stopping"))
            event.ignore()
            return
        self.settings.geometry = bytes(self.saveGeometry().toHex()).decode()
        self._save_settings()
        if installer is not None:
            try:
                update.start_installer(installer)
            except UserError as exc:
                QMessageBox.warning(self, APP_NAME, tr(exc.key, **exc.kwargs))
                event.ignore()
                return
            log.info("Quitting so the installer can update LocalScribe")
        event.accept()
