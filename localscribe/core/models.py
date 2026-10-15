"""Model registry and resumable downloads with progress reporting.

All models live under one folder so it can be copied to offline machines:

    models/
      whisper/<name>/model.bin ...                      (faster-whisper, CTranslate2 format)
      sherpa-onnx/sherpa-onnx-pyannote-segmentation-3-0/model.onnx
      sherpa-onnx/nemo_en_titanet_large.onnx
      pyannote/speaker-diarization-community-1/config.yaml ...
"""

from __future__ import annotations

import hashlib
import os
import tarfile
import threading
import time
from pathlib import Path
from typing import Callable, Iterable, NamedTuple
from urllib.parse import quote

from .. import __version__
from .errors import Cancelled, UserError

ProgressFn = Callable[[int, int], None]  # (done_bytes, total_bytes); total 0 = unknown

HF_ENDPOINT = os.environ.get("HF_ENDPOINT", "https://huggingface.co").rstrip("/")

WHISPER_REPOS = {
    "large-v3": "Systran/faster-whisper-large-v3",
    "large-v3-turbo": "mobiuslabsgmbh/faster-whisper-large-v3-turbo",
    "medium": "Systran/faster-whisper-medium",
    "small": "Systran/faster-whisper-small",
    "base": "Systran/faster-whisper-base",
    "medium.en": "Systran/faster-whisper-medium.en",
    "small.en": "Systran/faster-whisper-small.en",
    "base.en": "Systran/faster-whisper-base.en",
}
# Approximate download sizes, shown in the settings dialog.
WHISPER_SIZES_MB = {
    "large-v3": 3100, "large-v3-turbo": 1600, "medium": 1500, "small": 480, "base": 150,
    "medium.en": 1500, "small.en": 480, "base.en": 150,
}
_WHISPER_FILES = ("config.json", "preprocessor_config.json", "tokenizer.json",
                  "vocabulary.json", "vocabulary.txt", "model.bin")  # model.bin last: marks completion

PYANNOTE_REPO = "pyannote/speaker-diarization-community-1"
PYANNOTE_PAGE = f"https://huggingface.co/{PYANNOTE_REPO}"
PYANNOTE_DIR = "pyannote/speaker-diarization-community-1"

_SHERPA_BASE = "https://github.com/k2-fsa/sherpa-onnx/releases/download"
SHERPA_SEG_URL = f"{_SHERPA_BASE}/speaker-segmentation-models/sherpa-onnx-pyannote-segmentation-3-0.tar.bz2"
# NVIDIA TitaNet-large: kept speaker counts right across the widest threshold range in tests.
SHERPA_EMB_URL = f"{_SHERPA_BASE}/speaker-recongition-models/nemo_en_titanet_large.onnx"
SHERPA_SEG = "sherpa-onnx/sherpa-onnx-pyannote-segmentation-3-0/model.onnx"
SHERPA_EMB = "sherpa-onnx/nemo_en_titanet_large.onnx"

_truststore_done = False
_ATTEMPTS = 4
_RETRY_DELAY_S = 2.0  # times the attempt number
_RETRY_STATUS = {429, 500, 502, 503, 504}  # busy or briefly broken servers


def _session(token: str | None = None):
    """requests session that trusts the Windows certificate store (university proxies)."""
    global _truststore_done
    import requests

    if not _truststore_done:
        try:
            import truststore

            truststore.inject_into_ssl()
        except Exception:
            pass
        _truststore_done = True
    session = requests.Session()
    session.headers["User-Agent"] = f"LocalScribe/{__version__}"
    if token:
        if not HF_ENDPOINT.lower().startswith("https://"):  # HF_ENDPOINT can point at a mirror
            raise UserError("err_insecure_endpoint", url=HF_ENDPOINT)
        session.headers["Authorization"] = f"Bearer {token}"
    return session


def _check_auth(status: int) -> None:
    if status == 401:
        raise UserError("err_hf_token_invalid")
    if status == 403:
        raise UserError("err_hf_terms", url=PYANNOTE_PAGE)


def hf_url(repo: str, path: str, revision: str = "main") -> str:
    return f"{HF_ENDPOINT}/{repo}/resolve/{revision}/{quote(path)}"


def hf_list_files(repo: str, token: str | None = None,
                  revision: str = "main") -> list[tuple[str, int, str | None]]:
    """[(path, size, sha256 or None)] for every file in a Hugging Face model repo. Large (LFS)
    files come with their SHA-256; small ones only with a git hash, which isn't checked."""
    import requests

    try:
        resp = _session(token).get(f"{HF_ENDPOINT}/api/models/{repo}/tree/{revision}",
                                   params={"recursive": "true"}, timeout=30)
    except requests.RequestException as exc:
        raise UserError("err_network", detail=str(exc)) from exc
    _check_auth(resp.status_code)
    if resp.status_code >= 400:
        raise UserError("err_network", detail=f"HTTP {resp.status_code}")
    files = []
    for item in resp.json():
        if item.get("type") == "file":
            lfs = item.get("lfs") or {}
            size = lfs.get("size") or item.get("size") or 0
            files.append((item["path"], int(size), lfs.get("oid")))
    return files


class _Throttle:
    """Forwards progress at most every `interval` seconds (always forwards completion)."""

    def __init__(self, fn: ProgressFn | None, interval: float = 0.2):
        self.fn, self.interval, self.last = fn, interval, 0.0

    def __call__(self, done: int, total: int) -> None:
        now = time.monotonic()
        if self.fn and (now - self.last >= self.interval or (total and done >= total)):
            self.last = now
            self.fn(done, total)


class Download(NamedTuple):
    url: str
    dest: Path
    size: int             # bytes; 0 = unknown (only allowed where nothing better exists)
    sha256: str | None = None


def _inside(folder: Path, rel: str) -> Path:
    """folder / rel, refusing names from a listing that point outside folder."""
    target = (folder / rel).resolve()
    if not target.is_relative_to(folder.resolve()):
        raise UserError("err_unsafe_path", file=rel)
    return target


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def download_files(jobs: list[tuple], token: str | None = None,
                   progress: ProgressFn | None = None,
                   cancel: threading.Event | None = None) -> None:
    """Download (url, dest, size[, sha256]) jobs in order. Partial files resume; each file is
    written to `<dest>.part` and renamed when complete and verified, so `dest` existing means done."""
    import requests

    session = _session(token)
    report = _Throttle(progress)
    jobs = [Download(*job) for job in jobs]
    total = sum(max(job.size, 0) for job in jobs)
    done = 0
    for url, dest, size, sha256 in jobs:
        if dest.exists() and (size <= 0 or dest.stat().st_size == size):
            done += size
            report(done, total)
            continue
        part = dest.with_name(dest.name + ".part")
        _write_step(lambda: dest.parent.mkdir(parents=True, exist_ok=True), dest.parent)
        for attempt in range(1, _ATTEMPTS + 1):
            try:
                _download_one(session, url, part, size, done, total, report, cancel)
                break
            except requests.HTTPError as exc:
                status = exc.response.status_code if exc.response is not None else 0
                if status not in _RETRY_STATUS or attempt == _ATTEMPTS:
                    raise UserError("err_network", detail=f"HTTP {status}") from exc
            except (requests.ConnectionError, requests.Timeout, requests.exceptions.ChunkedEncodingError) as exc:
                if attempt == _ATTEMPTS:
                    raise UserError("err_network", detail=str(exc)) from exc
            except requests.RequestException as exc:  # e.g. too many redirects: retrying won't help
                raise UserError("err_network", detail=str(exc)) from exc
            except OSError as exc:  # after the requests errors, which are OSErrors too
                raise UserError("err_write", path=str(exc.filename or part)) from exc
            _wait(_RETRY_DELAY_S * attempt, cancel)
        if size > 0 and part.stat().st_size != size:
            raise UserError("err_download_incomplete", file=dest.name)
        if sha256 and _sha256(part) != sha256.lower():
            part.unlink(missing_ok=True)  # resuming a corrupt file would never fix it
            raise UserError("err_download_corrupt", file=dest.name)
        _write_step(lambda: os.replace(part, dest), dest)
        done += max(size, 0)
        report(done, total)


def _write_step(step: Callable[[], object], path: Path) -> None:
    try:
        step()
    except OSError as exc:
        raise UserError("err_write", path=str(exc.filename or path)) from exc


def _wait(seconds: float, cancel: threading.Event | None) -> None:
    """Sleep that Stop interrupts."""
    if cancel is None:
        time.sleep(seconds)
    elif cancel.wait(seconds):
        raise Cancelled()


def _download_one(session, url, part: Path, size, done_before, total, report, cancel) -> None:
    pos = part.stat().st_size if part.exists() else 0
    if size > 0 and pos > size:
        part.unlink()
        pos = 0
    if size > 0 and pos == size:
        return
    headers = {"Range": f"bytes={pos}-"} if pos else {}
    with session.get(url, headers=headers, stream=True, timeout=(20, 120)) as resp:
        _check_auth(resp.status_code)
        if resp.status_code == 416:  # stale partial file
            part.unlink(missing_ok=True)
            return _download_one(session, url, part, size, done_before, total, report, cancel)
        resp.raise_for_status()
        if pos and resp.status_code != 206:  # server ignored the range request
            pos = 0
        with open(part, "ab" if pos else "wb") as fh:
            got = pos
            for chunk in resp.iter_content(chunk_size=1 << 20):
                if cancel is not None and cancel.is_set():
                    raise Cancelled()
                fh.write(chunk)
                got += len(chunk)
                report(done_before + got, total)


def _remote_size(url: str) -> int:
    try:
        resp = _session().head(url, allow_redirects=True, timeout=20)
        return int(resp.headers.get("Content-Length", 0)) if resp.ok else 0
    except Exception:
        return 0


class ModelStore:
    """Finds models in the writable folder first, then in read-only bundled folders."""

    def __init__(self, root: Path, extra_roots: Iterable[Path | None] = ()):
        self.root = Path(root)
        self.roots = [self.root, *[Path(r) for r in extra_roots if r]]

    def _find(self, rel: str) -> Path | None:
        for base in self.roots:
            path = base / rel
            if path.exists():
                return path
        return None

    # ---- Whisper -------------------------------------------------------
    def whisper_path(self, name: str) -> Path | None:
        found = self._find(f"whisper/{name}/model.bin")
        return found.parent if found else None

    def ensure_whisper(self, name: str, progress: ProgressFn | None = None,
                       cancel: threading.Event | None = None) -> Path:
        existing = self.whisper_path(name)
        if existing:
            return existing
        repo = WHISPER_REPOS.get(name)
        if repo is None:
            raise UserError("err_unknown_model", name=name)
        remote = {f: (size, sha) for f, size, sha in hf_list_files(repo)}
        dest = self.root / "whisper" / name
        jobs = [(hf_url(repo, f), dest / f, *remote[f]) for f in _WHISPER_FILES if f in remote]
        download_files(jobs, progress=progress, cancel=cancel)
        return dest

    # ---- sherpa-onnx ---------------------------------------------------
    def sherpa_paths(self) -> tuple[Path, Path] | None:
        seg, emb = self._find(SHERPA_SEG), self._find(SHERPA_EMB)
        return (seg, emb) if seg and emb else None

    def ensure_sherpa(self, progress: ProgressFn | None = None,
                      cancel: threading.Event | None = None) -> tuple[Path, Path]:
        found = self.sherpa_paths()
        if found:
            return found
        base = self.root / "sherpa-onnx"
        archive = base / "segmentation.tar.bz2"
        jobs = []
        if not self._find(SHERPA_SEG):
            jobs.append((SHERPA_SEG_URL, archive, _remote_size(SHERPA_SEG_URL)))
        if not self._find(SHERPA_EMB):
            jobs.append((SHERPA_EMB_URL, self.root / SHERPA_EMB, _remote_size(SHERPA_EMB_URL)))
        for url, _, size in jobs:
            if size <= 0:  # without a size, a cut-off download would look complete
                raise UserError("err_size_unknown", file=url.rsplit("/", 1)[-1])
        download_files(jobs, progress=progress, cancel=cancel)
        if archive.exists():
            with tarfile.open(archive, "r:bz2") as tar:
                tar.extractall(base, filter="data")
            archive.unlink()
        found = self.sherpa_paths()
        if not found:
            raise UserError("err_download_incomplete", file="sherpa-onnx")
        return found

    # ---- pyannote ------------------------------------------------------
    def pyannote_path(self) -> Path | None:
        found = self._find(f"{PYANNOTE_DIR}/config.yaml")
        return found.parent if found else None

    def download_pyannote(self, token: str, progress: ProgressFn | None = None,
                          cancel: threading.Event | None = None) -> Path:
        token = (token or "").strip()
        if not token:
            raise UserError("err_hf_token_missing")
        files = [(f, s, sha) for f, s, sha in hf_list_files(PYANNOTE_REPO, token)
                 if not f.endswith((".gif", ".gitattributes"))]
        files.sort(key=lambda fs: fs[0] == "config.yaml")  # config.yaml last: marks completion
        dest = self.root / PYANNOTE_DIR
        jobs = [(hf_url(PYANNOTE_REPO, f), _inside(dest, f), s, sha) for f, s, sha in files]
        download_files(jobs, token=token, progress=progress, cancel=cancel)
        return dest
