"""The proofreading window: read a transcript along with its recording, correct it and save it.

Opened from a finished file's menu, or with Proofread… on a _transcript.json. The edits go through
core.proofread; saving writes the transcript and the files that came out of its run again.
"""

from __future__ import annotations

import html
import itertools
import logging
from pathlib import Path
from typing import Callable

from PySide6.QtCore import (QAbstractTableModel, QEvent, QModelIndex, QPersistentModelIndex, QRect, QSize, Qt,
                            QThread, QTimer, Signal)
from PySide6.QtGui import QFontMetrics, QKeySequence, QPalette, QShortcut, QTextDocument
from PySide6.QtWidgets import (QAbstractItemDelegate, QAbstractItemView, QApplication, QCheckBox, QComboBox,
                               QFileDialog, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QListWidget, QListWidgetItem,
                               QMainWindow, QMenu, QMessageBox, QPushButton, QSplitter, QStyle, QStyledItemDelegate,
                               QStyleOptionViewItem, QTableView, QToolButton, QVBoxLayout, QWidget)

from .. import APP_NAME
from ..config import Settings
from ..core import proofread
from ..core.errors import UserError
from ..core.media import MEDIA_EXTENSIONS, load_audio, mmss
from ..core.playback import Player
from ..core.transcript import Segment, Transcript
from ..export.common import ExportOptions, clock, is_uncertain, marked_runs, segment_words
from ..i18n import current_language, tr
from . import style

log = logging.getLogger("localscribe")

TIME, SPEAKER, TEXT = range(3)
_MARGIN = 4  # around a segment's text
# Roles as plain ints: Qt asks a long transcript's model hundreds of thousands of times while it
# lays the rows out, and comparing Qt's enum objects made that take seconds.
_DISPLAY, _EDIT, _TOOLTIP, _ALIGN = (int(r) for r in (Qt.DisplayRole, Qt.EditRole, Qt.ToolTipRole,
                                                       Qt.TextAlignmentRole))
_TOP_LEFT = int(Qt.AlignLeft | Qt.AlignTop)


def unsure_colors(palette: QPalette) -> tuple[str, str]:
    """(background, text) for the words Whisper was unsure of: on a light background the yellow
    Word exports use, on a dark one (dark mode) a dark amber that the light text reads on at 6:1."""
    if palette.color(QPalette.Base).lightness() < 128:
        return "#854D0E", palette.color(QPalette.Text).name()
    return "#FEF08A", "#111827"


def highlight_colors(palette: QPalette) -> dict[str, tuple[str, str]]:
    """(background, text) for each kind of highlight(): unsure words as unsure_colors gives them, and
    Find's matches in green, apart from those and from the selected row's blue, the match Next or
    Previous went to darker. On a dark background the light text reads on them at 4.5:1 or more."""
    if palette.color(QPalette.Base).lightness() < 128:
        text = palette.color(QPalette.Text).name()
        return {"unsure": unsure_colors(palette), "match": ("#14532D", text), "current": ("#15803D", text)}
    return {"unsure": unsure_colors(palette), "match": ("#BBF7D0", "#111827"), "current": ("#4ADE80", "#111827")}


def highlight(runs: list[tuple[str, bool]], matches: list[tuple[int, int]],
              current: tuple[int, int] | None) -> list[tuple[str, str | None]]:
    """The text of marked_runs' `runs` in pieces of one kind each: "current" for the match Next or
    Previous went to, "match" for Find's other matches (start, end), "unsure" for unsure words
    outside them, and None for the rest."""
    text = "".join(run for run, _ in runs)
    kinds: list[str | None] = []
    for run, unsure in runs:
        kinds += ["unsure" if unsure else None] * len(run)
    for start, end in matches:
        kinds[start:end] = ["current" if (start, end) == current else "match"] * (end - start)
    pieces, start = [], 0
    for kind, same in itertools.groupby(kinds):
        end = start + len(list(same))
        pieces.append((text[start:end], kind))
        start = end
    return pieces


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
        self.rows_changed(row, row)

    def rows_changed(self, first: int, last: int) -> None:
        """One signal for them all: the table lays every row out again for each (0.2 s for 3,000)."""
        self.dataChanged.emit(self.index(first, 0), self.index(last, 2))

    def speakers_changed(self) -> None:
        """Names changed: the speaker column only, since laying out every row again takes a while."""
        if self.t.segments:
            self.dataChanged.emit(self.index(0, SPEAKER), self.index(len(self.t.segments) - 1, SPEAKER))


class EditingDelegate(QStyledItemDelegate):
    """Says when its editor opens, on which row, and when it closes: while the recording plays,
    the window keeps to the segment being edited."""

    editing_started = Signal(int)
    editing_ended = Signal()

    def destroyEditor(self, editor, index) -> None:
        self.editing_ended.emit()
        super().destroyEditor(editor, index)


class SpeakerDelegate(EditingDelegate):
    """Picks a segment's speaker from the transcript's speakers."""

    def __init__(self, transcript: Transcript, parent=None):
        super().__init__(parent)
        self.t = transcript
        self.open_list = False  # the next editor shows its list at once (for the segment a split made)

    def createEditor(self, parent, option, index):
        self.editing_started.emit(index.row())
        combo = QComboBox(parent)
        for sid, name in self.t.speakers.items():
            combo.addItem(name, sid)
        combo.activated.connect(lambda _: (self.commitData.emit(combo), self.closeEditor.emit(combo)))
        if self.open_list:
            self.open_list = False
            QTimer.singleShot(0, combo, combo.showPopup)  # once the table has placed it
        return combo

    def setEditorData(self, editor, index) -> None:
        editor.setCurrentIndex(max(editor.findData(index.data(Qt.EditRole)), 0))

    def setModelData(self, editor, model, index) -> None:
        model.setData(index, editor.currentData(), Qt.EditRole)


class TextDelegate(EditingDelegate):
    """Wraps a segment's text and shows the words Whisper was unsure of in yellow, and what Find
    found in green. Rows get their height from the font's metrics, which wrap plain text the way
    the drawn document does: laying out a document for each of 3,000 rows took seconds whenever
    the column changed width. While a text is edited, Shift+Enter splits it at the cursor."""

    split = Signal(int, str, str)  # the row, and its text before the cursor and after it

    def __init__(self, view: QTableView, transcript: Transcript):
        super().__init__(view)
        self.view = view
        self.t = transcript
        self.found: tuple[str, bool] | None = None  # (the text looked for, match case) while the find bar shows
        self.current: tuple[int, int, int] | None = None  # the match Next or Previous went to
        self._editing = QPersistentModelIndex()

    def createEditor(self, parent, option, index):
        self._editing = QPersistentModelIndex(index)
        self.editing_started.emit(index.row())
        return super().createEditor(parent, option, index)

    def eventFilter(self, editor, event) -> bool:
        if (event.type() == QEvent.KeyPress and event.key() in (Qt.Key_Return, Qt.Key_Enter)
                and event.modifiers() & Qt.ShiftModifier and isinstance(editor, QLineEdit)):
            text, cursor = editor.text(), editor.cursorPosition()
            if proofread.can_split(text[:cursor], text[cursor:]) and self._editing.isValid():
                row = self._editing.row()
                self.closeEditor.emit(editor, QAbstractItemDelegate.NoHint)  # the split takes the text as typed
                self.split.emit(row, text[:cursor], text[cursor:])
                return True
        return super().eventFilter(editor, event)  # Enter finishes the edit

    def _document(self, index: QModelIndex, option, width: int) -> QTextDocument:
        row = index.row()
        seg = self.t.segments[row]
        colors = highlight_colors(option.palette)
        matches = proofread.matches_in(seg.text, *self.found) if self.found else []
        current = self.current[1:] if self.current is not None and self.current[0] == row else None
        parts = []
        for text, kind in highlight(marked_runs(seg, ExportOptions(mark_uncertain=True)), matches, current):
            text = html.escape(text)
            if kind is None:
                parts.append(text)
            else:
                background, color = colors[kind]
                parts.append(f'<span style="background-color:{background}; color:{color}">{text}</span>')
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


class FindEdit(QLineEdit):
    """Enter goes to the next match, Shift+Enter to the one before."""

    step = Signal(int)

    def keyPressEvent(self, event) -> None:
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            self.step.emit(-1 if event.modifiers() & Qt.ShiftModifier else 1)
            return
        super().keyPressEvent(event)


class ProofreadWindow(QMainWindow):
    closed = Signal(object)  # this window, once it has closed

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
        self._moving = False  # the window moves the current row itself, not the user
        self._follow = True  # the row follows the audio, until the user picks another row or scrolls
        self._match: tuple[int, int, int] | None = None  # (row, start, end) of the match Find went to
        self._edit_end: float | None = None  # where playback stops while a segment is being edited
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
        self.btn_save_as = QPushButton(tr("pr_save_as"), clicked=self.save_as)
        self.btn_save_as.setToolTip(tr("pr_save_as_tip"))
        self.btn_save = QPushButton(tr("pr_save"), objectName="primary", clicked=self.save)
        bar.addWidget(self.btn_play)
        bar.addWidget(self.lbl_time)
        bar.addWidget(self.btn_find)
        bar.addStretch(1)
        bar.addWidget(self.btn_undo)
        bar.addWidget(self.btn_save_as)
        bar.addWidget(self.btn_save)
        root.addLayout(bar)
        self.find_bar = self._build_find_bar()
        root.addWidget(self.find_bar)

        self.model = SegmentModel(self.t, self)
        self.model.edited.connect(self._on_cell_edited)
        for changed in (self.model.dataChanged, self.model.rowsRemoved, self.model.rowsInserted):
            changed.connect(self._refresh_find)
        self.table = SegmentTable()
        self.table.setModel(self.model)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.DoubleClicked | QAbstractItemView.EditKeyPressed)
        self.table.setWordWrap(True)
        self.speaker_delegate = SpeakerDelegate(self.t, self.table)
        self.table.setItemDelegateForColumn(SPEAKER, self.speaker_delegate)
        self.text_delegate = TextDelegate(self.table, self.t)
        self.table.setItemDelegateForColumn(TEXT, self.text_delegate)
        for delegate in (self.speaker_delegate, self.text_delegate):
            delegate.editing_started.connect(self._on_editing_started)
            delegate.editing_ended.connect(self._on_editing_ended)
        self.text_delegate.split.connect(self.split_segment, Qt.QueuedConnection)  # once its editor has closed
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
        self.table.verticalScrollBar().actionTriggered.connect(self._stop_following)  # the wheel or bar, not scrollTo
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
        QShortcut(QKeySequence("Ctrl+Shift+S"), self, activated=self.save_as)  # Qt has no Save As key on Windows
        QShortcut(QKeySequence.Undo, self, activated=self.undo)  # an open editor undoes its own typing first
        QShortcut(QKeySequence("Ctrl+F"), self, activated=self.show_find)
        QShortcut(QKeySequence("Ctrl+H"), self, activated=self.show_replace)
        QShortcut(QKeySequence.FindNext, self, activated=self.find_next)  # F3
        QShortcut(QKeySequence.FindPrevious, self, activated=self.find_previous)  # Shift+F3
        self.timer = QTimer(self, interval=100)
        self.timer.timeout.connect(self._tick)

    def _build_find_bar(self) -> QWidget:
        bar = QWidget(visible=False)
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(0, 0, 0, 0)
        self.edit_find = FindEdit(placeholderText=tr("pr_find_placeholder"), clearButtonEnabled=True)
        self.edit_find.setMinimumWidth(220)
        self.edit_find.textChanged.connect(self._search)
        self.edit_find.step.connect(self._step)
        self.btn_find_previous = QPushButton(tr("pr_find_previous"), clicked=self.find_previous)
        self.btn_find_previous.setToolTip("Shift+Enter, Shift+F3")
        self.btn_find_next = QPushButton(tr("pr_find_next"), clicked=self.find_next)
        self.btn_find_next.setToolTip("Enter, F3")
        self.chk_match_case = QCheckBox(tr("pr_match_case"))
        self.chk_match_case.toggled.connect(self._search)
        self.lbl_matches = QLabel(objectName="hint")
        self.edit_replace = QLineEdit(placeholderText=tr("pr_replace_placeholder"), clearButtonEnabled=True)
        self.edit_replace.setMinimumWidth(220)
        self.edit_replace.returnPressed.connect(self.replace)
        self.btn_replace = QPushButton(tr("pr_replace"), clicked=self.replace)
        self.btn_replace_all = QPushButton(tr("pr_replace_all"), clicked=self.replace_all)
        self._replace_widgets = (self.edit_replace, self.btn_replace, self.btn_replace_all)
        close = QToolButton(text="✕", autoRaise=True, clicked=self.hide_find)
        close.setToolTip(tr("pr_find_close"))
        for widget in (self.edit_find, self.btn_find_previous, self.btn_find_next, self.chk_match_case,
                       self.lbl_matches):
            layout.addWidget(widget)
        layout.addSpacing(16)
        for widget in self._replace_widgets:
            layout.addWidget(widget)
        layout.addStretch(1)
        layout.addWidget(close)
        QShortcut(QKeySequence(Qt.Key_Escape), bar, activated=self.hide_find, context=Qt.WidgetWithChildrenShortcut)
        return bar

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

    def split_segment(self, row: int, before: str, after: str) -> bool:
        """Splits segment `row` into the text `before` the cursor and the text `after` it, which goes to
        a new segment below, and opens the list of speakers for that one (Shift+Enter)."""
        if not 0 <= row < len(self.t.segments) or not proofread.can_split(before, after):
            return False
        seg = self.t.segments[row]
        old = seg.text, seg.end, seg.words
        self.model.beginInsertRows(QModelIndex(), row + 1, row + 1)
        proofread.split_segment(self.t, row, before, after)
        self.model.endInsertRows()
        self.model.row_changed(row)

        def undo():  # the edits after this one are undone already, so the rows are where they were
            self.model.beginRemoveRows(QModelIndex(), row + 1, row + 1)
            del self.t.segments[row + 1]
            self.model.endRemoveRows()
            seg.text, seg.end, seg.words = old
            self.model.row_changed(row)
            self._fill_speakers()
        self._remember(undo)
        self._fill_speakers()
        self.lbl_status.setText(tr("pr_split"))
        index = self.model.index(row + 1, SPEAKER)
        self.table.setCurrentIndex(index)
        self.speaker_delegate.open_list = True
        self.table.edit(index)
        return True

    # -------------------------------------------------------------------- find
    def show_find(self) -> None:
        self._open_find(replace=False)

    def show_replace(self) -> None:
        self._open_find(replace=True)

    def _open_find(self, replace: bool) -> None:
        self.find_bar.show()
        for widget in self._replace_widgets:
            widget.setVisible(replace)
        self.edit_find.setFocus()
        self.edit_find.selectAll()
        self._search()

    def hide_find(self) -> None:
        self.find_bar.hide()
        self._match = self.text_delegate.found = self.text_delegate.current = None
        self.table.viewport().update()
        self.table.setFocus()

    def find_next(self) -> bool:
        return self._step(1)

    def find_previous(self) -> bool:
        return self._step(-1)

    def _step(self, step: int) -> bool:
        """To the next match (step 1) or the one before (-1), around the ends; True when there is one.
        F3 with the find bar closed opens it."""
        if self.find_bar.isHidden():
            self.show_find()
        else:
            self._go(step, self._cursor(past_current=step > 0))
        return self._match is not None

    def _search(self, *_) -> None:
        """The text looked for or Match case changed: the first match from the current one on."""
        if not self.find_bar.isHidden():
            self._go(1, self._cursor(past_current=False))

    def _cursor(self, past_current: bool) -> tuple[int, int]:
        """Where looking goes on from, as (row, offset): the current match (or just past its start)
        while its row is the current one, else the start of the current row."""
        row = self.table.currentIndex().row()
        if self._match is not None and self._match[0] == row:
            return row, self._match[1] + (1 if past_current else 0)
        return row, 0

    def _go(self, step: int, cursor: tuple[int, int]) -> None:
        """To the first match at or after `cursor` (step 1), or the last one before it (-1)."""
        matches = proofread.find(self.t, self.edit_find.text(), self.chk_match_case.isChecked())
        if step > 0:
            match = next((m for m in matches if m[:2] >= cursor), matches[0] if matches else None)
        else:
            match = next((m for m in reversed(matches) if m[:2] < cursor), matches[-1] if matches else None)
        if match is not None:
            if match[0] != self.table.currentIndex().row():
                self.table.setCurrentIndex(self.model.index(match[0], TIME))  # as the user picking it would
            self._stop_following()
            self.table.scrollTo(self.model.index(match[0], TEXT))
        self._show_matches(matches, match)

    def _show_matches(self, matches: list[tuple[int, int, int]], match: tuple[int, int, int] | None) -> None:
        self._match = match
        needle = self.edit_find.text()
        self.text_delegate.found = (needle, self.chk_match_case.isChecked()) if needle else None
        self.text_delegate.current = match
        if not needle:
            label = ""
        elif not matches:
            label = tr("pr_find_none")
        elif match in matches:
            label = tr("pr_find_count", i=matches.index(match) + 1, n=len(matches))
        else:
            label = tr("pr_find_total", n=len(matches))
        self.lbl_matches.setText(label)
        self.table.viewport().update()

    def _refresh_find(self, *_) -> None:
        """The texts or the current row changed: count again, and keep the current match while it is
        still one, in the current row."""
        if self.find_bar.isHidden() or not self.edit_find.text():
            return
        matches = proofread.find(self.t, self.edit_find.text(), self.chk_match_case.isChecked())
        match = self._match
        if match not in matches or match[0] != self.table.currentIndex().row():
            match = None
        self._show_matches(matches, match)

    def replace(self) -> bool:
        """Replaces the current match and goes to the next one; with no match current, goes to one
        first. True when it replaced something."""
        match, row = self._match, self.table.currentIndex().row()
        if match is None or match[0] != row or match[1:] not in proofread.matches_in(
                self.t.segments[row].text, self.edit_find.text(), self.chk_match_case.isChecked()):
            self._search()
            return False
        seg, (_, start, end) = self.t.segments[row], match
        old, replacement = seg.text, self.edit_replace.text()
        after = proofread.replace_one(self.t, row, start, end, replacement)
        if after is None:  # the same text, or none at all
            if not (old[:start] + replacement + old[end:]).strip():
                self.lbl_status.setText(tr("pr_replace_empty"))
            self._go(1, (row, start + 1))
            return False
        self._remember_texts([(seg, old)])
        self.model.row_changed(row)
        self._go(1, (row, after))
        return True

    def replace_all(self) -> int:
        """Replaces every match, as one edit for Undo; how many it replaced."""
        needle = self.edit_find.text()
        if not needle:
            return 0
        done = proofread.replace_all(self.t, needle, self.edit_replace.text(), self.chk_match_case.isChecked())
        if done.changed:
            self._remember_texts([(self.t.segments[i], old) for i, old in done.changed])
            self.model.rows_changed(done.changed[0][0], done.changed[-1][0])
        self.lbl_status.setText(tr("pr_replaced_kept", n=done.count, kept=done.kept) if done.kept
                                else tr("pr_replaced", n=done.count))
        self._search()
        return done.count

    def _remember_texts(self, changes: list[tuple[Segment, str]]) -> None:
        """One undo step for the texts Replace changed: (segment, its text before)."""
        def undo():
            rows = {id(seg): row for row, seg in enumerate(self.t.segments)}
            for seg, old in changes:
                seg.text = old
            changed = [rows[id(seg)] for seg, _ in changes if id(seg) in rows]
            if changed:
                self.model.rows_changed(min(changed), max(changed))
        self._remember(undo)

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

    def _start(self, seconds: float, end: float | None = None) -> None:
        try:
            self.player.play(seconds, end)
        except UserError as exc:
            QMessageBox.warning(self, APP_NAME, tr(exc.key, **exc.kwargs))
            return
        self._resume_at = None
        self._follow = True
        self.btn_play.setText(tr("pr_pause"))
        self.timer.start()

    def _stop(self) -> None:
        self.player.stop()
        self.timer.stop()
        self.btn_play.setText(tr("pr_play"))

    def _on_row_changed(self, *_) -> None:
        if not self._moving:
            self._resume_at = None  # a row the user picked plays from its start
            self._stop_following()
            self._refresh_find()  # a match in another row is no longer the current one

    def _stop_following(self, *_) -> None:
        self._follow = False  # until playback starts again: the user is reading elsewhere

    def _on_editing_started(self, row: int) -> None:
        """While the recording plays, editing a segment plays just that one, so the audio doesn't run
        ahead of the edit: on from where it is while that is inside it, else from its start, and it
        stops at the segment's end."""
        if self.player is None or not self.player.playing or not 0 <= row < len(self.t.segments):
            return
        seg = self.t.segments[row]
        if seg.start <= self.player.position() < seg.end:
            self.player.set_end(seg.end)
        else:
            self._start(seg.start, seg.end)
        self._edit_end = seg.end

    def _on_editing_ended(self) -> None:
        if self._edit_end is not None and self.player is not None and self.player.playing:
            self.player.set_end(None)  # the edit is done before the segment: play on
        self._edit_end = None

    def _select(self, row: int) -> None:
        self._moving = True
        try:
            self.table.setCurrentIndex(self.model.index(row, TIME))
        finally:
            self._moving = False
        self.table.scrollTo(self.model.index(row, TEXT))

    def _tick(self) -> None:
        if self.player is None:
            return
        position = self.player.position()
        self.lbl_time.setText(mmss(position))
        row = proofread.segment_at(self.t, position)
        editing = self.table.state() == QAbstractItemView.EditingState
        if self._follow and row is not None and row != self.table.currentIndex().row() and not editing:
            self._select(row)
        if not self.player.playing:
            if self._edit_end is not None:
                self._resume_at = position  # it stopped at the end of the segment being edited: Space goes on
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
        self._saved(tr("pr_saved", n=len(written)))
        return True

    def save_as(self) -> bool:
        """Writes the transcript and its run's formats under a new name, keeping the files it came
        from; the window then works on the new ones."""
        path, _ = QFileDialog.getSaveFileName(self, tr("pr_save_as_title"), str(proofread.save_as_name(self.json_path)),
                                              f"{tr('proofread_filter')} (*_transcript*.json)",
                                              options=QFileDialog.DontConfirmOverwrite)  # asked below, for every file
        if not path:
            return False
        target = proofread.transcript_path(Path(path))
        if target.resolve() == self.json_path.resolve():
            return self.save()
        if any(w is not self and w.isVisible() and w.json_path.resolve() == target.resolve()
               for w in QApplication.topLevelWidgets() if isinstance(w, ProofreadWindow)):
            QMessageBox.warning(self, APP_NAME, tr("pr_open_elsewhere", name=target.name))
            return False
        existing = [p for p in proofread.save_as_files(self.json_path, target) if p.exists()]
        if existing and QMessageBox.question(self, APP_NAME, tr("pr_replace_files", files="\n".join(
                p.name for p in existing))) != QMessageBox.Yes:
            return False
        try:
            written = proofread.save_as(self.t, self.json_path, target, self.export_options())
        except UserError as exc:
            QMessageBox.warning(self, APP_NAME, tr(exc.key, **exc.kwargs))
            return False
        self.json_path = target
        self._saved(tr("pr_saved_as", n=len(written), name=target.name))
        return True

    def _saved(self, message: str) -> None:
        self._saved_depth = len(self._undo)
        self._update_dirty()
        self.lbl_status.setText(message)

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
        self.closed.emit(self)
        super().closeEvent(event)
