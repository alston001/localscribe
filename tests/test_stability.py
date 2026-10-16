"""Group C: shutdown, crashes, bad input and flaky networks must not lose work or hang."""

import argparse
import importlib.util
import io
import json
import logging
import os
import subprocess
import sys
import threading
import time
import types
import zipfile
from pathlib import Path

import pytest
import requests

from localscribe.core import models
from localscribe.core.errors import Cancelled, UserError

ROOT = Path(__file__).resolve().parent.parent


class FakeThread:
    """A QThread stand-in whose wait() times out."""

    def __init__(self, finishes: bool = False):
        self.cancel = threading.Event()
        self.finishes = finishes
        self.waited = 0

    def wait(self, ms=None):
        self.waited += 1
        return self.finishes

    def isRunning(self):
        return not (self.finishes and self.waited)


class FakeEvent:
    def __init__(self):
        self.result = None

    def ignore(self):
        self.result = "ignored"

    def accept(self):
        self.result = "accepted"


# ---- C1: closing while a worker is still running -----------------------------------
def test_main_window_close_waits_instead_of_destroying_a_running_thread(monkeypatch):
    from localscribe.ui import main_window
    from PySide6.QtWidgets import QMessageBox

    asked, told = [], []
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: asked.append(1) or QMessageBox.Yes)
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: told.append(a[-1]))
    window = types.SimpleNamespace(worker=FakeThread(), _helpers=[], _closing=False)
    event = FakeEvent()
    main_window.MainWindow.closeEvent(window, event)
    assert event.result == "ignored" and window.worker.cancel.is_set() and len(told) == 1
    event = FakeEvent()
    main_window.MainWindow.closeEvent(window, event)  # a second try does not ask again
    assert event.result == "ignored" and len(asked) == 1


def test_main_window_close_waits_for_helper_threads(monkeypatch):
    from localscribe.ui import main_window
    from PySide6.QtWidgets import QMessageBox

    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    window = types.SimpleNamespace(worker=None, _helpers=[FakeThread()], _closing=False)
    event = FakeEvent()
    main_window.MainWindow.closeEvent(window, event)
    assert event.result == "ignored"


def test_settings_dialog_stays_open_while_the_download_stops(monkeypatch):
    from localscribe.ui import settings_dialog
    from PySide6.QtWidgets import QMessageBox

    told = []
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: told.append(a[-1]))
    dialog = types.SimpleNamespace(download=FakeThread())
    settings_dialog.SettingsDialog.reject(dialog)  # would raise if it reached QDialog.reject
    assert dialog.download.cancel.is_set() and len(told) == 1


# ---- C2: cancelling a conversion ----------------------------------------------------
def test_cancelled_conversion_reports_the_row_as_stopped(monkeypatch, tmp_path):
    from localscribe.ui.threads import ConvertThread

    def cancelled(*args, **kwargs):
        raise Cancelled()

    monkeypatch.setattr("localscribe.core.convert.convert_file", cancelled)
    worker = ConvertThread([(0, tmp_path / "a.qta"), (1, tmp_path / "b.qta")], None, "m4a")
    stopped = []
    worker.file_stopped.connect(stopped.append)
    worker.run()
    assert stopped == [0]


def test_conversion_warnings_reach_the_dialog(monkeypatch, tmp_path):
    from localscribe import i18n
    from localscribe.ui.threads import ConvertThread

    warning = {"key": "warn_partial_decode", "decoded": "0:58", "expected": "1:57"}

    def short(src, folder, fmt, warnings=None, **kwargs):
        warnings.append(warning)
        return tmp_path / "cut (2).m4a"

    monkeypatch.setattr("localscribe.core.convert.convert_file", short)
    worker = ConvertThread([(0, tmp_path / "cut.m4a")], None, "m4a")
    done = []
    worker.file_done.connect(lambda row, out, warnings: done.append((row, out, warnings)))
    worker.run()
    assert done == [(0, str(tmp_path / "cut (2).m4a"), [i18n.tr_warning(warning)])]


def test_a_converted_row_with_warnings_says_so():
    from PySide6.QtWidgets import QStyle

    from localscribe.ui import convert_dialog

    item = types.SimpleNamespace(icon=None, text="", tooltip="", data_=None)
    item.setIcon = lambda icon: setattr(item, "icon", icon)
    item.setText = lambda text: setattr(item, "text", text)
    item.setToolTip = lambda tip: setattr(item, "tooltip", tip)
    item.setData = lambda role, value: None
    item.data = lambda role: "C:/rec/cut.m4a"
    dialog = types.SimpleNamespace(list=types.SimpleNamespace(item=lambda row: item),
                                   style=lambda: types.SimpleNamespace(standardIcon=lambda which: which),
                                   outputs=[], completed=0, counts={"ok": 0, "bad": 0, "warn": 0})
    convert_dialog.ConvertDialog._on_done(dialog, 0, "C:/rec/cut (2).m4a", ["Only 0:58 of 1:57 could be read."])
    assert item.icon == QStyle.SP_MessageBoxWarning
    # The warning gets its own line: appended to the file names it was cut off at the list's edge.
    assert item.text.split("\n") == ["cut.m4a  →  cut (2).m4a", "Only 0:58 of 1:57 could be read."]
    assert "0:58" in item.tooltip
    assert dialog.counts == {"ok": 1, "bad": 0, "warn": 1}  # it still produced a file


def test_a_long_warning_wraps_instead_of_running_off_the_list(tmp_path):
    # Real Qt layout, offscreen, in its own process so no QApplication leaks into other tests.
    script = r'''
import sys
from pathlib import Path
from PySide6.QtWidgets import QApplication
app = QApplication([])
from localscribe.config import Settings
from localscribe.ui.convert_dialog import ConvertDialog
src = Path(sys.argv[1]) / "cut.m4a"
src.write_bytes(b"")
dialog = ConvertDialog(Settings(), [src])
dialog.resize(640, 600)
dialog.show()
dialog.completed, dialog.total_files = 0, 1  # as during a run
dialog._on_done(0, str(src.with_name("cut (4).m4a")),
                ["The file may be damaged: only 0:58 of 1:57 could be read. " * 2])
app.processEvents()
print(dialog.list.horizontalScrollBar().isVisible())
'''
    env = {**os.environ, "QT_QPA_PLATFORM": "offscreen"}
    proc = subprocess.run([sys.executable, "-c", script, str(tmp_path)], cwd=ROOT, env=env,
                          capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip().splitlines()[-1] == "False"


def test_escape_in_the_converter_cancels_but_keeps_the_dialog_open():
    from localscribe.ui import convert_dialog

    cancelled = []
    dialog = types.SimpleNamespace(worker=FakeThread(), _start_or_cancel=lambda: cancelled.append(1))
    convert_dialog.ConvertDialog.reject(dialog)  # would raise if it reached QDialog.reject
    assert cancelled == [1] and dialog.worker.waited == 0  # same as Cancel; the list shows "Stopped"


def test_closing_the_converter_waits_for_the_conversion():
    from localscribe.ui import convert_dialog

    status = types.SimpleNamespace(text="", setText=lambda t: setattr(status, "text", t))
    dialog = types.SimpleNamespace(worker=FakeThread(), lbl_status=status)
    dialog._stop_worker = lambda: convert_dialog.ConvertDialog._stop_worker(dialog)
    event = FakeEvent()
    convert_dialog.ConvertDialog.closeEvent(dialog, event)
    assert dialog.worker.cancel.is_set() and dialog.worker.waited == 1
    assert event.result == "ignored" and status.text


def finished_summary(cancelled: bool, counts: dict) -> tuple[str, object]:
    """The converter's status line after a run, and the dialog it was shown on."""
    from localscribe.ui import convert_dialog

    worker = FakeThread()
    if cancelled:
        worker.cancel.set()
    status = types.SimpleNamespace(text="", setText=lambda t: setattr(status, "text", t))
    dialog = types.SimpleNamespace(worker=worker, lbl_status=status, completed=0, total_files=1,
                                   counts=counts, _update_state=lambda: None,
                                   progress=types.SimpleNamespace(setValue=lambda v: None))
    convert_dialog.ConvertDialog._on_finished(dialog)
    return status.text, dialog


@pytest.mark.parametrize("cancelled, key", [(True, "convert_stopped"), (False, "convert_done")])
def test_converter_summary_says_whether_it_was_stopped(cancelled, key):
    from localscribe import i18n

    text, dialog = finished_summary(cancelled, {"ok": 0, "bad": 0, "warn": 0})
    assert text == i18n.tr(key, ok=0, bad=0) and dialog.worker is None


def test_converter_summary_mentions_warnings():
    from localscribe import i18n

    text, _ = finished_summary(False, {"ok": 1, "bad": 0, "warn": 1})
    assert text == f'{i18n.tr("convert_done", ok=1, bad=0)} {i18n.tr("convert_warn_note", n=1)}'


@pytest.mark.parametrize("n", [1, 3])
def test_warning_note_reads_right_for_one_and_many(n):
    from localscribe import i18n

    zh, en = (i18n.tr_in(lang, "convert_warn_note", n=n) for lang in ("zh_TW", "en"))
    assert str(n) in zh and str(n) in en
    assert " have " not in en and " has " not in en  # no verb that must agree with n


def test_a_new_run_resets_the_warning_count():
    import inspect

    from localscribe.ui import convert_dialog

    source = inspect.getsource(convert_dialog.ConvertDialog._start_or_cancel)
    assert 'self.counts = {"ok": 0, "bad": 0, "warn": 0}' in source


def test_stopped_rows_do_not_look_failed():
    import inspect

    from localscribe.ui import convert_dialog

    source = inspect.getsource(convert_dialog.ConvertDialog._on_stopped)
    assert "SP_MediaStop" in source and "Critical" not in source and "BrowserStop" not in source


def test_quit_prompt_talks_about_transcription():
    from localscribe import i18n

    zh, en = i18n.STRINGS["confirm_quit"]
    assert "轉錄" in zh and "transcription" in en.lower() and "conversion" not in en.lower()


# ---- C3: crashes ------------------------------------------------------------------
def test_crash_in_a_worker_thread_is_shown_on_the_gui_thread(monkeypatch):
    from localscribe.ui import app
    from PySide6.QtWidgets import QMessageBox

    shown, emitted = [], []
    monkeypatch.setattr(QMessageBox, "critical", lambda *a, **k: shown.append(threading.current_thread()))
    bridge = types.SimpleNamespace(error=types.SimpleNamespace(emit=emitted.append))
    monkeypatch.setattr(app, "_errors", bridge)
    monkeypatch.setattr(app.sys, "excepthook", app.sys.excepthook)
    monkeypatch.setattr(app.threading, "excepthook", app.threading.excepthook)
    app._install_error_hooks()

    def crash():
        raise ValueError("boom")

    t = threading.Thread(target=crash)
    t.start()
    t.join()
    assert shown == [] and len(emitted) == 1 and "boom" in emitted[0]


def test_unwritable_data_folder_does_not_stop_a_windowed_start(monkeypatch, tmp_path):
    from localscribe.ui import app

    blocker = tmp_path / "not_a_folder"
    blocker.write_text("")
    monkeypatch.setattr(app.paths, "user_data_dir", lambda: blocker)  # console.log can't be created
    monkeypatch.setattr(app.sys, "stdout", None)
    monkeypatch.setattr(app.sys, "stderr", None)
    enabled = []
    monkeypatch.setattr(app.faulthandler, "enable", lambda file=None, **k: enabled.append(file))
    app._redirect_missing_streams()
    assert app.sys.stdout is not None and app.sys.stderr is not None
    app.sys.stdout.write("library noise\n")


def test_native_crashes_are_logged_to_console_log(monkeypatch, tmp_path):
    from localscribe.ui import app

    monkeypatch.setattr(app.paths, "user_data_dir", lambda: tmp_path)
    monkeypatch.setattr(app.sys, "stdout", None)
    monkeypatch.setattr(app.sys, "stderr", None)
    enabled = []
    monkeypatch.setattr(app.faulthandler, "enable", lambda file=None, **k: enabled.append(file))
    app._redirect_missing_streams()
    assert enabled and Path(enabled[0].name) == tmp_path / "console.log"
    enabled[0].close()


# ---- C4: writing outputs ----------------------------------------------------------
def test_failed_export_leaves_no_partial_files(monkeypatch, tmp_path):
    from localscribe import export
    from localscribe.export.common import ExportOptions
    from test_export import make_transcript

    def disk_full(t, path, options):
        Path(path).write_text("half a transc")
        raise OSError(28, "No space left on device", str(path))

    monkeypatch.setitem(export.FORMATS, "txt", (".txt", disk_full))
    out = tmp_path / "out"
    with pytest.raises(UserError) as caught:
        export.write_outputs(make_transcript(), out, ["docx", "txt", "srt"], ExportOptions())
    assert caught.value.key == "err_write"
    assert list(out.iterdir()) == []


def test_export_still_never_overwrites(tmp_path):
    from localscribe import export
    from localscribe.export.common import ExportOptions
    from test_export import make_transcript

    first = export.write_outputs(make_transcript(), tmp_path, ["txt"], ExportOptions())
    second = export.write_outputs(make_transcript(), tmp_path, ["txt"], ExportOptions())
    assert [p.name for p in second] == ["interview_transcript (2).json", "interview_transcript (2).txt"]
    assert all(p.exists() for p in first + second)
    assert sorted(p.name for p in tmp_path.iterdir()) == sorted(p.name for p in first + second)


# ---- C5: --speakers -----------------------------------------------------------------
@pytest.mark.parametrize("text", ["2-", "-3", "3-1", "0", "two", "1-x"])
def test_bad_speaker_counts_are_rejected_clearly(text):
    from localscribe.cli import parse_speakers

    with pytest.raises(argparse.ArgumentTypeError):
        parse_speakers(text)


def test_cli_reports_a_bad_speaker_range_as_a_usage_error(capsys):
    from localscribe import cli

    with pytest.raises(SystemExit) as caught:
        cli.main(["talk.wav", "--speakers", "3-1"])
    assert caught.value.code == 2 and "--speakers" in capsys.readouterr().err


def test_good_speaker_counts():
    from localscribe.cli import parse_speakers
    from localscribe.core.diarization import SpeakerCount

    assert parse_speakers("auto") == SpeakerCount()
    assert parse_speakers("3") == SpeakerCount(exact=3)
    assert parse_speakers(" 2-6 ") == SpeakerCount(min=2, max=6)


# ---- C6: settings.json --------------------------------------------------------------
@pytest.mark.parametrize("content", ["[1, 2]", "{not json", '"text"'])
def test_corrupt_settings_are_backed_up_and_logged(tmp_path, caplog, content):
    from localscribe.config import Settings

    path = tmp_path / "settings.json"
    path.write_text(content, encoding="utf-8")
    with caplog.at_level(logging.WARNING, logger="localscribe"):
        s = Settings.load(path)
    assert s == Settings()
    assert (tmp_path / "settings.json.bad").read_text(encoding="utf-8") == content
    assert "settings" in caplog.text.lower()


def test_wrong_item_types_in_settings_are_dropped(tmp_path):
    from localscribe.config import Settings

    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"formats": ["docx", 5, {"a": 1}, "srt"], "speakers_exact": True,
                                "normalize": 1, "preset": "custom"}), encoding="utf-8")
    s = Settings.load(path)
    assert s.formats == ["docx", "srt"] and s.speakers_exact == 2 and s.normalize is False


def test_missing_settings_file_is_not_backed_up(tmp_path):
    from localscribe.config import Settings

    assert Settings.load(tmp_path / "settings.json") == Settings()
    assert list(tmp_path.iterdir()) == []


# ---- C7: duration probe -------------------------------------------------------------
def test_duration_probe_survives_a_failing_file(monkeypatch, caplog, tmp_path):
    from localscribe.ui import threads

    def probe(path):
        if path.name == "bad.wav":
            raise RuntimeError("ffmpeg missing")
        return 5.0

    monkeypatch.setattr(threads, "probe_duration", probe)
    worker = threads.DurationProbe([(1, tmp_path / "bad.wav"), (2, tmp_path / "good.wav")])
    found = []
    worker.found.connect(lambda job_id, seconds: found.append((job_id, seconds)))
    with caplog.at_level(logging.WARNING, logger="localscribe"):
        worker.run()
    assert found == [(2, 5.0)] and "bad.wav" in caplog.text


# ---- C8 -------------------------------------------------------------------------------
def test_typescript_files_are_not_media():
    from localscribe.core.media import MEDIA_EXTENSIONS

    assert ".ts" not in MEDIA_EXTENSIONS and ".mts" in MEDIA_EXTENSIONS


# ---- C9: make_zip -------------------------------------------------------------------
def load_make_zip():
    spec = importlib.util.spec_from_file_location("make_zip", ROOT / "packaging" / "make_zip.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # must not zip anything on import
    return module


def test_make_zip_uses_the_given_dist_folder(tmp_path):
    app_dir = tmp_path / "dist_build" / "LocalScribe"
    (app_dir / "_internal").mkdir(parents=True)
    (app_dir / "LocalScribe.exe").write_bytes(b"MZ")
    (app_dir / "_internal" / "base.dll").write_bytes(b"dll")
    target = load_make_zip().main([str(tmp_path / "dist_build")])
    assert target.parent == tmp_path / "dist_build"
    with zipfile.ZipFile(target) as zf:
        assert sorted(zf.namelist()) == ["LocalScribe/LocalScribe.exe", "LocalScribe/_internal/base.dll"]


def test_make_zip_refuses_a_folder_without_the_exe(tmp_path):
    (tmp_path / "LocalScribe").mkdir()
    with pytest.raises(SystemExit) as caught:
        load_make_zip().main([str(tmp_path)])
    assert "LocalScribe.exe" in str(caught.value.code)
    assert list(tmp_path.glob("*.zip")) == []


# ---- C10: model downloads -----------------------------------------------------------
class FakeResponse:
    def __init__(self, status: int, body: bytes = b""):
        self.status_code, self.body = status, body
        self.headers = {}

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} Error", response=self)

    def iter_content(self, chunk_size=1):
        yield self.body

    def json(self):
        return json.loads(self.body)


class FakeSession:
    def __init__(self, *statuses: int, body: bytes = b"model"):
        self.statuses, self.body, self.calls = list(statuses), body, 0

    def get(self, url, **kwargs):
        self.calls += 1
        status = self.statuses.pop(0) if self.statuses else 200
        return FakeResponse(status, self.body if status < 400 else b"")


@pytest.fixture
def no_delay(monkeypatch):
    monkeypatch.setattr(models, "_RETRY_DELAY_S", 0.0)


@pytest.mark.parametrize("status", [429, 500, 503])
def test_busy_servers_are_retried(monkeypatch, tmp_path, no_delay, status):
    session = FakeSession(status, status)
    monkeypatch.setattr(models, "_session", lambda token=None: session)
    dest = tmp_path / "model.bin"
    models.download_files([("https://example.test/model.bin", dest, 5)])
    assert dest.read_bytes() == b"model" and session.calls == 3


def test_missing_files_are_not_retried(monkeypatch, tmp_path, no_delay):
    session = FakeSession(404)
    monkeypatch.setattr(models, "_session", lambda token=None: session)
    with pytest.raises(UserError) as caught:
        models.download_files([("https://example.test/model.bin", tmp_path / "model.bin", 5)])
    assert caught.value.key == "err_network" and session.calls == 1


def test_cancel_interrupts_the_retry_wait(monkeypatch, tmp_path):
    monkeypatch.setattr(models, "_session", lambda token=None: FakeSession(*[503] * 10))
    cancel = threading.Event()
    threading.Timer(0.1, cancel.set).start()
    started = time.monotonic()
    with pytest.raises(Cancelled):
        models.download_files([("https://example.test/model.bin", tmp_path / "model.bin", 5)], cancel=cancel)
    assert time.monotonic() - started < 1.5


def test_disk_errors_become_a_write_error(monkeypatch, tmp_path, no_delay):
    monkeypatch.setattr(models, "_session", lambda token=None: FakeSession())
    (tmp_path / "model.bin.part").mkdir()  # can't be opened as a file
    with pytest.raises(UserError) as caught:
        models.download_files([("https://example.test/model.bin", tmp_path / "model.bin", 5)])
    assert caught.value.key == "err_write"


def test_listing_errors_become_a_network_error(monkeypatch):
    monkeypatch.setattr(models, "_session", lambda token=None: FakeSession(500))
    with pytest.raises(UserError) as caught:
        models.hf_list_files("org/repo")
    assert caught.value.key == "err_network"


def test_a_locked_destination_becomes_a_write_error(monkeypatch, tmp_path, no_delay):
    monkeypatch.setattr(models, "_session", lambda token=None: FakeSession())

    def locked(src, dst):
        raise PermissionError(13, "The file is in use", str(dst))

    monkeypatch.setattr(models.os, "replace", locked)
    with pytest.raises(UserError) as caught:
        models.download_files([("https://example.test/model.bin", tmp_path / "model.bin", 5)])
    assert caught.value.key == "err_write"
