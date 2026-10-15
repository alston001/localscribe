"""Background threads: hardware probe, duration probe, conversions, pyannote download."""

from __future__ import annotations

import logging
import queue
import threading
import time
import traceback
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QThread, Signal

from ..core import device as dev
from ..core.errors import Cancelled, UserError
from ..core.media import probe_duration
from ..core.models import ModelStore
from ..core.pipeline import Engine, JobOptions
from ..export import write_outputs
from ..export.common import ExportOptions
from ..i18n import tr, tr_warning

log = logging.getLogger("localscribe")


class DeviceProbe(QThread):
    """Imports torch and finds the GPU without freezing the window (takes several seconds)."""

    ready = Signal(object)

    def run(self) -> None:
        try:
            info = dev.detect()
        except Exception:
            log.exception("Hardware detection failed")
            info = dev.DeviceInfo.cpu_only()  # never leave the status bar at "Detecting…"
        self.ready.emit(info)


class DurationProbe(QThread):
    found = Signal(int, float)

    def __init__(self, items: list[tuple[int, Path]], parent=None):
        super().__init__(parent)
        self.items = items

    def run(self) -> None:
        for job_id, path in self.items:
            try:
                seconds = probe_duration(path)
            except Exception:
                log.warning("Could not read the length of %s", path.name, exc_info=True)
                continue
            if seconds:
                self.found.emit(job_id, seconds)


@dataclass
class Task:
    job_id: int
    path: Path
    options: JobOptions
    formats: list[str]
    export_options: ExportOptions
    output_dir: Path | None


class ProcessThread(QThread):
    job_started = Signal(int)
    job_progress = Signal(int, str, float, str)
    job_finished = Signal(int, list, list)  # job id, written paths, translated warnings
    job_failed = Signal(int, str, str)
    job_stopped = Signal(int)

    def __init__(self, engine: Engine, parent=None):
        super().__init__(parent)
        self.engine = engine
        self.tasks: queue.Queue[Task] = queue.Queue()
        self.cancel = threading.Event()

    def add(self, task: Task) -> None:
        self.tasks.put(task)

    def run(self) -> None:
        while not self.cancel.is_set():
            try:
                task = self.tasks.get_nowait()
            except queue.Empty:
                break
            self._run(task)
        while True:  # after Stop, hand back whatever was still queued
            try:
                self.job_stopped.emit(self.tasks.get_nowait().job_id)
            except queue.Empty:
                break

    def _run(self, task: Task) -> None:
        self.job_started.emit(task.job_id)
        last = {"t": 0.0, "stage": "", "overall": -1.0}

        def report(p) -> None:
            now = time.monotonic()
            if p.stage != last["stage"] or now - last["t"] > 0.2 or p.overall - last["overall"] > 0.01:
                last.update(t=now, stage=p.stage, overall=p.overall)
                self.job_progress.emit(task.job_id, p.stage, p.overall, p.detail)

        try:
            transcript = self.engine.transcribe_file(task.path, task.options, progress=report, cancel=self.cancel)
            self.job_progress.emit(task.job_id, "export", 0.99, "")
            written = write_outputs(transcript, task.output_dir or task.path.parent, task.formats,
                                    task.export_options)
            for warning in transcript.warnings:
                log.warning("%s: %s", task.path.name, tr_warning(warning))
            self.job_finished.emit(task.job_id, [str(p) for p in written],
                                   [tr_warning(w) for w in transcript.warnings])
        except Cancelled:
            self.job_stopped.emit(task.job_id)
        except UserError as exc:
            self.job_failed.emit(task.job_id, tr(exc.key, **exc.kwargs), "")
        except Exception as exc:
            details = traceback.format_exc()
            log.error("%s failed:\n%s", task.path, details)
            self.job_failed.emit(task.job_id, tr("err_unexpected", detail=f"{type(exc).__name__}: {exc}"), details)


class ConvertThread(QThread):
    file_started = Signal(int)
    file_progress = Signal(int, float)
    file_done = Signal(int, str)
    file_failed = Signal(int, str)
    file_stopped = Signal(int)

    def __init__(self, items: list[tuple[int, Path]], folder: Path | None, fmt: str, parent=None):
        super().__init__(parent)
        self.items, self.folder, self.fmt = items, folder, fmt
        self.cancel = threading.Event()

    def run(self) -> None:
        from ..core.convert import convert_file

        for row, path in self.items:
            if self.cancel.is_set():
                break
            self.file_started.emit(row)
            try:
                out = convert_file(path, self.folder, self.fmt, cancel=self.cancel,
                                   progress=lambda f, r=row: self.file_progress.emit(r, f))
                log.info("Converted %s -> %s", path.name, out)
                self.file_done.emit(row, str(out))
            except Cancelled:
                self.file_stopped.emit(row)
                break
            except UserError as exc:
                self.file_failed.emit(row, tr(exc.key, **exc.kwargs))
            except Exception as exc:
                log.exception("Conversion of %s failed", path)
                self.file_failed.emit(row, tr("err_unexpected", detail=f"{type(exc).__name__}: {exc}"))


class PyannoteDownload(QThread):
    progress = Signal(object, object)  # done bytes, total bytes
    done = Signal(bool, str)

    def __init__(self, models_dir: Path, token: str, parent=None):
        super().__init__(parent)
        self.store = ModelStore(models_dir)
        self.token = token
        self.cancel = threading.Event()

    def run(self) -> None:
        try:
            self.store.download_pyannote(self.token, progress=self.progress.emit, cancel=self.cancel)
            self.done.emit(True, tr("pyannote_ok"))
        except Cancelled:
            self.done.emit(False, "")
        except UserError as exc:
            self.done.emit(False, tr(exc.key, **exc.kwargs))
        except Exception as exc:
            log.exception("pyannote download failed")
            self.done.emit(False, tr("err_unexpected", detail=f"{type(exc).__name__}: {exc}"))
