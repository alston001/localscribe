"""Updates: finding a newer release, picking the small update installer, downloading and starting it."""

import hashlib
import json
import os
import subprocess
import types

import pytest
import requests

from localscribe.core import models, update
from localscribe.core.errors import UserError

SHA = "ab" * 32


def asset(name, size=10, sha=SHA):
    return {"name": name, "size": size, "sha256": sha}


def full(*files, **extra):
    return {"files": list(files), **extra}


def latest(version="0.2.0", update_from=("0.1.9",), **changes):
    data = {"format": 1, "version": version,
            "full": full(asset(f"LocalScribe-Setup-{version}.exe", 3), asset(f"LocalScribe-Setup-{version}-1.bin", 2000),
                         asset(f"LocalScribe-Setup-{version}-2.bin", 900), install_size=5000),
            "update": {"from": list(update_from), "files": [asset(f"LocalScribe-Update-{version}.exe", 75)],
                       "install_size": 80}}
    data.update(changes)
    return data


# ---- versions ------------------------------------------------------------------------
@pytest.mark.parametrize("text, expected", [("0.1.3", (0, 1, 3)), ("0.1.10", (0, 1, 10)), ("1.0.0", (1, 0, 0)),
                                            ("0.1", None), ("0.1.3b1", None), ("v0.1.3", None), (" 0.1.3", None),
                                            ("", None), (13, None), (None, None)])
def test_versions_are_three_numbers(text, expected):
    assert update.parse_version(text) == expected


@pytest.mark.parametrize("text", ["０.１.３", "٠.١.٣", "1234567.0.0", "1" * 5000 + ".0.0"])
def test_versions_take_plain_short_numbers_only(text):
    assert update.parse_version(text) is None  # fullwidth or Arabic-Indic digits, or absurdly long


def test_versions_compare_as_numbers():
    assert update.parse_version("0.1.10") > update.parse_version("0.1.9")


# ---- latest.json ---------------------------------------------------------------------
def test_a_listed_version_gets_the_small_update_installer():
    release = update.parse_latest(latest(), current="0.1.9")
    assert release.version == "0.2.0" and release.kind == "update"
    assert [a.name for a in release.files] == ["LocalScribe-Update-0.2.0.exe"]
    assert release.size == 75 and release.install_size == 80


def test_other_versions_get_the_full_installer_with_its_slices():
    release = update.parse_latest(latest(), current="0.1.8")
    assert release.kind == "full"
    assert [a.name for a in release.files] == ["LocalScribe-Setup-0.2.0.exe", "LocalScribe-Setup-0.2.0-1.bin",
                                               "LocalScribe-Setup-0.2.0-2.bin"]
    assert release.size == 2903 and release.install_size == 5000


def test_the_install_size_may_be_left_out():
    data = latest(full=full(asset("LocalScribe-Setup-0.2.0.exe")))
    assert update.parse_latest(data, current="0.1.8").install_size == 0


def test_a_release_without_an_update_installer_offers_the_full_one():
    data = latest()
    del data["update"]
    assert update.parse_latest(data, current="0.1.9").kind == "full"


@pytest.mark.parametrize("version", ["0.1.9", "0.1.8"])
def test_nothing_is_offered_unless_the_release_is_newer(version):
    assert update.parse_latest(latest(version=version, update_from=()), current="0.1.9") is None


def test_downloads_come_from_this_repository_only():
    release = update.parse_latest(latest(), current="0.1.9")
    assert release.url(release.files[0]) == ("https://github.com/alston001/localscribe/releases/download/"
                                             "v0.2.0/LocalScribe-Update-0.2.0.exe")
    assert release.page == "https://github.com/alston001/localscribe/releases/tag/v0.2.0"


def test_a_newer_format_still_points_to_the_release_page():
    # If latest.json ever changes shape, the versions out there must not stop hearing about updates.
    release = update.parse_latest({"format": 2, "version": "0.3.0", "whatever": "comes next"}, current="0.1.9")
    assert release.kind == "page" and release.files == () and release.page.endswith("/tag/v0.3.0")
    assert update.parse_latest({"format": 2, "version": "0.1.9"}, current="0.1.9") is None
    with pytest.raises(UserError):
        update.parse_latest({"format": 2, "version": "next"}, current="0.1.9")


@pytest.mark.parametrize("change", [
    {"format": 0},
    {"format": "1"},
    {"format": True},
    {"format": None},
    {"version": "0.2"},
    {"version": None},
    {"full": [asset("LocalScribe-Setup-0.2.0.exe")]},  # a list, not an object
    {"full": full()},
    {"full": full(asset("../LocalScribe-Setup-0.2.0.exe"))},
    {"full": full(asset("LocalScribe-Setup-0.2.0.exe", size=0))},
    {"full": full(asset("LocalScribe-Setup-0.2.0.exe", size=True))},
    {"full": full(asset("LocalScribe-Setup-0.2.0.exe", size=2**31))},  # GitHub takes files below 2 GiB
    {"full": full(asset("LocalScribe-Setup-0.2.0.exe", sha="xyz"))},
    {"full": full(asset("LocalScribe-Setup-0.2.0.exe", sha=None))},
    {"full": full(asset("LocalScribe-Setup-0.1.0.exe"))},  # another version's installer
    {"full": full(asset("LocalScribe-Setup-0.2.0-1.bin"))},  # a slice is not an installer
    {"full": full(asset("LocalScribe-Setup-0.2.0.exe"), asset("LocalScribe-Setup-0.2.0-2.bin"))},  # no slice 1
    {"full": full(asset("evil.exe"))},
    {"full": full("LocalScribe-Setup-0.2.0.exe")},
    {"full": full(asset("LocalScribe-Setup-0.2.0.exe"), install_size=-1)},
    {"full": full(asset("LocalScribe-Setup-0.2.0.exe"), install_size="5 GB")},
    {"update": {"from": ["0.1.9"], "files": [asset("LocalScribe-Setup-0.2.0.exe")]}},
    {"update": {"from": ["0.1.9"], "files": []}},
    {"update": {"from": "0.1.9", "files": [asset("LocalScribe-Update-0.2.0.exe")]}},
    {"update": {"from": ["latest"], "files": [asset("LocalScribe-Update-0.2.0.exe")]}},
    {"update": {"from": ["0.1.9"], "files": [asset("LocalScribe-Update-0.2.0.exe")], "install_size": True}},
    {"update": ["0.1.9"]},
])
def test_malformed_release_info_is_refused(change):
    with pytest.raises(UserError) as caught:
        update.parse_latest(latest(**change), current="0.1.9")
    assert caught.value.key == "err_update_info"


@pytest.mark.parametrize("data", [["0.2.0"], "0.2.0", None, {}])
def test_release_info_must_be_an_object_with_a_version(data):
    with pytest.raises(UserError) as caught:
        update.parse_latest(data, current="0.1.9")
    assert caught.value.key == "err_update_info"


def test_names_and_hashes_must_match_exactly():
    upper = latest(full=full(asset("LocalScribe-Setup-0.2.0.exe", sha="AB" * 32)))
    assert update.parse_latest(upper, current="0.1.8").files[0].sha256 == SHA  # compared in lower case
    with pytest.raises(UserError):
        update.parse_latest(latest(full=full(asset("localscribe-setup-0.2.0.exe"))), current="0.1.8")


# ---- checking ------------------------------------------------------------------------
class Response:
    def __init__(self, status=200, body=b"", url=update.LATEST_URL, history=()):
        self.status_code, self.body, self.url, self.history = status, body, url, list(history)
        self.closed = False

    def iter_content(self, chunk_size=1):
        for start in range(0, len(self.body), chunk_size):
            yield self.body[start:start + chunk_size]

    def close(self):
        self.closed = True


class Session:
    """Answers every GET with one response, and records what was asked."""

    def __init__(self, error=None, **response):
        self.error, self.response, self.calls = error, Response(**response), []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if self.error:
            raise self.error
        return self.response


def serve(monkeypatch, **kwargs) -> Session:
    session = Session(**kwargs)
    monkeypatch.setattr(models, "_session", lambda token=None: session)
    return session


@pytest.fixture
def folder(monkeypatch, tmp_path):
    monkeypatch.setattr(update, "updates_dir", lambda: tmp_path)
    return tmp_path


def test_a_check_finds_the_release_and_remembers_it(monkeypatch, folder):
    session = serve(monkeypatch, body=json.dumps(latest()).encode())
    release = update.check(fetch=True, current="0.1.9")
    assert release.version == "0.2.0" and release.kind == "update"
    assert session.calls[0][0] == update.LATEST_URL and session.response.closed
    serve(monkeypatch, error=AssertionError("no network without fetch"))
    assert update.check(fetch=False, current="0.1.9") == release  # what the last check found
    assert update.check(fetch=False, current="0.2.0") is None  # installed meanwhile


def test_a_release_without_latest_json_is_reported_and_the_last_find_kept(monkeypatch, folder):
    (folder / "latest.json").write_text(json.dumps(latest()), encoding="utf-8")  # an earlier check's find
    serve(monkeypatch, status=404)
    with pytest.raises(UserError) as caught:  # not "you have the latest version": nobody knows
        update.check(fetch=True, current="0.1.9")
    assert caught.value.key == "err_update_missing"
    assert update.check(fetch=False, current="0.1.9").version == "0.2.0"


@pytest.mark.parametrize("kwargs, key", [
    ({"status": 500}, "err_network"),
    ({"error": requests.ConnectionError("offline")}, "err_network"),
    ({"body": b"<html>"}, "err_update_info"),
    ({"body": json.dumps(latest(format=0)).encode()}, "err_update_info"),
    ({"body": b" " * 1_000_001}, "err_update_info"),  # latest.json is a few kB
    ({"body": json.dumps(latest()).encode(), "url": "http://cdn.example/latest.json",
      "history": [types.SimpleNamespace(url=update.LATEST_URL)]}, "err_network"),  # left https on the way
])
def test_failed_checks_are_reported_and_not_remembered(monkeypatch, folder, kwargs, key):
    serve(monkeypatch, **kwargs)
    with pytest.raises(UserError) as caught:
        update.check(fetch=True, current="0.1.9")
    assert caught.value.key == key
    assert not (folder / "latest.json").exists()


@pytest.mark.parametrize("content", [None, b"\x00garbage", json.dumps(latest(format=0)).encode()])
def test_without_a_readable_earlier_check_nothing_is_offered(folder, content):
    if content is not None:
        (folder / "latest.json").write_bytes(content)
    assert update.check(fetch=False, current="0.1.9") is None


@pytest.mark.parametrize("checked_at, now, expected", [(0, 1e9, True), (1e9, 1e9 + 3600, False),
                                                       (1e9, 1e9 + 86400, True), (1e9 + 50, 1e9, True)])
def test_automatic_checks_run_at_most_once_a_day(checked_at, now, expected):
    assert update.due(int(checked_at), now) is expected  # a clock set back counts as a day gone by


# ---- where LocalScribe runs from -----------------------------------------------------
def test_only_an_installed_copy_installs_updates(monkeypatch, tmp_path):
    monkeypatch.setattr(update.paths, "is_frozen", lambda: False)
    assert update.install_mode() == "source"
    monkeypatch.setattr(update.paths, "is_frozen", lambda: True)
    monkeypatch.setattr(update, "_elevated", lambda: False)
    monkeypatch.setattr(update.sys, "executable", str(tmp_path / "LocalScribe.exe"))
    assert update.install_mode() == "portable"  # unzipped: the download page instead
    (tmp_path / "unins000.exe").write_bytes(b"MZ")
    assert update.install_mode() == "installed"
    # Run as administrator, the installer would run elevated too, with files any program of this
    # user could have swapped in the meantime: the download page instead.
    monkeypatch.setattr(update, "_elevated", lambda: True)
    assert update.install_mode() == "elevated"


# ---- downloading ---------------------------------------------------------------------
def fake_downloads(monkeypatch):
    jobs, options = [], {}

    def download_files(batch, token=None, progress=None, cancel=None, verify_existing=False):
        options["verify_existing"] = verify_existing
        for url, dest, size, sha256 in batch:
            jobs.append((url, dest, size, sha256))
            dest.write_bytes(b"x" * size)

    monkeypatch.setattr(models, "download_files", download_files)
    return jobs, options


def test_the_download_fetches_every_file_with_its_size_and_hash(monkeypatch, folder):
    jobs, options = fake_downloads(monkeypatch)
    release = update.parse_latest(latest(), current="0.1.8")  # the full installer: exe and two slices
    installer = update.download(release)
    assert installer == folder / "0.2.0" / "LocalScribe-Setup-0.2.0.exe"
    assert jobs == [(release.url(a), folder / "0.2.0" / a.name, a.size, a.sha256) for a in release.files]
    assert options["verify_existing"] is True  # files kept from an earlier session are checked again
    assert update.downloaded(release) == installer


def test_only_a_complete_download_counts(folder):
    release = update.parse_latest(latest(), current="0.1.9")
    assert update.downloaded(release) is None
    (folder / "0.2.0").mkdir()
    (folder / "0.2.0" / "LocalScribe-Update-0.2.0.exe").write_bytes(b"short")
    assert update.downloaded(release) is None


def test_an_unreadable_download_folder_counts_as_no_download(monkeypatch, folder):
    def locked(self, *args, **kwargs):
        raise PermissionError(13, "Access is denied")

    monkeypatch.setattr(update.Path, "stat", locked)
    assert update.downloaded(update.parse_latest(latest(), current="0.1.9")) is None


def test_a_new_download_replaces_older_ones(monkeypatch, folder):
    fake_downloads(monkeypatch)
    (folder / "0.1.9").mkdir()
    (folder / "0.1.9" / "LocalScribe-Update-0.1.9.exe.part").write_bytes(b"half")
    update.download(update.parse_latest(latest(), current="0.1.9"))
    assert sorted(p.name for p in folder.iterdir()) == ["0.2.0"]


@pytest.mark.parametrize("free", [1000, 2903 + 100_000_000])  # less than the download / than download + install
def test_a_full_disk_is_reported_before_downloading(monkeypatch, folder, free):
    jobs, _ = fake_downloads(monkeypatch)
    monkeypatch.setattr(update.shutil, "disk_usage", lambda path: types.SimpleNamespace(free=free))
    with pytest.raises(UserError) as caught:
        update.download(update.parse_latest(latest(), current="0.1.8"))
    assert caught.value.key == "err_update_space" and jobs == []


def test_files_kept_from_an_earlier_session_are_checked_again(monkeypatch, tmp_path):
    from test_stability import FakeSession

    session = FakeSession(body=b"model")
    monkeypatch.setattr(models, "_session", lambda token=None: session)
    dest = tmp_path / "LocalScribe-Update-0.2.0.exe"
    dest.write_bytes(b"MODEL")  # the right size, other bytes
    job = ("https://example.test/u.exe", dest, 5, hashlib.sha256(b"model").hexdigest())
    models.download_files([job])
    assert dest.read_bytes() == b"MODEL" and session.calls == 0  # model downloads trust a finished file
    models.download_files([job], verify_existing=True)
    assert dest.read_bytes() == b"model" and session.calls == 1
    models.download_files([job], verify_existing=True)
    assert session.calls == 1  # a file that checks out is not downloaded again


@pytest.mark.parametrize("status", [401, 403])
def test_a_refused_release_download_is_not_blamed_on_hugging_face(monkeypatch, tmp_path, status):
    from test_stability import FakeSession

    monkeypatch.setattr(models, "_session", lambda token=None: FakeSession(status))
    with pytest.raises(UserError) as caught:  # e.g. a proxy refusing GitHub
        models.download_files([("https://github.com/x/releases/download/v1/a.exe", tmp_path / "a.exe", 5)])
    assert caught.value.key == "err_network"
    with pytest.raises(UserError) as caught:  # with a Hugging Face token it is about the token or the terms
        models.download_files([("https://huggingface.co/x/resolve/main/a", tmp_path / "a", 5)], token="hf_x")
    assert caught.value.key in ("err_hf_token_invalid", "err_hf_terms")


# ---- installing ----------------------------------------------------------------------
def test_the_installer_shows_progress_only_and_starts_localscribe_again(tmp_path):
    installer, log = tmp_path / "LocalScribe-Update-0.2.0.exe", tmp_path / "install.log"
    cmd = update.installer_command(installer, log, wait_pid=4321)
    assert cmd[0] == str(installer) and f"/LOG={log}" in cmd
    assert {"/SILENT", "/NOCANCEL", "/NORESTART", "/CLOSEAPPLICATIONS", "/relaunch=1"} <= set(cmd)
    assert "/waitpid=4321" in cmd  # it waits until LocalScribe has really quit
    assert "/SUPPRESSMSGBOXES" not in cmd  # an installer that can't install has to say so
    assert not any(arg.startswith("/waitpid") for arg in update.installer_command(installer, log))


def test_the_installer_runs_on_its_own_and_logs_next_to_itself(monkeypatch, tmp_path):
    started = []
    monkeypatch.setattr(update.subprocess, "Popen", lambda cmd, **kwargs: started.append((cmd, kwargs)))
    installer = tmp_path / "LocalScribe-Update-0.2.0.exe"
    update.start_installer(installer)
    (cmd, kwargs), = started
    assert cmd == update.installer_command(installer, tmp_path / "install.log", wait_pid=os.getpid())
    assert kwargs["creationflags"] & subprocess.DETACHED_PROCESS  # it outlives LocalScribe
    assert kwargs["creationflags"] & subprocess.CREATE_BREAKAWAY_FROM_JOB  # also when LocalScribe's job ends
    assert kwargs["close_fds"] is True and kwargs["cwd"] == tmp_path
    # The LocalScribe it starts again must not inherit this frozen process's bootloader state.
    assert kwargs["env"]["PYINSTALLER_RESET_ENVIRONMENT"] == "1"
    assert kwargs["env"]["PATH"] == os.environ["PATH"]


def test_a_job_that_forbids_breaking_away_still_gets_the_installer(monkeypatch, tmp_path):
    started = []

    def popen(cmd, creationflags=0, **kwargs):
        if creationflags & subprocess.CREATE_BREAKAWAY_FROM_JOB:
            raise PermissionError(5, "Access is denied")
        started.append(creationflags)

    monkeypatch.setattr(update.subprocess, "Popen", popen)
    update.start_installer(tmp_path / "LocalScribe-Update-0.2.0.exe")
    assert len(started) == 1 and started[0] & subprocess.DETACHED_PROCESS


def test_an_installer_that_cannot_start_is_reported(monkeypatch, tmp_path):
    def refuse(cmd, **kwargs):
        raise OSError(193, "%1 is not a valid Win32 application")

    monkeypatch.setattr(update.subprocess, "Popen", refuse)
    with pytest.raises(UserError) as caught:
        update.start_installer(tmp_path / "LocalScribe-Update-0.2.0.exe")
    assert caught.value.key == "err_update_launch"


def test_only_the_newest_release_keeps_its_download(folder):
    for name in ("0.1.8", "0.1.9", "0.2.0", "0.3.0", "notes"):
        (folder / name).mkdir()
    (folder / "latest.json").write_text(json.dumps(latest(version="0.3.0")), encoding="utf-8")
    update.clean_up(current="0.1.9")
    # 0.2.0 was downloaded before 0.3.0 came out: it would never be installed
    assert sorted(p.name for p in folder.iterdir()) == ["0.3.0", "latest.json", "notes"]


def test_without_a_known_release_downloads_of_installed_versions_go(folder):
    for name in ("0.1.8", "0.1.9", "0.2.0"):
        (folder / name).mkdir()
    update.clean_up(current="0.1.9")
    assert sorted(p.name for p in folder.iterdir()) == ["0.2.0"]


@pytest.mark.parametrize("n, text", [(75_000_000, "75 MB"), (2_805_000_000, "2.8 GB"), (500_000, "0.5 MB")])
def test_sizes_read_naturally(n, text):
    assert update.size_text(n) == text
