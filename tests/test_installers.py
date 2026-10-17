"""The real installers, compiled from a tiny fake bundle and installed under a test name and AppId:
the full installer, the update installer over it, its refusal to install over a version it doesn't
fit, and LocalScribe's own update flow (offscreen window, local server, real download and restart).

Opt-in, because it installs a test copy into a temporary folder, adds a Start menu entry and an
uninstall entry for it (both removed at the end), and briefly shows the installer's progress window:

    set LOCALSCRIBE_INSTALLER_TESTS=1
    .venv\\Scripts\\python.exe -m pytest tests\\test_installers.py -q
"""

import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import types
from pathlib import Path

import pytest

from localscribe import __version__
from localscribe.core import update

ROOT = Path(__file__).resolve().parent.parent
ISCC = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Inno Setup 6" / "ISCC.exe"
REAL_GUID = "8F3C2A51-6E4B-4D7A-9C1E-2B5F7A9D0E13"
TEST_GUID = "5E1D7C2B-0A4F-4B8E-9D3C-6F2A1B0C9E87"
TEST_NAME = "LocalScribeInstallerTest"

pytestmark = pytest.mark.skipif(
    sys.platform != "win32" or os.environ.get("LOCALSCRIBE_INSTALLER_TESTS") != "1" or not ISCC.is_file(),
    reason="opt-in: set LOCALSCRIBE_INSTALLER_TESTS=1 (needs Inno Setup 6)")


def uninstall_entry(guid: str) -> dict | None:
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            rf"Software\Microsoft\Windows\CurrentVersion\Uninstall\{{{guid}}}_is1") as key:
            return {name: winreg.QueryValueEx(key, name)[0] for name in ("DisplayVersion", "Inno Setup: App Path")}
    except FileNotFoundError:
        return None


def wait_for_version(version: str, seconds: float = 60) -> dict | None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        entry = uninstall_entry(TEST_GUID)
        if entry and entry["DisplayVersion"] == version:
            return entry
        time.sleep(0.5)
    return uninstall_entry(TEST_GUID)


def run(cmd: list, timeout: float = 300) -> subprocess.CompletedProcess:
    """Runs and waits. An installer that hangs, e.g. on a message box, is ended with its own setup
    process (setup.exe starts a copy of itself from %TEMP%) instead of being left on the desktop."""
    proc = subprocess.Popen([str(c) for c in cmd], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        out, err = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], capture_output=True)
        proc.communicate()
        raise
    return subprocess.CompletedProcess(proc.args, proc.returncode, out, err)


def fake_bundle(folder: Path, files: dict[str, bytes]) -> Path:
    folder.mkdir(parents=True)
    # Something that starts and ends at once, for the installer's "start LocalScribe again".
    shutil.copyfile(Path(os.environ.get("WINDIR", r"C:\Windows")) / "System32" / "whoami.exe",
                    folder / "LocalScribe.exe")
    for rel, data in files.items():
        (folder / rel).parent.mkdir(parents=True, exist_ok=True)
        (folder / rel).write_bytes(data)
    return folder


def uninstall(app: Path) -> None:
    exe = app / "unins000.exe"
    if exe.is_file():
        run([exe, "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART"])
    # The uninstaller carries on from a copy of itself in %TEMP%, and removes unins000.exe last.
    deadline = time.monotonic() + 60
    while (uninstall_entry(TEST_GUID) is not None or exe.exists()) and time.monotonic() < deadline:
        time.sleep(0.5)


@pytest.fixture
def builds(tmp_path):
    """The test copy's full installer for 9.0.0 and its update installer to 9.0.1."""
    spec = importlib.util.spec_from_file_location("release_assets", ROOT / "packaging" / "release_assets.py")
    ra = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ra)
    if not (ROOT / "packaging" / "localscribe.ico").is_file():
        subprocess.run([sys.executable, str(ROOT / "packaging" / "make_icon.py")], check=True)
    assert TEST_GUID != REAL_GUID
    v1 = fake_bundle(tmp_path / "v1", {"_internal/keep.txt": b"same", "_internal/changed.txt": b"old",
                                       "_internal/gone.txt": b"bye"})
    v2 = fake_bundle(tmp_path / "v2", {"_internal/keep.txt": b"same", "_internal/changed.txt": b"new",
                                       "_internal/sub/added.txt": b"hi", "_internal/odd {dir}/x {y}.txt": b"brace"})
    out = tmp_path / "out dir"
    test_names = [f"/DAppName={TEST_NAME}", f"/DAppGuid={TEST_GUID}"]
    proc = run([ISCC, *test_names, "/DAppVersion=9.0.0", f"/DDistDir={v1}", f"/O{out}", "/FFull-9.0.0",
                ROOT / "packaging" / "installer.iss"])
    assert proc.returncode == 0, proc.stdout + proc.stderr
    plan = ra.plan_update(ra.file_list(v2), {"9.0.0": ra.file_list(v1)})
    assert plan.files == ["_internal/changed.txt", "_internal/odd {dir}/x {y}.txt", "_internal/sub/added.txt"]
    assert plan.deletes == ["_internal/gone.txt"] and plan.update_from == ["9.0.0"]
    include = tmp_path / "update-9.0.1.iss"
    include.write_text(ra.inno_include(plan, "9.0.1"), encoding="utf-8-sig", newline="")
    ra.compile_update(include, v2, out, ISCC, extra=tuple(test_names))
    assert (out / "LocalScribe-Update-9.0.1.exe").is_file()
    return types.SimpleNamespace(full=out / "Full-9.0.0.exe", small=out / "LocalScribe-Update-9.0.1.exe")


@pytest.fixture
def short_dir():
    """A folder for the test copy that keeps it under the installer's 110-character limit whatever
    pytest's own temporary folder is; with a space in it, as many user names have."""
    folder = Path(tempfile.mkdtemp(prefix="lsit "))
    yield folder
    shutil.rmtree(folder, ignore_errors=True)


@pytest.fixture
def installed(builds, short_dir, tmp_path):
    """Test copy 9.0.0 installed from the full installer, plus the update installer to 9.0.1."""
    real_before = uninstall_entry(REAL_GUID)
    assert uninstall_entry(TEST_GUID) is None, "a test copy is left over from an earlier run"
    app = short_dir / "app dir"
    assert len(str(app)) <= 100, f"{app} is too long for the installer; set TEMP to a shorter folder"
    try:
        proc = run([builds.full, "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", f"/DIR={app}",
                    "/MERGETASKS=!desktopicon", f"/LOG={tmp_path / 'full.log'}"], timeout=120)
        assert proc.returncode == 0
        assert uninstall_entry(TEST_GUID)["DisplayVersion"] == "9.0.0"
        assert (app / "_internal" / "gone.txt").read_bytes() == b"bye"
        yield types.SimpleNamespace(app=app, small=builds.small)
    finally:
        uninstall(app)
    assert uninstall_entry(TEST_GUID) is None
    # The uninstaller knows the files of both installers: nothing is left behind.
    assert not app.exists() or [p for p in app.rglob("*") if p.is_file()] == []
    assert uninstall_entry(REAL_GUID) == real_before  # the real installation was never touched


def test_a_folder_path_too_long_ends_a_silent_install_instead_of_waiting_for_ok(builds, short_dir):
    real_before = uninstall_entry(REAL_GUID)
    folder = short_dir / ("x" * 120)
    started = time.monotonic()
    proc = run([builds.full, "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", f"/DIR={folder}",
                "/MERGETASKS=!desktopicon"], timeout=60)
    assert proc.returncode != 0 and time.monotonic() - started < 30
    assert uninstall_entry(TEST_GUID) is None and not (folder / "LocalScribe.exe").exists()
    assert uninstall_entry(REAL_GUID) == real_before


def assert_updated(app: Path) -> None:
    assert (app / "_internal" / "changed.txt").read_bytes() == b"new"
    assert (app / "_internal" / "sub" / "added.txt").read_bytes() == b"hi"
    assert (app / "_internal" / "odd {dir}" / "x {y}.txt").read_bytes() == b"brace"
    assert (app / "_internal" / "keep.txt").read_bytes() == b"same"
    assert not (app / "_internal" / "gone.txt").exists()


RELAUNCH_LINE = "Starting the LocalScribe that is still installed"


def test_the_update_installer_updates_the_installed_copy_and_nothing_else(installed, tmp_path):
    app, small = installed.app, installed.small
    log = tmp_path / "update.log"
    # LocalScribe still quitting: the installer waits for that process before it replaces files.
    quitting = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(3)"])
    started = time.monotonic()
    proc = run(update.installer_command(small, log, wait_pid=quitting.pid))  # what LocalScribe starts
    waited = time.monotonic() - started
    quitting.wait()
    text = log.read_text(encoding="utf-8", errors="replace")
    assert proc.returncode == 0, text
    assert waited >= 2.5, waited
    assert_updated(app)
    entry = uninstall_entry(TEST_GUID)
    assert entry["DisplayVersion"] == "9.0.1" and Path(entry["Inno Setup: App Path"]) == app
    assert f"Filename: {app / 'LocalScribe.exe'}" in text  # LocalScribe was started again

    # 9.0.1 is installed now, and the update only fits 9.0.0: it refuses, changes nothing, and
    # starts the installed LocalScribe again, once, since LocalScribe quit for it.
    (app / "_internal" / "changed.txt").write_bytes(b"edited")
    refused = tmp_path / "refused.log"
    proc = run([small, "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/relaunch=1", f"/LOG={refused}"])
    assert proc.returncode != 0
    assert (app / "_internal" / "changed.txt").read_bytes() == b"edited"
    assert refused.read_text(encoding="utf-8", errors="replace").count(RELAUNCH_LINE) == 1


def test_an_update_that_fails_half_way_brings_back_the_old_copy_and_can_be_retried(installed, tmp_path):
    app, small = installed.app, installed.small
    (app / "_internal" / "sub").write_bytes(b"a file where the update needs a folder")
    log = tmp_path / "failed.log"
    proc = run([*update.installer_command(small, log), "/SUPPRESSMSGBOXES"], timeout=120)  # no one to click
    text = log.read_text(encoding="utf-8", errors="replace")
    assert proc.returncode != 0, text
    assert uninstall_entry(TEST_GUID)["DisplayVersion"] == "9.0.0"  # so the same update fits a retry
    assert text.count(RELAUNCH_LINE) == 1, text  # LocalScribe, which quit for it, is back
    print("after the failed update:", {rel: (app / rel).read_bytes() if (app / rel).exists() else None
                                       for rel in ("_internal/changed.txt", "_internal/gone.txt",
                                                   "_internal/keep.txt", "LocalScribe.exe")} | {"LocalScribe.exe": "…"})

    (app / "_internal" / "sub").unlink()
    proc = run(update.installer_command(small, tmp_path / "retry.log"))
    assert proc.returncode == 0
    assert uninstall_entry(TEST_GUID)["DisplayVersion"] == "9.0.1"
    assert_updated(app)


APP_SCRIPT = r'''
import functools, http.server, json, sys, threading
from pathlib import Path
data, site = Path(sys.argv[1]), Path(sys.argv[2])
from localscribe import paths
paths.user_data_dir = lambda: data
handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(site))
server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
threading.Thread(target=server.serve_forever, daemon=True).start()
from localscribe.core import update
update.REPO_URL = f"http://127.0.0.1:{server.server_port}"  # this repository's releases, served locally
update.LATEST_URL = f"{update.REPO_URL}/releases/latest/download/latest.json"
update.install_mode = lambda: "installed"
from PySide6.QtCore import QThread, QTimer, Signal
from PySide6.QtWidgets import QApplication
app = QApplication([])
from localscribe import i18n
from localscribe.config import Settings
from localscribe.ui import main_window


class NoProbe(QThread):
    ready = Signal(object)

    def run(self):
        pass


i18n.set_language("en")
main_window.DeviceProbe = NoProbe
window = main_window.MainWindow(Settings())
window.show()
steps = []


def drive():  # what a person does: click Update, then Restart now
    bar = window.update_bar
    phase = bar.phase() if bar.release else ""
    if phase == "available" and not steps:
        steps.append(bar.lbl_text.text())
        bar.btn_action.click()
    elif phase == "ready" and len(steps) == 1:
        steps.append(bar.lbl_text.text())
        bar.btn_action.click()
    elif phase == "failed":
        steps.append(bar.lbl_text.text())
        app.exit(3)


timer = QTimer()
timer.timeout.connect(drive)
timer.start(100)
QTimer.singleShot(60000, lambda: app.exit(2))
code = app.exec()
print(json.dumps({"steps": steps, "code": code}))
sys.exit(code)
'''


def test_localscribe_downloads_the_update_and_restarts_into_it(installed, tmp_path):
    def asset(path: Path) -> dict:
        return {"name": path.name, "size": path.stat().st_size, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}

    site, data = tmp_path / "site", tmp_path / "data dir"
    files = site / "releases" / "download" / "v9.0.1"
    files.mkdir(parents=True)
    data.mkdir()
    small = shutil.copy(installed.small, files)
    full = files / "LocalScribe-Setup-9.0.1.exe"
    full.write_bytes(b"not used: the update installer fits")
    info = {"format": 1, "version": "9.0.1", "full": {"files": [asset(full)], "install_size": 1000},
            "update": {"from": [__version__], "files": [asset(Path(small))], "install_size": 100}}
    (site / "releases" / "latest" / "download").mkdir(parents=True)
    (site / "releases" / "latest" / "download" / "latest.json").write_text(json.dumps(info), encoding="utf-8")

    env = {**os.environ, "QT_QPA_PLATFORM": "offscreen"}
    proc = subprocess.run([sys.executable, "-c", APP_SCRIPT, str(data), str(site)], cwd=ROOT, env=env,
                          capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    steps = json.loads(proc.stdout.strip().splitlines()[-1])["steps"]
    assert steps == ["LocalScribe 9.0.1 is available (" + update.size_text(Path(small).stat().st_size) + " download).",
                     "LocalScribe 9.0.1 is downloaded. Restart to install it."]
    # LocalScribe has quit and started the installer, which waited for it and then updated the copy.
    entry = wait_for_version("9.0.1")
    assert entry and entry["DisplayVersion"] == "9.0.1", entry
    assert_updated(installed.app)
    log = data / "updates" / "9.0.1" / "install.log"
    deadline = time.monotonic() + 30
    while f"Filename: {installed.app / 'LocalScribe.exe'}" not in log.read_text(encoding="utf-8", errors="replace"):
        assert time.monotonic() < deadline, "the installer did not start LocalScribe again"
        time.sleep(0.5)
    settings = json.loads((data / "settings.json").read_text(encoding="utf-8"))
    assert settings["update_checked_at"] > 0 and settings["last_version"] == __version__
