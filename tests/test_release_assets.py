"""packaging/release_assets.py: the files a release needs so that LocalScribe can update itself."""

import hashlib
import importlib.util
import json
import os
import re
from pathlib import Path

import pytest

from localscribe import __version__
from localscribe.core import update

ROOT = Path(__file__).resolve().parent.parent


def load_release_assets():
    spec = importlib.util.spec_from_file_location("release_assets", ROOT / "packaging" / "release_assets.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # must not build anything on import
    return module


@pytest.fixture
def ra():
    return load_release_assets()


def entry(data: bytes) -> list:
    return [len(data), hashlib.sha256(data).hexdigest()]


def make_tree(root: Path, files: dict[str, bytes]) -> Path:
    for rel, data in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    return root


# ---- the file list -----------------------------------------------------------------
def test_the_file_list_has_every_file_with_its_size_and_sha256(ra, tmp_path):
    bundle = make_tree(tmp_path / "LocalScribe", {"LocalScribe.exe": b"MZ", "_internal/torch/lib/c10.dll": b"dll"})
    assert ra.file_list(bundle) == {"LocalScribe.exe": entry(b"MZ"), "_internal/torch/lib/c10.dll": entry(b"dll")}


# ---- what the update installer holds -----------------------------------------------
def test_the_update_holds_what_changed_since_the_previous_release(ra):
    new = {"LocalScribe.exe": entry(b"exe 4"), "_internal/torch.dll": entry(b"torch"), "_internal/added.py": entry(b"+")}
    bases = {"0.1.3": {"LocalScribe.exe": entry(b"exe 3"), "_internal/torch.dll": entry(b"torch"),
                       "_internal/gone.dll": entry(b"gone")}}
    plan = ra.plan_update(new, bases)
    assert plan.files == ["LocalScribe.exe", "_internal/added.py"]
    assert plan.deletes == ["_internal/gone.dll"]
    assert plan.update_from == ["0.1.3"]


def test_older_versions_qualify_when_everything_else_is_the_same(ra):
    torch = entry(b"torch 2.14")
    new = {"LocalScribe.exe": entry(b"exe 5"), "_internal/torch.dll": torch}
    bases = {"0.1.4": {"LocalScribe.exe": entry(b"exe 4"), "_internal/torch.dll": torch},
             "0.1.3": {"LocalScribe.exe": entry(b"exe 3"), "_internal/torch.dll": torch, "_internal/x.dll": entry(b"x")},
             "0.1.2": {"LocalScribe.exe": entry(b"exe 2"), "_internal/torch.dll": entry(b"torch 2.13")}}
    plan = ra.plan_update(new, bases)
    assert plan.files == ["LocalScribe.exe"]
    assert plan.update_from == ["0.1.4", "0.1.3"]  # 0.1.2 has another torch: it needs the full installer
    assert plan.deletes == ["_internal/x.dll"]


def test_the_previous_release_is_found_by_number(ra):
    new = {"LocalScribe.exe": entry(b"exe 10"), "a.dll": entry(b"a2")}
    bases = {"0.1.9": {"LocalScribe.exe": entry(b"exe 9"), "a.dll": entry(b"a2")},
             "0.1.1": {"LocalScribe.exe": entry(b"exe 1"), "a.dll": entry(b"a1")}}
    plan = ra.plan_update(new, bases)  # as text, "0.1.1" > "0.1.10" > "0.1.9"
    assert plan.files == ["LocalScribe.exe"] and plan.update_from == ["0.1.9"]


def test_the_inno_list_installs_changed_files_and_removes_stale_ones(ra):
    plan = ra.UpdatePlan(files=["LocalScribe.exe", "_internal/odd {dir}/x {y}.txt"],
                         deletes=["_internal/gone.dll", "_internal/{old}.dll"], update_from=["0.1.4", "0.1.3"])
    lines = ra.inno_include(plan, "0.1.5").splitlines()
    assert '#define AppVersion "0.1.5"' in lines and '#define UpdateFrom "0.1.4,0.1.3"' in lines
    assert 'Source: "{#DistDir}\\LocalScribe.exe"; DestDir: "{app}"; Flags: ignoreversion' in lines
    # Source is taken literally; in DestDir and Name, "{" starts an Inno constant and is doubled.
    assert ('Source: "{#DistDir}\\_internal\\odd {dir}\\x {y}.txt"; DestDir: "{app}\\_internal\\odd {{dir}"; '
            'Flags: ignoreversion') in lines
    assert 'Type: files; Name: "{app}\\_internal\\gone.dll"' in lines
    assert 'Type: files; Name: "{app}\\_internal\\{{old}.dll"' in lines


def test_the_exe_goes_in_last(ra):
    # LocalScribe.exe holds the version the app reports: an update that fails half way must leave
    # the old one, which offers the same update again (Inno doesn't put back files it replaced).
    plan = ra.UpdatePlan(files=["LocalScribe.exe", "_internal/a.dll", "_internal/z.dll"], deletes=[],
                         update_from=["0.1.3"])
    sources = [line for line in ra.inno_include(plan, "0.1.4").splitlines() if line.startswith("Source:")]
    assert [s.split('"')[1] for s in sources] == ["{#DistDir}\\_internal\\a.dll", "{#DistDir}\\_internal\\z.dll",
                                                  "{#DistDir}\\LocalScribe.exe"]


def test_the_full_installer_also_puts_the_exe_in_last():
    text = (ROOT / "packaging" / "installer.iss").read_text(encoding="utf-8-sig")
    files = text.split("[Files]")[1].split("\n[")[0]
    sources = [line for line in files.splitlines() if line.startswith("Source:")]
    assert len(sources) == 2
    assert 'Excludes: "\\{#AppExe}"' in sources[0] and sources[1].startswith('Source: "{#DistDir}\\{#AppExe}"')


@pytest.mark.parametrize("name", ['a"b.dll', "x{#y}.dll", "../evil.dll", "_internal/../../Documents/x.docx",
                                  "C:/Windows/x.dll", "/abs.dll", "_internal/*", "_internal/a?.dll",
                                  "a\\b.dll", "", "_internal//x.dll", "./x.dll", "x.dll:stream", "x\x01.dll"])
@pytest.mark.parametrize("where", ["files", "deletes"])
def test_names_that_could_reach_outside_the_app_folder_are_refused(ra, name, where):
    # The deletes come from an older release's file list, which may have been downloaded or edited:
    # a wildcard or ".." there would delete files on every computer the update reaches.
    lists = {"files": ["LocalScribe.exe"], "deletes": [], where: [name]}
    with pytest.raises(SystemExit):
        ra.inno_include(ra.UpdatePlan(files=lists["files"], deletes=lists["deletes"], update_from=["0.1.3"]),
                        "0.1.4")


# ---- latest.json -------------------------------------------------------------------
def write_installers(dist: Path, version: str, update_installer: bool = True) -> None:
    """Like ISCC writes them: slice after slice, the setup exe last."""
    names = [f"LocalScribe-Setup-{version}-{n}.bin" for n in range(1, 11)] + [f"LocalScribe-Setup-{version}.exe"]
    for i, name in enumerate(names):
        make_tree(dist, {name: b"setup" if name.endswith(".exe") else f"slice {i + 1}".encode()})
        os.utime(dist / name, (1_760_000_000 + i, 1_760_000_000 + i))
    if update_installer:
        make_tree(dist, {f"LocalScribe-Update-{version}.exe": b"update"})


def test_latest_json_lists_both_installers_and_the_app_reads_it(ra, tmp_path):
    write_installers(tmp_path, "0.1.5")
    info = ra.latest_info("0.1.5", tmp_path, 5_000_000_000, ["0.1.4"], 80_000_000)
    files = info["full"]["files"]
    assert files[0] == {"name": "LocalScribe-Setup-0.1.5.exe", "size": 5, "sha256": hashlib.sha256(b"setup").hexdigest()}
    assert [a["name"] for a in files[1:]] == [f"LocalScribe-Setup-0.1.5-{n}.bin" for n in range(1, 11)]
    assert info["full"]["install_size"] == 5_000_000_000
    assert info["update"]["from"] == ["0.1.4"] and info["update"]["install_size"] == 80_000_000
    assert [a["name"] for a in info["update"]["files"]] == ["LocalScribe-Update-0.1.5.exe"]
    assert update.parse_latest(info, current="0.1.4").kind == "update"
    assert update.parse_latest(info, current="0.1.3").install_size == 5_000_000_000


def test_without_an_update_installer_latest_json_offers_the_full_one(ra, tmp_path):
    write_installers(tmp_path, "0.1.5", update_installer=False)
    info = ra.latest_info("0.1.5", tmp_path, 5_000_000_000)
    assert "update" not in info
    assert update.parse_latest(info, current="0.1.4").kind == "full"


def test_a_slice_left_from_an_earlier_compile_is_refused(ra, tmp_path):
    write_installers(tmp_path, "0.1.5")
    os.utime(tmp_path / "LocalScribe-Setup-0.1.5-10.bin", (1_700_000_000, 1_700_000_000))  # days older
    with pytest.raises(SystemExit) as caught:
        ra.latest_info("0.1.5", tmp_path, 5_000_000_000)
    assert "LocalScribe-Setup-0.1.5-10.bin" in str(caught.value.code)


# ---- the whole command -------------------------------------------------------------
@pytest.fixture
def release(ra, tmp_path, monkeypatch):
    """A built 0.1.5 bundle, its full installer, and 0.1.4's file list in dist."""
    monkeypatch.setattr(ra, "__version__", "0.1.5")
    monkeypatch.setattr(ra, "installer_version", lambda: "0.1.5")
    monkeypatch.setattr(ra, "bundle_version", lambda exe: "0.1.5")
    bundle = make_tree(tmp_path / "dist_build" / "LocalScribe", {"LocalScribe.exe": b"exe 5", "_internal/torch.dll": b"torch"})
    dist = tmp_path / "dist"
    write_installers(dist, "0.1.5", update_installer=False)
    old = {"version": "0.1.4", "files": {"LocalScribe.exe": entry(b"exe 4"), "_internal/torch.dll": entry(b"torch")}}
    (dist / "LocalScribe-0.1.4-files.json").write_text(json.dumps(old), encoding="utf-8")
    compiled = []

    def compile_update(include, bundle_dir, out_dir, iscc):
        compiled.append((include.read_text(encoding="utf-8-sig"), bundle_dir))
        (out_dir / "LocalScribe-Update-0.1.5.exe").write_bytes(b"update")

    monkeypatch.setattr(ra, "compile_update", compile_update)
    monkeypatch.setattr(ra, "BUILD", tmp_path / "build")
    return bundle, dist, compiled


def test_main_writes_the_file_list_the_update_installer_and_latest_json(ra, release):
    bundle, dist, compiled = release
    ra.main(["--bundle", str(bundle), "--dist", str(dist)])
    files = json.loads((dist / "LocalScribe-0.1.5-files.json").read_text(encoding="utf-8"))
    assert files == {"version": "0.1.5", "files": ra.file_list(bundle)}
    (include, bundle_dir), = compiled
    assert "LocalScribe.exe" in include and "torch.dll" not in include and bundle_dir == bundle.resolve()
    info = json.loads((dist / "latest.json").read_text(encoding="utf-8"))
    assert info["update"]["from"] == ["0.1.4"]
    assert update.parse_latest(info, current="0.1.4").files[0].name == "LocalScribe-Update-0.1.5.exe"
    assert info["full"]["install_size"] == len(b"exe 5") + len(b"torch")  # what each installer writes
    assert info["update"]["install_size"] == len(b"exe 5")


def test_an_update_installer_too_big_to_help_is_left_out(ra, release, monkeypatch):
    bundle, dist, compiled = release
    monkeypatch.setattr(ra, "MAX_UPDATE_BYTES", 3)  # the changed files: 5 bytes
    ra.main(["--bundle", str(bundle), "--dist", str(dist)])
    assert compiled == [] and "update" not in json.loads((dist / "latest.json").read_text(encoding="utf-8"))


def test_without_older_file_lists_only_the_full_installer_is_offered(ra, release):
    bundle, dist, compiled = release
    (dist / "LocalScribe-0.1.4-files.json").unlink()
    ra.main(["--bundle", str(bundle), "--dist", str(dist)])
    assert compiled == [] and "update" not in json.loads((dist / "latest.json").read_text(encoding="utf-8"))


def test_a_stale_bundle_is_refused(ra, release, monkeypatch):
    bundle, dist, _ = release
    monkeypatch.setattr(ra, "bundle_version", lambda exe: "0.1.4")  # dist_build still holds the last release
    with pytest.raises(SystemExit) as caught:
        ra.main(["--bundle", str(bundle), "--dist", str(dist)])
    assert "0.1.4" in str(caught.value.code)
    assert not (dist / "latest.json").exists()


def test_a_missing_full_installer_is_refused(ra, release):
    bundle, dist, _ = release
    (dist / "LocalScribe-Setup-0.1.5.exe").unlink()
    with pytest.raises(SystemExit) as caught:
        ra.main(["--bundle", str(bundle), "--dist", str(dist)])
    assert "LocalScribe-Setup-0.1.5.exe" in str(caught.value.code)


# ---- the installer scripts ---------------------------------------------------------
def iss_define(name: str, script: str) -> str:
    text = (ROOT / "packaging" / script).read_text(encoding="utf-8-sig")
    return re.search(rf'^\s*#define {name} "([^"]+)"', text, re.M).group(1)


def test_the_installer_version_is_the_app_version():
    assert iss_define("AppVersion", "installer.iss") == __version__


@pytest.mark.parametrize("script", ["installer.iss", "update.iss"])
def test_installer_messages_never_block_a_silent_install(script):
    # A plain MsgBox shows even under /VERYSILENT /SUPPRESSMSGBOXES and waits for someone to click OK.
    text = (ROOT / "packaging" / script).read_text(encoding="utf-8-sig")
    assert re.findall(r"(?<!Suppressible)MsgBox\(", text) == []


def test_both_installers_update_the_same_app():
    assert iss_define("AppGuid", "update.iss") == iss_define("AppGuid", "installer.iss")
    assert iss_define("AppName", "update.iss") == iss_define("AppName", "installer.iss") == "LocalScribe"
