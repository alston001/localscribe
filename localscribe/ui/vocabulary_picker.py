"""Word banks in the main window: a searchable drop-down to pick one, and the editor."""

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import QEvent, QPoint, QPointF, QRect, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (QApplication, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QFrame, QLabel,
                               QLineEdit, QListWidget, QListWidgetItem, QPlainTextEdit, QPushButton, QStyle,
                               QStyledItemDelegate, QToolTip, QVBoxLayout, QWidget)

from ..i18n import tr
from ..vocabulary import PROMPT_LIMIT, TokenCounter, Vocabulary, find_vocabulary, parse_terms, prompt_terms
from . import style

_NAME = Qt.UserRole       # the word bank's name; "" for None
_COUNT = Qt.UserRole + 1  # its term count, as shown
_VISIBLE_ROWS = 8


def _icon(kind: str) -> QIcon:
    """Line icons drawn in code like the style sheet's, at 1x and 2x for high-DPI screens."""
    icon = QIcon()
    for scale in (1, 2):
        pix = QPixmap(16 * scale, 16 * scale)
        pix.setDevicePixelRatio(scale)
        pix.fill(Qt.transparent)
        p = QPainter(pix)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(QPen(QColor(style.MUTED), 1.4, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        if kind == "search":
            p.drawEllipse(QPointF(6.8, 6.8), 4.3, 4.3)
            p.drawLine(QPointF(10, 10), QPointF(13.5, 13.5))
        elif kind == "edit":  # pencil
            p.drawPolygon([QPointF(2.5, 13.5), QPointF(3, 10.5), QPointF(10.5, 3), QPointF(13, 5.5),
                           QPointF(5.5, 13)])
            p.drawLine(QPointF(9, 4.5), QPointF(11.5, 7))
        else:  # delete: a bin
            p.drawLine(QPointF(2.5, 4.5), QPointF(13.5, 4.5))
            p.drawPolyline([QPointF(6, 4.5), QPointF(6.5, 2.5), QPointF(9.5, 2.5), QPointF(10, 4.5)])
            p.drawPolyline([QPointF(4, 4.5), QPointF(4.8, 13.5), QPointF(11.2, 13.5), QPointF(12, 4.5)])
            p.drawLine(QPointF(6.8, 7), QPointF(6.8, 11))
            p.drawLine(QPointF(9.2, 7), QPointF(9.2, 11))
        p.end()
        icon.addPixmap(pix)
    return icon


class _RowDelegate(QStyledItemDelegate):
    """Paints a row (name, term count, edit and delete buttons) and turns clicks into actions."""

    picked = Signal(str)
    edit_clicked = Signal(str)
    delete_clicked = Signal(str)

    def __init__(self, current: str, parent=None):
        super().__init__(parent)
        self.current = current.casefold()
        self.icons = {"edit": _icon("edit"), "delete": _icon("delete")}

    @staticmethod
    def button_rects(rect: QRect) -> dict[str, QRect]:
        size = 24
        delete = QRect(rect.right() - 4 - size, rect.center().y() - size // 2 + 1, size, size)
        return {"edit": delete.translated(-size - 2, 0), "delete": delete}

    def hit(self, rect: QRect, pos: QPoint) -> str | None:
        """Which button of a word bank's row pos is on: "edit", "delete" or None."""
        return next((kind for kind, box in self.button_rects(rect).items() if box.contains(pos)), None)

    def sizeHint(self, option, index) -> QSize:
        return QSize(super().sizeHint(option, index).width(), max(30, option.fontMetrics.height() + 14))

    def paint(self, painter, option, index) -> None:
        painter.save()
        rect, name = option.rect, index.data(_NAME)
        if option.state & QStyle.State_Selected:
            painter.fillRect(rect, QColor("#DBEAFE"))
        elif option.state & QStyle.State_MouseOver:
            painter.fillRect(rect, QColor(style.WINDOW))
        text = rect.adjusted(10, 0, -8, 0)
        if name:
            buttons = self.button_rects(rect)
            for kind, box in buttons.items():
                self.icons[kind].paint(painter, box.adjusted(4, 4, -4, -4))
            count = index.data(_COUNT)
            width = option.fontMetrics.horizontalAdvance(count)
            count_box = QRect(buttons["edit"].left() - 6 - width, rect.top(), width, rect.height())
            painter.setPen(QColor(style.MUTED))
            painter.drawText(count_box, Qt.AlignVCenter | Qt.AlignRight, count)
            text.setRight(count_box.left() - 10)
        font = QFont(option.font)
        font.setBold(name.casefold() == self.current)
        painter.setFont(font)
        painter.setPen(QColor(style.TEXT))
        label = QFontMetrics(font).elidedText(index.data(Qt.DisplayRole), Qt.ElideRight, text.width())
        painter.drawText(text, Qt.AlignVCenter | Qt.AlignLeft, label)
        painter.restore()

    def editorEvent(self, event, model, option, index) -> bool:
        if event.type() == QEvent.MouseButtonRelease and event.button() == Qt.LeftButton:
            name = index.data(_NAME)
            kind = self.hit(option.rect, event.position().toPoint()) if name else None
            {"edit": self.edit_clicked, "delete": self.delete_clicked}.get(kind, self.picked).emit(name)
            return True
        return super().editorEvent(event, model, option, index)

    def helpEvent(self, event, view, option, index) -> bool:
        kind = self.hit(option.rect, event.pos()) if index.data(_NAME) else None
        if event.type() == QEvent.ToolTip and kind:
            QToolTip.showText(event.globalPos(), {"edit": tr("vocab_edit"), "delete": tr("vocab_delete")}[kind], view)
            return True
        return super().helpEvent(event, view, option, index)


class _Popup(QFrame):
    """The open drop-down: a search box, None and the word banks, and New word bank."""

    picked = Signal(str)
    new_requested = Signal(str)
    edit_requested = Signal(str)
    delete_requested = Signal(str)
    closed = Signal()

    def __init__(self, entries: list[tuple[str, int]], current: str, parent: QWidget):
        super().__init__(parent, Qt.Popup)
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.setObjectName("vocabularyPopup")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(4)
        self.search = QLineEdit()
        self.search.setPlaceholderText(tr("vocab_search"))
        self.search.setClearButtonEnabled(True)
        self.search.addAction(_icon("search"), QLineEdit.LeadingPosition)
        self.search.textChanged.connect(self._filter)
        self.search.installEventFilter(self)
        layout.addWidget(self.search)

        self.list = QListWidget()
        self.list.setFocusPolicy(Qt.NoFocus)  # typing stays in the search box
        self.list.setMouseTracking(True)
        self.list.setFrameShape(QFrame.NoFrame)
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.delegate = _RowDelegate(current, self.list)
        self.list.setItemDelegate(self.delegate)
        for name, count in [("", 0), *entries]:
            item = QListWidgetItem(name or tr("vocab_none"))
            item.setData(_NAME, name)
            item.setData(_COUNT, tr("vocab_term_count", n=count) if name else "")
            self.list.addItem(item)
        layout.addWidget(self.list)
        self.list.ensurePolished()  # the style sheet's frame counts towards the height
        self.list.setFixedHeight(min(self.list.count(), _VISIBLE_ROWS) * self.list.sizeHintForRow(0)
                                 + 2 * self.list.frameWidth())
        self.lbl_empty = QLabel(tr("vocab_no_match"), objectName="hint", alignment=Qt.AlignCenter)
        self.lbl_empty.setFixedHeight(self.list.height())  # the drop-down keeps its size while searching
        self.lbl_empty.hide()
        layout.addWidget(self.lbl_empty)
        line = QFrame(objectName="vocabularyLine")
        line.setFixedHeight(1)
        layout.addWidget(line)
        self.btn_new = QPushButton(tr("vocab_new"), objectName="vocabularyNew")  # Tab reaches it from the search box
        self.btn_new.clicked.connect(lambda: self._finish(self.new_requested, self.search.text().strip()))
        layout.addWidget(self.btn_new)

        self.delegate.picked.connect(lambda name: self._finish(self.picked, name))
        self.delegate.edit_clicked.connect(lambda name: self._finish(self.edit_requested, name))
        self.delegate.delete_clicked.connect(lambda name: self._finish(self.delete_requested, name))
        names = [self.list.item(row).data(_NAME).casefold() for row in range(self.list.count())]
        self._select(names.index(current.casefold()) if current.casefold() in names else 0)

    def visible_names(self) -> list[str]:
        return [self.list.item(row).data(_NAME) for row in self._visible_rows()]

    def _visible_rows(self) -> list[int]:
        return [row for row in range(self.list.count()) if not self.list.item(row).isHidden()]

    def _select(self, row: int) -> None:
        self.list.setCurrentRow(row)
        self.list.scrollToItem(self.list.item(row))

    def _filter(self, text: str) -> None:
        query = text.strip().casefold()
        for row in range(self.list.count()):
            name = self.list.item(row).data(_NAME)
            self.list.item(row).setHidden(bool(query) and query not in name.casefold())
        rows = self._visible_rows()
        self.list.setVisible(bool(rows))
        self.lbl_empty.setVisible(not rows)
        if rows:
            self._select(rows[0])

    def _move(self, step: int) -> None:
        rows = self._visible_rows()
        if rows:
            here = rows.index(self.list.currentRow()) if self.list.currentRow() in rows else -1
            self._select(rows[max(0, min(len(rows) - 1, here + step))])

    def _finish(self, signal, value: str) -> None:
        self.close()
        signal.emit(value)

    def eventFilter(self, obj, event) -> bool:
        if obj is self.search and event.type() == QEvent.KeyPress:
            steps = {Qt.Key_Up: -1, Qt.Key_Down: 1, Qt.Key_PageUp: -_VISIBLE_ROWS, Qt.Key_PageDown: _VISIBLE_ROWS}
            if event.key() in steps:
                self._move(steps[event.key()])
                return True
            if event.key() in (Qt.Key_Return, Qt.Key_Enter):
                item = self.list.currentItem()
                if item is not None and not item.isHidden():
                    self._finish(self.picked, item.data(_NAME))
                return True
            if event.key() == Qt.Key_Escape:
                self.close()
                return True
        return super().eventFilter(obj, event)

    def mousePressEvent(self, event) -> None:
        combo = self.parentWidget()
        if combo is not None and combo.rect().contains(combo.mapFromGlobal(event.globalPosition().toPoint())):
            self.setAttribute(Qt.WA_NoMouseReplay)  # a click on the drop-down closes it, as in QComboBox
        super().mousePressEvent(event)

    def hideEvent(self, event) -> None:
        super().hideEvent(event)
        self.closed.emit()


class VocabularyPicker(QComboBox):
    """Looks like the other drop-downs, but opens a searchable list of word banks with
    New, Edit and Delete. Shows the chosen bank's name, or None."""

    picked = Signal(str)            # name, "" for None
    new_requested = Signal(str)     # whatever was typed into the search box
    edit_requested = Signal(str)
    delete_requested = Signal(str)
    opening = Signal()              # before the list is built: a chance to set_vocabularies afresh

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)  # long names don't widen the panel
        self.setMinimumContentsLength(12)
        self.addItem("")
        self._entries: list[tuple[str, int]] = []
        self._current = ""
        self._popup: _Popup | None = None

    def set_vocabularies(self, vocabularies: list[Vocabulary], current: str) -> None:
        self._entries = sorted(((v.name, len(v.terms)) for v in vocabularies), key=lambda e: e[0].casefold())
        chosen = find_vocabulary(vocabularies, current)
        self._show(chosen.name if chosen else "")

    def _show(self, name: str) -> None:
        self._current = name
        self.setItemText(0, name or tr("vocab_none"))

    def showPopup(self) -> None:
        if self._popup is not None:
            return
        self.opening.emit()
        popup = _Popup(self._entries, self._current, self)
        popup.picked.connect(self._on_picked)
        popup.new_requested.connect(self.new_requested)
        popup.edit_requested.connect(self.edit_requested)
        popup.delete_requested.connect(self.delete_requested)
        popup.closed.connect(self._on_closed)
        self._popup = popup
        width = max(self.width(), 320)
        popup.resize(width, popup.sizeHint().height())
        screen = (self.screen() or QApplication.primaryScreen()).availableGeometry()
        below = self.mapToGlobal(QPoint(self.width() - width, self.height() + 2))  # right edges line up
        above = self.mapToGlobal(QPoint(0, -popup.height() - 2)).y()
        y = below.y() if below.y() + popup.height() <= screen.bottom() else max(screen.top(), above)
        popup.move(max(screen.left(), min(below.x(), screen.right() - width)), y)
        popup.show()
        popup.search.setFocus()

    def hidePopup(self) -> None:
        if self._popup is not None:
            self._popup.close()

    def _on_closed(self) -> None:
        self._popup = None

    def _on_picked(self, name: str) -> None:
        self._show(name)
        self.picked.emit(name)


class VocabularyEditor(QDialog):
    """A word bank's name and terms, with a live count against Whisper's limit. `on_save` stores
    the result and returns why it couldn't ("" when it did); the editor stays open on failure."""

    def __init__(self, original: Vocabulary | None, taken: list[str], counter: TokenCounter,
                 hotwords: str = "", name_hint: str = "", parent=None,
                 on_save: Callable[[Vocabulary], str] | None = None):
        super().__init__(parent)
        self.taken = {name.casefold(): name for name in taken}
        self.counter, self.hotwords, self.on_save = counter, hotwords, on_save
        self.setWindowTitle(tr("vocab_edit_title" if original else "vocab_new_title"))
        self.setMinimumSize(460, 520)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(6)
        form = QFormLayout()
        self.txt_name = QLineEdit(original.name if original else name_hint)
        self.txt_name.setPlaceholderText(tr("vocab_name_placeholder"))
        form.addRow(tr("vocab_name"), self.txt_name)
        layout.addLayout(form)
        layout.addWidget(QLabel(tr("vocab_terms")))
        layout.addWidget(QLabel(tr("vocab_terms_hint"), objectName="hint", wordWrap=True))
        self.txt_terms = QPlainTextEdit(objectName="terms")
        self.txt_terms.setPlainText("\n".join(original.terms) if original else "")
        self.txt_terms.textChanged.connect(self._update_count)
        layout.addWidget(self.txt_terms, 1)
        self.lbl_count = QLabel(wordWrap=True)
        self.lbl_combined = QLabel(wordWrap=True)
        self.lbl_error = QLabel(wordWrap=True, textFormat=Qt.PlainText)  # it can quote a bank's name
        self.lbl_error.setStyleSheet(f"color: {style.DANGER};")
        self.lbl_error.hide()
        for label in (self.lbl_count, self.lbl_combined, self.lbl_error):
            layout.addWidget(label)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Save).setText(tr("vocab_save"))
        buttons.button(QDialogButtonBox.Cancel).setText(tr("cancel"))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self._update_count()
        (self.txt_terms if original or name_hint else self.txt_name).setFocus()

    def name(self) -> str:
        return " ".join(self.txt_name.text().split())

    def terms(self) -> list[str]:
        return parse_terms(self.txt_terms.toPlainText())

    def vocabulary(self) -> Vocabulary:
        return Vocabulary(self.name(), self.terms())

    def _update_count(self) -> None:
        terms = self.terms()
        used = self.counter.count(terms)
        text = tr("vocab_tokens" if self.counter.exact else "vocab_tokens_estimate",
                  terms=len(terms), n=used, limit=PROMPT_LIMIT)
        if used > PROMPT_LIMIT:
            text += "\n" + tr("vocab_over_limit", limit=PROMPT_LIMIT)
        _show_count(self.lbl_count, text, used > PROMPT_LIMIT)
        self.lbl_count.setToolTip("" if self.counter.exact else tr("vocab_estimate_tip"))
        typed = parse_terms(self.hotwords)
        if typed:  # the Names and terms field (Settings) shares the limit
            both = self.counter.count(prompt_terms(Vocabulary("", terms), self.hotwords))
            _show_count(self.lbl_combined, tr("vocab_with_hotwords", n=both, limit=PROMPT_LIMIT), both > PROMPT_LIMIT)
        self.lbl_combined.setVisible(bool(typed))

    def accept(self) -> None:
        name = self.name()
        if not name:
            error = tr("vocab_name_missing")
        elif name.casefold() in self.taken:
            error = tr("vocab_name_taken", name=self.taken[name.casefold()])
        else:
            error = self.on_save(self.vocabulary()) if self.on_save else ""
            if not error:
                super().accept()
                return
        self.lbl_error.setText(error)
        self.lbl_error.show()
        self.txt_name.setFocus()


def _show_count(label: QLabel, text: str, over: bool) -> None:
    label.setText(text)
    label.setStyleSheet(f"color: {style.DANGER if over else style.MUTED};")
