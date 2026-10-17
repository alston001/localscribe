"""Updates in the app: the check at start, the strip that offers the update, Settings, and the restart."""

import json
import os
import subprocess
import sys
import time
import types
from pathlib import Path

import pytest

from localscribe import __version__
from localscribe.core import update
from localscribe.core.errors import UserError
from test_update import latest

ROOT = Path(__file__).resolve().parent.parent


def test_update_settings_survive_a_restart(tmp_path):
    from localscribe.config import Settings

    s = Settings()
    assert (s.update_check, s.update_checked_at, s.last_version) == (True, 0, "")
    s.update_check, s.update_checked_at, s.last_version = False, 1_760_000_000, "0.1.3"
    s.save(tmp_path / "settings.json")
    again = Settings.load(tmp_path / "settings.json")
    assert (again.update_check, again.update_checked_at, again.last_version) == (False, 1_760_000_000, "0.1.3")


# ---- the check at start --------------------------------------------------------------
class FakeBar:
    def __init__(self, stops=True):
        self.stops, self.offered, self.stopped = stops, [], 0

    def offer(self, release, mode):
        self.offered.append((release, mode))

    def stop(self):
        self.stopped += 1
        return self.stops


class FakeCheck:
    made = []

    def __init__(self, fetch, parent=None):
        self.fetch, self.started = fetch, False
        self.done = types.SimpleNamespace(connect=lambda slot: setattr(self, "slot", slot))
        FakeCheck.made.append(self)

    def start(self):
        self.started = True


def startup_window(monkeypatch, mode="installed", **settings):
    from localscribe.config import Settings
    from localscribe.ui import main_window

    FakeCheck.made = []
    monkeypatch.setattr(main_window, "UpdateCheck", FakeCheck)
    monkeypatch.setattr(main_window.update, "install_mode", lambda: mode)
    monkeypatch.setattr(main_window.update, "clean_up", lambda: None)
    messages = []
    status = types.SimpleNamespace(showMessage=lambda text, ms=0: messages.append(text))
    window = types.SimpleNamespace(settings=Settings(**settings), update_bar=FakeBar(), _helpers=[],
                                   statusBar=lambda: status, _save_settings=lambda: None)
    window._keep = window._helpers.append
    window._on_update_checked = lambda *a: main_window.MainWindow._on_update_checked(window, *a)
    return main_window, window, messages


def test_an_installed_copy_checks_at_start_once_a_day(monkeypatch):
    main_window, window, _ = startup_window(monkeypatch, last_version=__version__)
    main_window.MainWindow._startup_update_check(window)
    check, = FakeCheck.made
    assert check.fetch is True and check.started
    assert window._helpers == []  # quitting never waits for a check: DNS can hang past any timeout
    main_window, window, _ = startup_window(monkeypatch, update_checked_at=int(time.time()))
    main_window.MainWindow._startup_update_check(window)
    assert FakeCheck.made[0].fetch is False  # checked today: what that check found, without the network


def test_an_update_check_runs_in_a_thread_that_never_holds_up_quitting(monkeypatch):
    from localscribe.ui import threads

    started = []
    monkeypatch.setattr(threads.threading, "Thread", lambda **kw: started.append(kw) or types.SimpleNamespace(
        start=lambda: None))
    threads.UpdateCheck(fetch=True).start()
    assert started[0]["daemon"] is True


@pytest.mark.parametrize("mode, switched_on", [("source", True), ("installed", False)])
def test_no_check_from_a_checkout_or_when_switched_off(monkeypatch, mode, switched_on):
    main_window, window, _ = startup_window(monkeypatch, mode=mode, update_check=switched_on)
    main_window.MainWindow._startup_update_check(window)
    assert FakeCheck.made == []


def test_the_first_start_of_a_new_version_says_so_once(monkeypatch):
    main_window, window, messages = startup_window(monkeypatch, last_version="0.0.1")
    main_window.MainWindow._startup_update_check(window)
    assert window.settings.last_version == __version__
    assert len(messages) == 1 and __version__ in messages[0]
    main_window.MainWindow._startup_update_check(window)
    assert len(messages) == 1


def test_a_found_release_is_offered_and_the_check_remembered(monkeypatch):
    main_window, window, _ = startup_window(monkeypatch)
    release = update.parse_latest(latest(), current="0.1.9")
    main_window.MainWindow._on_update_checked(window, release, "", True)
    assert window.update_bar.offered == [(release, "installed")] and window.settings.update_checked_at > 0


def test_a_failed_check_offers_nothing_and_tries_again_next_start(monkeypatch):
    main_window, window, _ = startup_window(monkeypatch)
    main_window.MainWindow._on_update_checked(window, None, "Network error: offline", True)
    assert window.update_bar.offered == [] and window.settings.update_checked_at == 0


# ---- restarting into the installer ---------------------------------------------------
class FakeEvent:
    result = None

    def ignore(self):
        self.result = "ignored"

    def accept(self):
        self.result = "accepted"


def closing_window(installer=None, bar=None):
    from PySide6.QtCore import QByteArray

    from localscribe.config import Settings

    saved = []
    window = types.SimpleNamespace(_proofreaders={}, worker=None, _helpers=[], _closing=False,
                                   _pending_installer=installer, update_bar=bar or FakeBar(), settings=Settings(),
                                   saveGeometry=lambda: QByteArray(b"geometry"), _save_settings=lambda: saved.append(1))
    return window, saved


def test_restart_to_update_quits_and_then_starts_the_installer(monkeypatch, tmp_path):
    from localscribe.ui import main_window

    started = []
    monkeypatch.setattr(main_window.update, "start_installer", started.append)
    installer = tmp_path / "LocalScribe-Update-0.2.0.exe"
    window, saved = closing_window(installer=installer)
    event = FakeEvent()
    main_window.MainWindow.closeEvent(window, event)
    assert event.result == "accepted" and saved and started == [installer]


def test_an_installer_that_cannot_start_keeps_localscribe_open(monkeypatch, tmp_path):
    from PySide6.QtWidgets import QMessageBox

    from localscribe.ui import main_window

    def refuse(path):
        raise UserError("err_update_launch", detail="blocked")

    told = []
    monkeypatch.setattr(main_window.update, "start_installer", refuse)
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: told.append(a[-1]))
    window, _ = closing_window(installer=tmp_path / "LocalScribe-Update-0.2.0.exe")
    event = FakeEvent()
    main_window.MainWindow.closeEvent(window, event)
    assert event.result == "ignored" and "blocked" in told[0]
    assert window._pending_installer is None  # closing again later is an ordinary close


def test_a_download_that_wont_stop_keeps_localscribe_open(monkeypatch, tmp_path):
    from PySide6.QtWidgets import QMessageBox

    from localscribe.ui import main_window

    started = []
    monkeypatch.setattr(main_window.update, "start_installer", started.append)
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    window, _ = closing_window(installer=tmp_path / "x.exe", bar=FakeBar(stops=False))
    event = FakeEvent()
    main_window.MainWindow.closeEvent(window, event)
    assert event.result == "ignored" and started == [] and window.update_bar.stopped == 1


def test_a_close_that_cannot_happen_leaves_the_download_running(monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    from localscribe.ui import main_window
    from test_stability import FakeThread

    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    window, _ = closing_window()
    window._helpers = [FakeThread()]  # e.g. the hardware probe still importing torch
    event = FakeEvent()
    main_window.MainWindow.closeEvent(window, event)
    assert event.result == "ignored" and window.update_bar.stopped == 0


def test_settings_keep_what_the_update_check_wrote_while_they_were_open(monkeypatch):
    from localscribe.config import Settings
    from localscribe.ui import main_window

    class Dialog:
        Accepted = 1

        def __init__(self, settings, bundled, parent, on_update_checked=None):
            self.settings = Settings(**{**vars(settings)})  # the copy taken when Settings opened
            parent.settings.update_checked_at, parent.settings.last_version = 1_760_000_000, "9.9.9"  # meanwhile

        def exec(self):
            return self.Accepted

    monkeypatch.setattr(main_window, "SettingsDialog", Dialog)
    window = types.SimpleNamespace(settings=Settings(), _save_settings=lambda: None, retranslate=lambda: None,
                                   _update_status_bar=lambda: None,
                                   engine=types.SimpleNamespace(update_settings=lambda s: None),
                                   _on_manual_update_check=lambda *a: None)
    main_window.MainWindow.open_settings(window)
    assert (window.settings.update_checked_at, window.settings.last_version) == (1_760_000_000, "9.9.9")


def test_no_restart_while_a_transcription_runs():
    from localscribe.ui import main_window

    closed = []
    window = types.SimpleNamespace(worker=object(), _pending_installer=None, close=lambda: closed.append(1))
    main_window.MainWindow._restart_to_update(window, Path("x.exe"))
    assert closed == [] and window._pending_installer is None


# ---- the settings dialog -------------------------------------------------------------
def checking_dialog():
    label = types.SimpleNamespace(text="")
    label.setText = lambda text: setattr(label, "text", text)
    return types.SimpleNamespace(check=object(), btn_check=types.SimpleNamespace(setEnabled=lambda on: None),
                                 lbl_update=label)


def test_a_manual_check_reports_what_it_found():
    from localscribe.ui import settings_dialog

    dialog = checking_dialog()
    release = update.parse_latest(latest(), current="0.1.9")
    settings_dialog.SettingsDialog._on_update_checked(dialog, release, "")
    assert "0.2.0" in dialog.lbl_update.text and dialog.check is None


def test_a_failed_manual_check_shows_why():
    from localscribe.ui import settings_dialog

    dialog = checking_dialog()
    settings_dialog.SettingsDialog._on_update_checked(dialog, None, "Network error: offline")
    assert dialog.lbl_update.text == "Network error: offline"


def test_a_manual_check_reaches_the_main_window_too(monkeypatch):
    # The main window offers the update and records the check, also when Settings closed first.
    from localscribe.ui import settings_dialog

    made = []

    class Check(FakeCheck):
        def __init__(self, fetch, parent=None):
            super().__init__(fetch, parent)
            self.slots = []
            self.done = types.SimpleNamespace(connect=self.slots.append)
            made.append(self)

    monkeypatch.setattr(settings_dialog, "UpdateCheck", Check)
    reported = []
    dialog = checking_dialog()
    dialog.check, dialog.on_update_checked = None, lambda *a: reported.append(a)
    dialog._on_update_checked = lambda *a: None
    dialog.parent = lambda: None
    settings_dialog.SettingsDialog._check_for_update(dialog)
    check, = made
    assert check.fetch is True and check.started and dialog.on_update_checked in check.slots


# ---- real widgets --------------------------------------------------------------------
SCRIPT = r'''
import json, sys
from pathlib import Path
from localscribe import paths
paths.user_data_dir = lambda: Path(sys.argv[1])
from PySide6.QtCore import QPoint, QThread, Signal
from PySide6.QtWidgets import QApplication
app = QApplication([])
from localscribe import i18n
from localscribe.config import Settings
from localscribe.core import update
from localscribe.ui import main_window
from localscribe.ui.settings_dialog import SettingsDialog
from localscribe.ui.update_bar import UpdateBar


class NoProbe(QThread):
    ready = Signal(object)

    def run(self):
        pass


i18n.set_language("en")
main_window.DeviceProbe = NoProbe
release = update.Release("9.9.9", "update", (update.Asset("LocalScribe-Update-9.9.9.exe", 75_000_000, "ab" * 32),))
out = {}
bar = UpdateBar()
bar.offer(release, "installed")
out["available"] = [bar.lbl_text.text(), bar.btn_action.text(), bar.btn_action.isHidden()]
bar.installer = Path("x.exe")
bar.set_busy(True)
out["ready_busy"] = [bar.lbl_text.text(), bar.btn_action.text(), bar.btn_action.isEnabled()]
bar.set_busy(False)
out["ready"] = bar.btn_action.isEnabled()
bar.offer(release, "portable")
out["portable"] = [bar.lbl_text.text(), bar.btn_action.text(), bar.btn_notes.isHidden()]

window = main_window.MainWindow(Settings())
window.resize(1180, 760)
window.show()
app.processEvents()
out["hidden_at_start"] = window.update_bar.isHidden()
window.update_bar.offer(release, "installed")
app.processEvents()
top_left = lambda w: w.mapTo(window, QPoint(0, 0))
out["above_the_list"] = top_left(window.update_bar).y() + window.update_bar.height() <= top_left(window.view).y()
out["left_column"] = top_left(window.update_bar).x() + window.update_bar.width() < top_left(window.btn_start).x()

dialog = SettingsDialog(Settings(), [], window)
out["switch"] = dialog.chk_updates.isChecked()
dialog.chk_updates.setChecked(False)
dialog.accept()
out["saved"] = dialog.settings.update_check


def wait_until(condition, seconds=10):
    import time
    deadline = time.monotonic() + seconds
    while not condition() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.01)


# "Restart now" checks every file again first (it may have sat on disk for days), then restarts.
checked, restarts = [], []
update.download = lambda release, progress=None, cancel=None: checked.append(release.version) or Path("ok.exe")
bar2 = UpdateBar()
bar2.restart_requested.connect(restarts.append)
bar2.offer(release, "installed")
bar2.installer = Path("x.exe")  # downloaded in an earlier session
bar2.retranslate()
bar2.btn_action.click()
out["verifying"] = bar2.lbl_text.text()
wait_until(lambda: restarts)
out["restart"] = [checked, [str(p) for p in restarts]]

# A newer release found during a download waits for it, then takes over.
newer = update.Release("9.9.10", "update", (update.Asset("LocalScribe-Update-9.9.10.exe", 70_000_000, "cd" * 32),))
bar3 = UpdateBar()
bar3.offer(release, "installed")
bar3.worker = object()  # downloading
bar3.offer(newer, "installed")
out["pending_kept"] = bar3.release.version
bar3._on_done(Path("old.exe"), "")
out["pending_now"] = [bar3.release.version, bar3.phase()]

# latest.json in a format this version doesn't know: the release page.
bar4 = UpdateBar()
bar4.offer(update.Release("10.0.0", "page", ()), "installed")
out["page"] = [bar4.phase(), bar4.lbl_text.text(), bar4.btn_action.text()]
for thread in list(window._helpers):
    thread.wait()
print(json.dumps(out))
'''


def test_the_update_strip_and_the_settings_switch_in_real_widgets(tmp_path):
    # Real Qt widgets, offscreen, in their own process so no QApplication leaks into other tests.
    env = {**os.environ, "QT_QPA_PLATFORM": "offscreen"}
    proc = subprocess.run([sys.executable, "-c", SCRIPT, str(tmp_path)], cwd=ROOT, env=env,
                          capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr
    out = json.loads(proc.stdout.strip().splitlines()[-1])
    assert out["available"] == ["LocalScribe 9.9.9 is available (75 MB download).", "Update", False]
    assert out["ready_busy"][1] == "Restart now" and out["ready_busy"][2] is False  # not mid-transcription
    assert "9.9.9" in out["ready_busy"][0] and out["ready"] is True
    assert out["portable"] == ["LocalScribe 9.9.9 is available.", "Download page", True]
    assert out["hidden_at_start"] and out["above_the_list"] and out["left_column"]
    assert out["switch"] is True and out["saved"] is False
    assert out["verifying"] == "Checking LocalScribe 9.9.9 before installing…"
    assert out["restart"] == [["9.9.9"], ["ok.exe"]]
    assert out["pending_kept"] == "9.9.9" and out["pending_now"] == ["9.9.10", "available"]
    assert out["page"] == ["manual", "LocalScribe 10.0.0 is available.", "Download page"]
