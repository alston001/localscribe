"""The proofreading window: read a transcript along with its recording, correct it and save it.

Opened from a finished file's menu, or with Proofread… on a _transcript.json. The edits go through
core.proofread; saving writes the transcript and the files that came out of its run again.
"""

from __future__ import annotations

import html
import logging
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QRect, QSize, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QFontMetrics, QKeySequence, QShortcut, QTextDocument
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QComboBox, QFileDialog, QHBoxLayout, QHeaderView,
                               QLabel, QListWidget, QListWidgetItem, QMainWindow, QMenu, QMessageBox, QPushButton,
                               QSplitter, QStyle, QStyledItemDelegate, QStyleOptionViewItem, QTableView,
                               QVBoxLayout, QWidget)

from .. import APP_NAME
from ..config import Settings
from ..core import proofread
from ..core.errors import UserError
from ..core.media import MEDIA_EXTENSIONS, load_audio, mmss
from ..core.playback import Player
from ..core.transcript import Transcript
from ..export.common import ExportOptions, clock, is_uncertain, marked_runs, segment_words
from ..i18n import current_language, tr
from . import style

log = logging.getLogger("localscribe")

TIME, SPEAKER, TEXT = range(3)
UNSURE_BACKGROUND = "#FEF08A"  # the yellow Word exports use for unsure words
_MARGIN = 4  # around a segment's text
# Roles as plain ints: Qt asks a long transcript's model hundreds of thousands of times while it
# lays the rows out, and comparing Qt's enum objects made that take seconds.
_DISPLAY, _EDIT, _TOOLTIP, _ALIGN = (int(r) for r in (Qt.DisplayRole, Qt.EditRole, Qt.ToolTipRole,
                                                       Qt.TextAlignmentRole))
_TOP_LEFT = int(Qt.AlignLeft | Qt.AlignTop)


class RecordingLoader(QThread):
    """Decodes the recording for playback without freezing the window (an hour takes seconds)."""

    loaded = Signal(object)
    failed = Signal(str)

    def __init__(self, path: Path, parent=None):
        super().__init__(parent)
        self.path = path

    def run(self) -> None:
        try:
            self.loaded.emit(load_audio(self.path))
        except UserError as exc:
            self.failed.emit(tr(exc.key, **exc.kwargs))
        except Exception as exc:
            log.warning("Could not decode %s for playback", self.path.name, exc_info=True)
            self.failed.emit(str(exc))


class SegmentModel(QAbstractTableModel):
    edited = Signal(object, str, str)  # the segment, its field ("text" or "speaker"), the old value

    def __init__(self, transcript: Transcript, parent=None):
        super().__init__(parent)
        self.t = transcript

    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self.t.segments)

    def columnCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else 3

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if orientation == Qt.Horizontal and role == Qt.DisplayRole:
            return tr(("pr_col_time", "pr_col_speaker", "pr_col_text")[section])
        return None

    def data(self, index: QModelIndex, role=_DISPLAY):
        role = int(role)
        if role not in (_DISPLAY, _EDIT, _TOOLTIP, _ALIGN) or not index.isValid():
            return None
        seg, col = self.t.segments[index.row()], index.column()
        if role == _DISPLAY or role == _EDIT:
            if col == TIME:
                return clock(seg.start)
            if col == SPEAKER:
                return self.t.speaker_name(seg.speaker) if role == _DISPLAY else seg.speaker
            return seg.text
        if role == _TOOLTIP:
            if col != TEXT:
                return None
            words = segment_words(seg)
            if seg.words and words is not seg.words:
                return tr("pr_edited_tip")
            unsure = [w.text.strip() for w in words if is_uncertain(w)]
            return tr("pr_unsure_tip", words=", ".join(unsure)) if unsure else None
        return _TOP_LEFT if col != TEXT else None

    def flags(self, index: QModelIndex):
        flags = super().flags(index)
        return flags | Qt.ItemIsEditable if index.column() in (SPEAKER, TEXT) else flags

    def setData(self, index: QModelIndex, value, role=Qt.EditRole) -> bool:
        if role != Qt.EditRole or not index.isValid():
            return False
        row, seg = index.row(), self.t.segments[index.row()]
        if index.column() == TEXT:
            field, old, changed = "text", seg.text, proofread.set_text(self.t, row, str(value))
        elif index.column() == SPEAKER:
            field, old, changed = "speaker", seg.speaker, proofread.set_speaker(self.t, row, str(value))
        else:
            return False
        if changed:
            self.row_changed(row)
            self.edited.emit(seg, field, old)
        return changed

    def row_changed(self, row: int) -> None:
        self.dataChanged.emit(self.index(row, 0), self.index(row, 2))

    def speakers_changed(self) -> None:
        """Names changed: the speaker column only, since laying out every row again takes a while."""
        if self.t.segments:
            self.dataChanged.emit(self.index(0, SPEAKER), self.index(len(self.t.segments) - 1, SPEAKER))


class SpeakerDelegate(QStyledItemDelegate):
    """Picks a segment's speaker from the transcript's speakers."""

    def __init__(self, transcript: Transcript, parent=None):
        super().__init__(parent)
        self.t = transcript

    def createEditor(self, parent, option, index):
        combo = QComboBox(parent)
        for sid, name in self.t.speakers.items():
            combo.addItem(name, sid)
        combo.activated.connect(lambda _: (self.commitData.emit(combo), self.closeEditor.emit(combo)))
        return combo

    def setEditorData(self, editor, index) -> None:
        editor.setCurrentIndex(max(editor.findData(index.data(Qt.EditRole)), 0))

    def setModelData(self, editor, model, index) -> None:
        model.setData(index, editor.currentData(), Qt.EditRole)


class TextDelegate(QStyledItemDelegate):
    """Wraps a segment's text and shows the words Whisper was unsure of in yellow. Rows get their
    height from the font's metrics, which wrap plain text the way the drawn document does: laying
    out a document for each of 3,000 rows took seconds whenever the column changed width."""

    def __init__(self, view: QTableView, transcript: Transcript):
        super().__init__(view)
        self.view = view
        self.t = transcript

    def _document(self, index: QModelIndex, option, width: int) -> QTextDocument:
        seg = self.t.segments[index.row()]
        parts = []
        for text, unsure in marked_runs(seg, ExportOptions(mark_uncertain=True)):
            text = html.escape(text)
            parts.append(f'<span style="background-color:{UNSURE_BACKGROUND}">{text}</span>' if unsure else text)
        doc = QTextDocument()
        doc.setDefaultFont(option.font)
        doc.setDocumentMargin(_MARGIN)
        doc.setHtml("".join(parts))
        doc.setTextWidth(max(width, 50))
        return doc

    def paint(self, painter, option, index) -> None:
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        doc = self._document(index, opt, opt.rect.width())
        opt.text = ""
        widget = opt.widget
        (widget.style() if widget else QApplication.style()).drawControl(QStyle.CE_ItemViewItem, opt, painter, widget)
        painter.save()
        painter.translate(opt.rect.topLeft())
        painter.setClipRect(opt.rect.translated(-opt.rect.topLeft()))
        doc.drawContents(painter)
        painter.restore()

    def sizeHint(self, option, index) -> QSize:
        width = self.view.columnWidth(TEXT)
        room = QRect(0, 0, max(width, 50) - 2 * _MARGIN, 1_000_000)
        text = QFontMetrics(option.font).boundingRect(room, Qt.TextWordWrap, self.t.segments[index.row()].text)
        return QSize(width, text.height() + 2 * _MARGIN + 2)


class SegmentTable(QTableView):
    """Space plays or pauses while no cell is being edited."""

    play_pause = Signal()

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key_Space and self.state() != QAbstractItemView.EditingState:
            self.play_pause.emit()
            return
        super().keyPressEvent(event)


class ProofreadWindow(QMainWindow):
    closed = Signal(object)  # the transcript's path

    def __init__(self, json_path: Path, settings: Settings, recording: Path | None = None, parent=None):
        super().__init__(parent)
        self.json_path = Path(json_path)
        self.settings = settings
        self.t = Transcript.load(self.json_path)  # UserError for an unreadable or newer file: the caller says so
        self.dirty = False
        self._undo: list[Callable[[], None]] = []  # each undoes one edit, the last one last
        self._saved_depth = 0  # len(self._undo) when the files last said what the window says
        self.player: Player | None = None
        self._loader: RecordingLoader | None = None
        self._resume_at: float | None = None  # where a pause stopped, while the same row is current
        self._following = False  # the row moves with the audio, not because the user picked one
        self.recording = proofread.find_recording(self.t, self.json_path, recording)
        self._build()
        self._fill_speakers()
        self._update_title()
        if self.recording is not None:
            self._load(self.recording)
        else:
            self.lbl_status.setText(tr("pr_no_recording", name=self.t.source_name))

    # ------------------------------------------------------------------ layout
    def _build(self) -> None:
        self.setWindowIcon(style.app_icon())
        self.resize(1100, 720)
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(12, 12, 12, 8)

        bar = QHBoxLayout()
        self.btn_play = QPushButton(tr("pr_play"), clicked=self.toggle_play, enabled=False)
        self.lbl_time = QLabel("0:00")
        self.btn_find = QPushButton(tr("pr_find_recording"), clicked=self.find_recording)
        self.btn_find.setVisible(self.recording is None)
        self.btn_undo = QPushButton(tr("pr_undo"), clicked=self.undo, enabled=False)
        self.btn_undo.setToolTip(QKeySequence(QKeySequence.Undo).toString(QKeySequence.NativeText))
        self.btn_save = QPushButton(tr("pr_save"), objectName="primary", clicked=self.save)
        bar.addWidget(self.btn_play)
        bar.addWidget(self.lbl_time)
        bar.addWidget(self.btn_find)
        bar.addStretch(1)
        bar.addWidget(self.btn_undo)
        bar.addWidget(self.btn_save)
        root.addLayout(bar)

        self.model = SegmentModel(self.t, self)
        self.model.edited.connect(self._on_cell_edited)
        self.table = SegmentTable()
        self.table.setModel(self.model)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.DoubleClicked | QAbstractItemView.EditKeyPressed)
        self.table.setWordWrap(True)
        self.table.setItemDelegateForColumn(SPEAKER, SpeakerDelegate(self.t, self.table))
        self.table.setItemDelegateForColumn(TEXT, TextDelegate(self.table, self.t))
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(TIME, QHeaderView.Fixed)  # sizing it to its contents would read every row
        header.setSectionResizeMode(SPEAKER, QHeaderView.Interactive)
        header.setSectionResizeMode(TEXT, QHeaderView.Stretch)
        self.table.setColumnWidth(TIME, self.table.fontMetrics().horizontalAdvance("00:00:00") + 24)
        self.table.setColumnWidth(SPEAKER, 150)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.table.doubleClicked.connect(self._on_double_click)
        self.table.play_pause.connect(self.toggle_play)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._row_menu)
        self.table.selectionModel().currentRowChanged.connect(self._on_row_changed)
        self._relayout = QTimer(self, singleShot=True, interval=150)  # once a column stops changing width
        self._relayout.timeout.connect(self.table.resizeRowsToContents)
        header.sectionResized.connect(lambda column, *_: column == TEXT and self._relayout.start())

        side = QWidget()
        side_layout = QVBoxLayout(side)
        side_layout.setContentsMargins(0, 0, 0, 0)
        side_layout.addWidget(QLabel(tr("pr_speakers")))
        self.speaker_list = QListWidget()
        self.speaker_list.itemChanged.connect(self._on_speaker_renamed)
        self.speaker_list.currentItemChanged.connect(lambda *_: self._update_speaker_buttons())
        side_layout.addWidget(self.speaker_list, 1)
        hint = QLabel(tr("pr_rename_hint"), objectName="hint", wordWrap=True)
        side_layout.addWidget(hint)
        buttons = QHBoxLayout()
        self.btn_merge = QPushButton(tr("pr_merge"), clicked=self._merge_menu)
        self.btn_new_speaker = QPushButton(tr("pr_new_speaker"), clicked=self.new_speaker)
        buttons.addWidget(self.btn_merge)
        buttons.addWidget(self.btn_new_speaker)
        side_layout.addLayout(buttons)

        split = QSplitter(Qt.Horizontal)
        split.addWidget(self.table)
        split.addWidget(side)
        split.setStretchFactor(0, 4)
        split.setStretchFactor(1, 1)
        split.setChildrenCollapsible(False)
        root.addWidget(split, 1)
        self.lbl_status = QLabel(objectName="hint")
        self.statusBar().addWidget(self.lbl_status, 1)

        QShortcut(QKeySequence.Save, self, activated=self.save)
        QShortcut(QKeySequence.Undo, self, activated=self.undo)  # an open editor undoes its own typing first
        self.timer = QTimer(self, interval=100)
        self.timer.timeout.connect(self._tick)

    def _update_title(self) -> None:
        title = tr("pr_title", name=self.json_path.name) + f" — {APP_NAME}"
        self.setWindowTitle(("* " if self.dirty else "") + title)

    # -------------------------------------------------------------------- undo
    def _remember(self, undo: Callable[[], None]) -> None:
        self._undo.append(undo)
        if len(self._undo) > 500:
            del self._undo[0]
            self._saved_depth -= 1  # below 0 the saved state can't come back by undoing
        self._update_dirty()

    def _update_dirty(self) -> None:
        self.dirty = len(self._undo) != self._saved_depth
        self.btn_undo.setEnabled(bool(self._undo))
        self._update_title()

    def undo(self) -> None:
        if self._undo:
            self._undo.pop()()
            self._update_dirty()

    def _row_of(self, seg) -> int | None:
        return next((i for i, s in enumerate(self.t.segments) if s is seg), None)  # by identity: equal ones may repeat

    def _on_cell_edited(self, seg, field: str, old: str) -> None:
        def undo():
            setattr(seg, field, old)
            row = self._row_of(seg)
            if row is not None:
                self.model.row_changed(row)
            if field == "speaker":
                QTimer.singleShot(0, self._fill_speakers)
        self._remember(undo)
        if field == "speaker":
            QTimer.singleShot(0, self._fill_speakers)  # talk times

    # ---------------------------------------------------------------- speakers
    def _fill_speakers(self) -> None:
        times = proofread.talk_time(self.t)
        current = self._current_speaker()
        self.speaker_list.blockSignals(True)
        self.speaker_list.clear()
        for sid, name in self.t.speakers.items():
            item = QListWidgetItem(name)
            item.setData(Qt.UserRole, sid)
            item.setFlags(item.flags() | Qt.ItemIsEditable)
            item.setToolTip(tr("pr_talk_time", time=mmss(times.get(sid, 0.0))))
            self.speaker_list.addItem(item)
            if sid == current:
                self.speaker_list.setCurrentItem(item)
        self.speaker_list.blockSignals(False)
        self._update_speaker_buttons()

    def _current_speaker(self) -> str | None:
        item = self.speaker_list.currentItem()
        return item.data(Qt.UserRole) if item is not None else None

    def _update_speaker_buttons(self) -> None:
        self.btn_merge.setEnabled(self._current_speaker() is not None and len(self.t.speakers) > 1)

    def _on_speaker_renamed(self, item: QListWidgetItem) -> None:
        if not self.rename_speaker(item.data(Qt.UserRole), item.text()):
            QTimer.singleShot(0, self._fill_speakers)  # an empty name: show the old one again

    def rename_speaker(self, speaker_id: str, name: str) -> bool:
        old = self.t.speakers.get(speaker_id)
        if not proofread.rename_speaker(self.t, speaker_id, name):
            return False
        self._remember(lambda: (self.t.speakers.__setitem__(speaker_id, old), self._speakers_changed()))
        self._speakers_changed()
        return True

    def _merge_menu(self) -> None:
        source = self._current_speaker()
        if source is None:
            return
        menu = QMenu(self)
        for sid, name in self.t.speakers.items():
            if sid != source:
                menu.addAction(name, lambda target=sid: self._confirm_merge(source, target))
        menu.exec(self.btn_merge.mapToGlobal(self.btn_merge.rect().bottomLeft()))

    def _confirm_merge(self, source: str, target: str) -> None:
        question = tr("pr_merge_confirm", source=self.t.speaker_name(source), target=self.t.speaker_name(target))
        if QMessageBox.question(self, APP_NAME, question) == QMessageBox.Yes:
            self.merge_speaker(source, target)

    def merge_speaker(self, source: str, target: str) -> int:
        before = list(self.t.speakers.items())
        segments = [seg for seg in self.t.segments if seg.speaker == source]
        moved = proofread.merge_speakers(self.t, source, target)
        if source in self.t.speakers:
            return 0  # nothing happened

        def undo():
            self.t.speakers.clear()
            self.t.speakers.update(before)  # in the order they had
            for seg in segments:
                seg.speaker = source
            self._speakers_changed()
        self._remember(undo)
        self._speakers_changed()
        return moved

    def new_speaker(self) -> str:
        sid = proofread.add_speaker(self.t, f"{self.settings.speaker_label or 'Speaker'} {len(self.t.speakers) + 1}")
        self._remember(lambda: (self.t.speakers.pop(sid, None), self._speakers_changed()))
        self._fill_speakers()
        item = self.speaker_list.item(self.speaker_list.count() - 1)
        self.speaker_list.setCurrentItem(item)
        self.speaker_list.editItem(item)
        return sid

    def _speakers_changed(self) -> None:
        self.model.speakers_changed()
        # Later: a rename arrives from the list's own itemChanged, and refilling now would delete that item.
        QTimer.singleShot(0, self._fill_speakers)

    # ---------------------------------------------------------------- segments
    def _row_menu(self, pos) -> None:
        index = self.table.indexAt(pos)
        if not index.isValid():
            return
        menu = QMenu(self)
        menu.addAction(tr("pr_play_from_here"), lambda: self.play_from(index.row()))
        menu.addSeparator()
        menu.addAction(tr("pr_delete"), lambda: self._confirm_delete(index.row()))
        menu.exec(self.table.viewport().mapToGlobal(pos))

    def _confirm_delete(self, row: int) -> None:
        if QMessageBox.question(self, APP_NAME, tr("pr_delete_confirm")) == QMessageBox.Yes:
            self.delete_segment(row)

    def delete_segment(self, row: int) -> None:
        seg = self.t.segments[row]
        self.model.beginRemoveRows(QModelIndex(), row, row)
        proofread.delete_segment(self.t, row)
        self.model.endRemoveRows()

        def undo():  # the edits after this one are undone already, so the row is where it was
            self.model.beginInsertRows(QModelIndex(), row, row)
            self.t.segments.insert(row, seg)
            self.model.endInsertRows()
            self._fill_speakers()
        self._remember(undo)
        self._fill_speakers()

    def _on_double_click(self, index: QModelIndex) -> None:
        if index.column() == TIME:
            self.play_from(index.row())

    # ---------------------------------------------------------------- playback
    def _load(self, path: Path) -> None:
        self.recording = path
        self.btn_find.setVisible(False)
        self.lbl_status.setText(tr("pr_loading"))
        self._loader = RecordingLoader(path, self)
        self._loader.loaded.connect(self._on_loaded)
        self._loader.failed.connect(self._on_load_failed)
        self._loader.start()

    def _on_loaded(self, audio) -> None:
        self.player = Player(audio)
        self.btn_play.setEnabled(True)
        self.lbl_status.setText(tr("pr_ready", name=self.recording.name))

    def _on_load_failed(self, message: str) -> None:
        self.btn_find.setVisible(True)
        self.lbl_status.setText(tr("pr_load_failed", name=self.recording.name, detail=message))

    def find_recording(self) -> None:
        patterns = " ".join(f"*{ext}" for ext in sorted(MEDIA_EXTENSIONS))
        path, _ = QFileDialog.getOpenFileName(self, tr("pr_find_recording"), str(self.json_path.parent),
                                              f"{tr('pr_media_filter')} ({patterns})")
        if path:
            self._load(Path(path))

    def toggle_play(self) -> None:
        if self.player is None:
            return
        if self.player.playing:
            self._resume_at = self.player.position()
            self._stop()
            return
        row = max(self.table.currentIndex().row(), 0)
        if self._resume_at is not None:
            self._start(self._resume_at)
        elif self.t.segments:
            self.play_from(row)

    def play_from(self, row: int) -> None:
        if self.player is None or not 0 <= row < len(self.t.segments):
            return
        self._select(row)
        self._start(self.t.segments[row].start)

    def _start(self, seconds: float) -> None:
        try:
            self.player.play(seconds)
        except UserError as exc:
            QMessageBox.warning(self, APP_NAME, tr(exc.key, **exc.kwargs))
            return
        self._resume_at = None
        self.btn_play.setText(tr("pr_pause"))
        self.timer.start()

    def _stop(self) -> None:
        self.player.stop()
        self.timer.stop()
        self.btn_play.setText(tr("pr_play"))

    def _on_row_changed(self, *_) -> None:
        if not self._following:
            self._resume_at = None  # a row the user picked plays from its start

    def _select(self, row: int) -> None:
        self._following = True
        try:
            self.table.setCurrentIndex(self.model.index(row, TIME))
        finally:
            self._following = False
        self.table.scrollTo(self.model.index(row, TEXT))

    def _tick(self) -> None:
        if self.player is None:
            return
        position = self.player.position()
        self.lbl_time.setText(mmss(position))
        row = proofread.segment_at(self.t, position)
        editing = self.table.state() == QAbstractItemView.EditingState
        if row is not None and row != self.table.currentIndex().row() and not editing:
            self._select(row)
        if not self.player.playing:
            self._stop()

    # -------------------------------------------------------------------- save
    def export_options(self) -> ExportOptions:
        return self.settings.export_options(current_language())

    def save(self) -> bool:
        try:
            changed = proofread.changed_since(self.json_path)
        except OSError:
            changed = []  # the transcript is gone: saving writes it again
        if changed and QMessageBox.question(self, APP_NAME, tr("pr_overwrite", files="\n".join(
                p.name for p in changed))) != QMessageBox.Yes:
            return False
        try:
            written = proofread.save(self.t, self.json_path, self.export_options())
        except UserError as exc:
            QMessageBox.warning(self, APP_NAME, tr(exc.key, **exc.kwargs))
            return False
        self._saved_depth = len(self._undo)
        self._update_dirty()
        self.lbl_status.setText(tr("pr_saved", n=len(written)))
        return True

    def closeEvent(self, event) -> None:
        if self.dirty:
            box = QMessageBox(QMessageBox.Question, APP_NAME, tr("pr_unsaved", name=self.json_path.name),
                              QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel, self)
            box.exec()
            answer = box.standardButton(box.clickedButton())  # Esc and the title bar's X give Cancel
            if answer == QMessageBox.Cancel or (answer == QMessageBox.Save and not self.save()):
                event.ignore()
                return
        if self.player is not None:
            self.player.stop()
        self.timer.stop()
        if self._loader is not None and not self._loader.wait(15000):  # a running QThread must not be destroyed
            event.ignore()
            return
        self.closed.emit(self.json_path)
        super().closeEvent(event)
