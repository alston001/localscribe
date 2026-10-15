"""The file queue: job records, table model, progress-bar column and drop hint."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QHeaderView, QStyle, QStyledItemDelegate,
                               QStyleOptionProgressBar, QTableView)

from ..export.common import duration_text
from ..i18n import tr
from . import style


@dataclass
class Job:
    id: int
    path: Path
    duration: float | None = None
    status: str = "waiting"   # waiting | queued | running | done | failed | stopped
    stage: str = ""
    progress: float = 0.0
    detail: str = ""
    outputs: list[str] = field(default_factory=list)
    error: str = ""
    error_details: str = ""

    @property
    def active(self) -> bool:
        return self.status in ("queued", "running")

    def status_text(self) -> str:
        if self.status == "running":
            text = tr(f"st_{self.stage}") if self.stage else tr("st_decode")
            if self.stage == "download" and self.detail:
                text += f" · {self.detail.split(': ', 1)[-1]}"
            return text
        return tr({"waiting": "st_waiting", "queued": "st_waiting", "done": "st_done",
                   "failed": "st_failed", "stopped": "st_stopped"}[self.status])


class JobTableModel(QAbstractTableModel):
    COLUMNS = ("col_file", "col_length", "col_status", "col_progress")
    PROGRESS = 3

    def __init__(self, parent=None):
        super().__init__(parent)
        self.jobs: list[Job] = []
        self._next_id = 1

    # Qt model API
    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self.jobs)

    def columnCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self.COLUMNS)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if orientation == Qt.Horizontal and role == Qt.DisplayRole:
            return tr(self.COLUMNS[section])
        return None

    def data(self, index: QModelIndex, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        job, col = self.jobs[index.row()], index.column()
        if role == Qt.DisplayRole:
            if col == 0:
                return job.path.name
            if col == 1:
                return duration_text(job.duration) if job.duration else "…"
            if col == 2:
                return job.status_text()
            return None  # drawn by ProgressDelegate
        if role == Qt.ToolTipRole:
            if col == 0:
                return str(job.path)
            if col == 2 and job.error:
                return job.error
        if role == Qt.ForegroundRole and col == 2:
            key = "running" if job.status == "running" else job.status
            if key in style.STATUS_COLORS:
                return QColor(style.STATUS_COLORS[key])
        if role == Qt.TextAlignmentRole and col == 1:
            return int(Qt.AlignRight | Qt.AlignVCenter)
        if role == Qt.UserRole:
            return job
        return None

    # helpers
    def add(self, paths: list[Path]) -> list[Job]:
        if not paths:
            return []
        first = len(self.jobs)
        self.beginInsertRows(QModelIndex(), first, first + len(paths) - 1)
        new = []
        for path in paths:
            new.append(Job(self._next_id, path))
            self._next_id += 1
        self.jobs.extend(new)
        self.endInsertRows()
        return new

    def remove(self, job_ids: set[int]) -> None:
        for row in sorted((i for i, j in enumerate(self.jobs) if j.id in job_ids), reverse=True):
            self.beginRemoveRows(QModelIndex(), row, row)
            del self.jobs[row]
            self.endRemoveRows()

    def find(self, job_id: int) -> tuple[int, Job | None]:
        for row, job in enumerate(self.jobs):
            if job.id == job_id:
                return row, job
        return -1, None

    def refresh(self, job_id: int) -> None:
        row, _ = self.find(job_id)
        if row >= 0:
            self.dataChanged.emit(self.index(row, 0), self.index(row, len(self.COLUMNS) - 1))

    def retranslate(self) -> None:
        self.headerDataChanged.emit(Qt.Horizontal, 0, len(self.COLUMNS) - 1)
        if self.jobs:
            self.dataChanged.emit(self.index(0, 0), self.index(len(self.jobs) - 1, len(self.COLUMNS) - 1))


class ProgressDelegate(QStyledItemDelegate):
    def paint(self, painter: QPainter, option, index: QModelIndex) -> None:
        job: Job = index.data(Qt.UserRole)
        if job is None or job.status in ("waiting", "queued"):
            return super().paint(painter, option, index)
        bar = QStyleOptionProgressBar()
        bar.rect = option.rect.adjusted(6, 7, -6, -7)
        bar.minimum, bar.maximum = 0, 1000
        bar.progress = int(job.progress * 1000)
        bar.text = f"{job.progress * 100:.0f}%"
        bar.textVisible = True
        bar.state = QStyle.State_Enabled | QStyle.State_Horizontal
        bar.palette = option.palette
        color = style.STATUS_COLORS.get(job.status, style.ACCENT)
        bar.palette.setColor(bar.palette.ColorRole.Highlight, QColor(color))
        QApplication.style().drawControl(QStyle.CE_ProgressBar, bar, painter)


class QueueView(QTableView):
    """Table that shows a drop hint while empty."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.setShowGrid(False)
        self.setAlternatingRowColors(True)
        self.setWordWrap(False)
        self.verticalHeader().hide()
        self.verticalHeader().setDefaultSectionSize(34)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.setItemDelegateForColumn(JobTableModel.PROGRESS, ProgressDelegate(self))

    def setModel(self, model) -> None:
        super().setModel(model)
        header = self.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        header.setSectionResizeMode(1, QHeaderView.Fixed)
        header.setSectionResizeMode(2, QHeaderView.Fixed)
        header.setSectionResizeMode(3, QHeaderView.Fixed)
        header.resizeSection(1, 72)
        header.resizeSection(2, 250)  # fits "Downloading model · 1.23 GB / 2.88 GB"
        header.resizeSection(3, 140)
        header.setHighlightSections(False)
        header.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        if self.model() is not None and self.model().rowCount() == 0:
            painter = QPainter(self.viewport())
            painter.setPen(QColor(style.MUTED))
            font = painter.font()
            font.setPointSize(12)
            painter.setFont(font)
            painter.drawText(self.viewport().rect(), Qt.AlignCenter, tr("drop_hint"))
            painter.end()
