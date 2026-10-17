"""Finds, downloads and starts LocalScribe updates from the GitHub releases.

Each release carries latest.json, written by packaging/release_assets.py:

    {"format": 1, "version": "0.1.5",
     "full": {"files": [{"name": "LocalScribe-Setup-0.1.5.exe", "size": ..., "sha256": "..."},
                        {"name": "LocalScribe-Setup-0.1.5-1.bin", ...}, ...],
              "install_size": ...},
     "update": {"from": ["0.1.4"], "files": [{"name": "LocalScribe-Update-0.1.5.exe", ...}],
                "install_size": ...}}

The update installer holds only the files that changed, so it fits just the versions in "from";
any other version gets the full installer. Names must be exactly the ones that release would
have, downloads always come from this repository's release of that version, and every file is
checked against its size and SHA-256 when it arrives and again just before it runs. Fields may be
added to format 1; a newer format still announces the release, with its page to download from.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import sys
import threading
from dataclasses import dataclass
from pathlib import Path

from .. import __version__, paths
from . import models
from .errors import UserError

log = logging.getLogger("localscribe")

REPO_URL = "https://github.com/alston001/localscribe"
LATEST_URL = f"{REPO_URL}/releases/latest/download/latest.json"
FORMAT = 1
CHECK_INTERVAL_S = 24 * 3600  # automatic checks: at most once a day
_SPARE_BYTES = 100_000_000  # left free on the disk after downloading and installing
_MAX_SIZE = 2**31  # GitHub release files are smaller than 2 GiB
_MAX_INSTALL = 2**40
_MAX_INFO_BYTES = 1_000_000  # latest.json itself is a few kB
_VERSION = re.compile(r"(\d{1,6})\.(\d{1,6})\.(\d{1,6})", re.ASCII)
_SHA256 = re.compile(r"[0-9a-f]{64}")


def parse_version(text) -> tuple[int, int, int] | None:
    match = _VERSION.fullmatch(text) if isinstance(text, str) else None
    return tuple(int(n) for n in match.groups()) if match else None


@dataclass(frozen=True)
class Asset:
    name: str
    size: int
    sha256: str


@dataclass(frozen=True)
class Release:
    version: str
    kind: str                 # "update": only the changed files; "full": the whole installer;
                              # "page": latest.json is in a newer format, so only its page is offered
    files: tuple[Asset, ...]  # files[0] is the installer to run; the others sit next to it
    install_size: int = 0     # what the installer writes, for the disk space check

    @property
    def size(self) -> int:
        return sum(a.size for a in self.files)

    @property
    def page(self) -> str:
        return f"{REPO_URL}/releases/tag/v{self.version}"

    def url(self, asset: Asset) -> str:
        return f"{REPO_URL}/releases/download/v{self.version}/{asset.name}"


def _invalid(what: str) -> UserError:
    return UserError("err_update_info", detail=what)


def _assets(items, names: list[str]) -> tuple[Asset, ...]:
    if not isinstance(items, list) or len(items) != len(names):
        raise _invalid("file list")
    assets = []
    for item, name in zip(items, names):
        if not isinstance(item, dict) or item.get("name") != name:
            raise _invalid(f"expected {name}")
        size, sha256 = item.get("size"), item.get("sha256")
        if type(size) is not int or not 0 < size < _MAX_SIZE:
            raise _invalid(f"size of {name}")
        if not isinstance(sha256, str) or not _SHA256.fullmatch(sha256.lower()):
            raise _invalid(f"SHA-256 of {name}")
        assets.append(Asset(name, size, sha256.lower()))
    return tuple(assets)


def _install_size(section: dict) -> int:
    size = section.get("install_size", 0)
    if type(size) is not int or not 0 <= size < _MAX_INSTALL:
        raise _invalid("install size")
    return size


def parse_latest(data, current: str) -> Release | None:
    """What to offer the installed `current` version, or None when the release isn't newer.
    Raises UserError("err_update_info") when latest.json is malformed."""
    fmt = data.get("format") if isinstance(data, dict) else None
    if type(fmt) is not int or fmt < FORMAT:
        raise _invalid("format")
    version = data.get("version")
    if parse_version(version) is None:
        raise _invalid("version")
    newer = parse_version(version) > (parse_version(current) or (0, 0, 0))
    if fmt > FORMAT:  # from tools newer than this LocalScribe: it can only point to the release
        return Release(version, "page", ()) if newer else None
    section = data.get("full")
    if not isinstance(section, dict) or not isinstance(section.get("files"), list) or not section["files"]:
        raise _invalid("full installer")
    names = [f"LocalScribe-Setup-{version}.exe"] + [f"LocalScribe-Setup-{version}-{n}.bin"
                                                    for n in range(1, len(section["files"]))]
    full = Release(version, "full", _assets(section["files"], names), _install_size(section))
    small, fits = None, []
    if "update" in data:
        section = data["update"]
        if not isinstance(section, dict):
            raise _invalid("update installer")
        fits = section.get("from")
        if not isinstance(fits, list) or any(parse_version(v) is None for v in fits):
            raise _invalid("versions the update installer fits")
        small = Release(version, "update", _assets(section.get("files"), [f"LocalScribe-Update-{version}.exe"]),
                        _install_size(section))
    if not newer:
        return None
    return small if small and current in fits else full


def installer_command(installer: Path, log: Path, wait_pid: int = 0) -> list[str]:
    """Installs over the installed copy with only a progress window, then starts LocalScribe
    again (/relaunch=1, see packaging/installer.iss and update.iss). With wait_pid, the installer
    first waits up to 30 s for that process, the LocalScribe that is quitting, to end. Message
    boxes stay on: an installer that can't install has to say so."""
    cmd = [str(installer), "/SILENT", "/NOCANCEL", "/NORESTART", "/CLOSEAPPLICATIONS", "/relaunch=1", f"/LOG={log}"]
    return cmd + [f"/waitpid={wait_pid}"] if wait_pid else cmd


def size_text(n: int) -> str:
    if n < 10_000_000:
        return f"{n / 1e6:.1f} MB"
    return f"{n / 1e6:.0f} MB" if n < 1_000_000_000 else f"{n / 1e9:.1f} GB"


def updates_dir() -> Path:
    """Downloaded installers, one folder per version, and what the last check found."""
    return paths.user_data_dir() / "updates"


def _elevated() -> bool:
    """Whether LocalScribe runs as administrator."""
    try:
        import ctypes

        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def install_mode() -> str:
    """"installed" by the installer, so updates install themselves. Otherwise the release page
    is offered: "portable" (unzipped), "elevated" (run as administrator, where the installer
    would run elevated too, with files any program of this user could have swapped), or
    "source", a checkout that updates through git."""
    if not paths.is_frozen():
        return "source"
    if not Path(sys.executable).with_name("unins000.exe").is_file():
        return "portable"
    return "elevated" if _elevated() else "installed"


def due(checked_at: int, now: float) -> bool:
    """Whether an automatic check should run. A clock set back counts as a day gone by."""
    return not 0 <= now - checked_at < CHECK_INTERVAL_S


def check(fetch: bool = True, current: str = __version__) -> Release | None:
    """The release to offer `current`. fetch=False reads what the last check found instead of
    asking GitHub. Raises UserError when GitHub can't be reached or has no usable latest.json."""
    found = updates_dir() / "latest.json"
    if not fetch:
        try:
            return parse_latest(json.loads(found.read_bytes()), current)
        except (OSError, ValueError, UserError):
            return None
    body = _fetch_latest()
    try:
        data = json.loads(body)
    except ValueError as exc:
        raise _invalid("not JSON") from exc
    release = parse_latest(data, current)
    try:
        found.parent.mkdir(parents=True, exist_ok=True)
        found.write_bytes(body)
    except OSError:
        log.warning("Could not keep the update information", exc_info=True)
    return release


def _fetch_latest() -> bytes:
    """latest.json, the root every SHA-256 comes from: over https on every hop, and small."""
    import requests

    try:
        resp = models._session().get(LATEST_URL, timeout=(5, 10), stream=True)
    except requests.RequestException as exc:
        raise UserError("err_network", detail=str(exc)) from exc
    try:
        hops = [r.url for r in resp.history] + [resp.url]
        if LATEST_URL.startswith("https://") and not all(url.startswith("https://") for url in hops):
            raise UserError("err_network", detail="redirected away from https")
        if resp.status_code == 404:  # the newest release was published without latest.json
            raise UserError("err_update_missing")
        if resp.status_code >= 400:
            raise UserError("err_network", detail=f"HTTP {resp.status_code}")
        body = b""
        for chunk in resp.iter_content(64 * 1024):
            body += chunk
            if len(body) > _MAX_INFO_BYTES:
                raise _invalid("too large")
        return body
    except requests.RequestException as exc:  # while the body arrives
        raise UserError("err_network", detail=str(exc)) from exc
    finally:
        resp.close()


def downloaded(release: Release) -> Path | None:
    """The installer to run once every file of the release is here, by size; download() checks
    their SHA-256 again before they run."""
    folder = updates_dir() / release.version
    try:
        for asset in release.files:
            path = folder / asset.name
            if not path.is_file() or path.stat().st_size != asset.size:
                return None
    except OSError:
        return None
    return folder / release.files[0].name if release.files else None


def _have(path: Path, size: int) -> int:
    """Bytes of a file already downloaded, complete or partial."""
    for candidate in (path, path.with_name(path.name + ".part")):
        if candidate.is_file():
            return min(candidate.stat().st_size, size)
    return 0


def download(release: Release, progress: models.ProgressFn | None = None,
             cancel: threading.Event | None = None) -> Path:
    """Downloads the release's installer files, resuming partial ones, and returns the one to
    run. Files already here are checked against their SHA-256 again (they may have sat on disk
    since an earlier session); downloads of other versions are removed first."""
    root = updates_dir()
    folder = root / release.version
    try:
        folder.mkdir(parents=True, exist_ok=True)
        for other in root.iterdir():
            if other.is_dir() and other != folder and parse_version(other.name):
                shutil.rmtree(other, ignore_errors=True)
        left = sum(a.size - _have(folder / a.name, a.size) for a in release.files)
        free = shutil.disk_usage(folder).free
    except OSError as exc:
        raise UserError("err_write", path=str(exc.filename or folder)) from exc
    need = left + release.install_size + _SPARE_BYTES
    if free < need:
        raise UserError("err_update_space", need=size_text(need), free=size_text(free))
    models.download_files([(release.url(a), folder / a.name, a.size, a.sha256) for a in release.files],
                          progress=progress, cancel=cancel, verify_existing=True)
    return folder / release.files[0].name


def start_installer(installer: Path) -> None:
    """Starts the installer on its own, so it keeps running once LocalScribe has quit, also out of
    a job that ends with LocalScribe where that job allows it. The LocalScribe it starts again
    inherits this environment; PyInstaller's reset variable makes it start fresh instead of as a
    child of this (frozen) process."""
    detached = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    breakaway = getattr(subprocess, "CREATE_BREAKAWAY_FROM_JOB", 0)
    cmd = installer_command(installer, installer.with_name("install.log"), wait_pid=os.getpid())
    env = {**os.environ, "PYINSTALLER_RESET_ENVIRONMENT": "1"}
    error: OSError | None = None
    for flags in (detached | breakaway, detached):
        try:
            subprocess.Popen(cmd, creationflags=flags, close_fds=True, cwd=installer.parent, env=env)
            return
        except OSError as exc:  # e.g. a job that doesn't allow breaking away: try without
            error = exc
    raise UserError("err_update_launch", detail=str(error)) from error


def clean_up(current: str = __version__) -> None:
    """Removes downloads that will never be installed: of the installed version or older, and of
    any version but the newest the last check found. A failed install keeps its folder, with
    install.log, while its version is still the newest."""
    root, installed = updates_dir(), parse_version(current)
    if not root.is_dir():
        return
    newest = check(fetch=False, current=current)
    for folder in root.iterdir():
        version = parse_version(folder.name)
        stale = version and (version <= installed or (newest is not None and folder.name != newest.version))
        if folder.is_dir() and stale:
            shutil.rmtree(folder, ignore_errors=True)  # an installer still finishing stays till next time
