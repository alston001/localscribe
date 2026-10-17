"""Update files for a release: the bundle's file list, the update installer and latest.json.

Run from PowerShell after build.ps1 and the full installer (README: Building the installer):

    .venv\\Scripts\\python.exe packaging\\release_assets.py --bundle dist_build\\LocalScribe

It writes into dist\\; attach all of them to the GitHub release:
    LocalScribe-<v>-files.json   every file of the bundle with its size and SHA-256; the next
                                 release builds its update installer against it
    LocalScribe-Update-<v>.exe   only the files that changed since the previous release, for the
                                 older versions whose other files are all the same
    latest.json                  what LocalScribe reads to offer the update (core/update.py)
"""

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from localscribe import __version__  # noqa: E402
from localscribe.core import update  # noqa: E402
from localscribe.core.errors import UserError  # noqa: E402

BUILD = ROOT / "build"  # the generated Inno file list goes here
DEFAULT_ISCC = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Inno Setup 6" / "ISCC.exe"
MAX_UPDATE_BYTES = 1_500_000_000  # past this the update installer saves little: offer the full one
_BAD_CHARS = set('\\:*?"<>|') | {chr(c) for c in range(32)}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def file_list(bundle: Path) -> dict[str, list]:
    """{"_internal/x.dll": [size, sha256], ...} for every file in the bundle, sorted."""
    files = {p.relative_to(bundle).as_posix(): p for p in bundle.rglob("*") if p.is_file()}
    return {rel: [files[rel].stat().st_size, _sha256(files[rel])] for rel in sorted(files)}


@dataclass
class UpdatePlan:
    files: list[str]        # to install: changed or new since the previous release
    deletes: list[str]      # left over from an older version the update fits
    update_from: list[str]  # the versions the update installer fits, newest first


def plan_update(new: dict, bases: dict[str, dict]) -> UpdatePlan:
    """bases: {version: file list} of older releases. The update installer holds what changed
    since the newest of them, and fits every one whose other files are the same as `new`."""
    previous = bases[max(bases, key=update.parse_version)]
    files = [rel for rel, meta in new.items() if previous.get(rel) != meta]
    unchanged = set(new) - set(files)
    fits = sorted((v for v, old in bases.items() if all(old.get(rel) == new[rel] for rel in unchanged)),
                  key=update.parse_version, reverse=True)
    deletes = sorted({rel for v in fits for rel in bases[v] if rel not in new})
    return UpdatePlan(sorted(files), deletes, fits)


def _parts(rel: str) -> list[str]:
    """The folders and name of a bundle path. The deletes come from an older release's file list,
    which may have been downloaded or edited, so nothing may point outside the app folder (no
    "..", drive or wildcard) or be unwritable in an Inno parameter (a quote, or ISPP's "{#")."""
    parts = rel.split("/")
    if any(p in ("", ".", "..") for p in parts) or any(c in _BAD_CHARS for c in rel) or "{#" in rel:
        sys.exit(f"refusing the bundle path {rel!r}")
    return parts


def _inno_constant_safe(parts: list[str]) -> str:
    return "\\".join(p.replace("{", "{{") for p in parts)  # "{" starts an Inno constant


def inno_include(plan: UpdatePlan, version: str) -> str:
    """The part of packaging/update.iss that changes with every release. Source paths are read
    literally by the compiler; DestDir and Name are expanded at install time."""
    lines = [f'#define AppVersion "{version}"', f'#define UpdateFrom "{",".join(plan.update_from)}"', "", "[Files]"]
    # LocalScribe.exe, which holds the version the app reports, goes in last: Inno doesn't put back
    # files it replaced, so an update that fails half way must leave the old version, which then
    # offers the same update again.
    for rel in sorted(plan.files, key=lambda rel: rel == "LocalScribe.exe"):
        parts = _parts(rel)
        folder = "\\".join(["{app}", *([_inno_constant_safe(parts[:-1])] if parts[:-1] else [])])
        lines.append(f'Source: "{{#DistDir}}\\{chr(92).join(parts)}"; DestDir: "{folder}"; Flags: ignoreversion')
    lines += ["", "[InstallDelete]"]
    lines += [f'Type: files; Name: "{{app}}\\{_inno_constant_safe(_parts(rel))}"' for rel in plan.deletes]
    return "\r\n".join(lines) + "\r\n"


def _asset(path: Path) -> dict:
    return {"name": path.name, "size": path.stat().st_size, "sha256": _sha256(path)}


def _check_slices(setup: Path, slices: list[Path]) -> None:
    """ISCC writes slice after slice and the setup exe last. A slice out of that order is left from
    an earlier compile of this version (which needed more slices): it would be listed and downloaded."""
    files = [*slices, setup]
    for earlier, later in zip(files, files[1:]):
        if later.stat().st_mtime < earlier.stat().st_mtime - 2:  # 2 s: file times aren't exact
            sys.exit(f"{later.name} is older than {earlier.name}, so it is left from an earlier compile. "
                     f"Delete {setup.stem}*.bin and {setup.name}, and compile installer.iss again")


def latest_info(version: str, dist: Path, install_size: int, update_from: list[str] = (),
                update_size: int = 0) -> dict:
    """latest.json: the full installer with its slices, and the update installer if it was built.
    The install sizes are what each writes into the app folder, for LocalScribe's disk check."""
    setup = dist / f"LocalScribe-Setup-{version}.exe"
    pattern = re.compile(rf"LocalScribe-Setup-{re.escape(version)}-(\d+)\.bin")
    numbered = {}
    for path in dist.iterdir():
        if match := pattern.fullmatch(path.name):
            numbered[int(match.group(1))] = path
    slices = [numbered[n] for n in sorted(numbered)]
    _check_slices(setup, slices)
    info = {"format": update.FORMAT, "version": version,
            "full": {"files": [_asset(p) for p in [setup, *slices]], "install_size": install_size}}
    small = dist / f"LocalScribe-Update-{version}.exe"
    if update_from and small.is_file():
        info["update"] = {"from": list(update_from), "files": [_asset(small)], "install_size": update_size}
    return info


def older_file_lists(dist: Path, version: str) -> dict[str, dict]:
    """{version: file list} of the releases before `version` whose file list is in dist."""
    lists = {}
    for path in dist.glob("LocalScribe-*-files.json"):
        data = json.loads(path.read_text(encoding="utf-8"))
        found = update.parse_version(data.get("version"))
        if found and found < update.parse_version(version):
            lists[data["version"]] = data["files"]
    return lists


def installer_version() -> str:
    text = (ROOT / "packaging" / "installer.iss").read_text(encoding="utf-8-sig")
    match = re.search(r'^\s*#define AppVersion "([^"]+)"', text, re.M)
    return match.group(1) if match else ""


def bundle_version(exe: Path) -> str:
    """The version frozen into a PyInstaller build of LocalScribe."""
    from PyInstaller.archive.readers import CArchiveReader

    package = CArchiveReader(str(exe))
    pyz = package.open_embedded_archive(next(name for name in package.toc if name.endswith(".pyz")))
    consts = pyz.extract("localscribe").co_consts  # localscribe/__init__.py
    return next(c for c in consts if isinstance(c, str) and update.parse_version(c))


def compile_update(include: Path, bundle: Path, out_dir: Path, iscc: Path, extra: tuple[str, ...] = ()) -> None:
    if not iscc.is_file():
        sys.exit(f"{iscc} not found: install Inno Setup 6 or pass --iscc")
    cmd = [str(iscc), f"/DDistDir={bundle}", f"/DUpdateList={include}", f"/O{out_dir}", *extra,
           str(ROOT / "packaging" / "update.iss")]
    if subprocess.run(cmd).returncode != 0:
        sys.exit("ISCC could not compile packaging\\update.iss")


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--bundle", type=Path, default=ROOT / "dist" / "LocalScribe", help="the built LocalScribe folder")
    p.add_argument("--dist", type=Path, default=ROOT / "dist", help="where the installers are; output goes here too")
    p.add_argument("--iscc", type=Path, default=DEFAULT_ISCC, help="Inno Setup's ISCC.exe")
    args = p.parse_args(argv)
    bundle, dist, version = args.bundle.resolve(), args.dist.resolve(), __version__
    exe = bundle / "LocalScribe.exe"
    if not exe.is_file():
        sys.exit(f"{exe} not found: build first (packaging\\build.ps1)")
    if installer_version() != version:
        sys.exit(f"packaging\\installer.iss says {installer_version()} but the app is {version}: bump both")
    try:
        built = bundle_version(exe)
    except Exception as exc:
        sys.exit(f"could not read the version inside {exe} ({type(exc).__name__}: {exc})")
    if built != version:
        sys.exit(f"{bundle} holds LocalScribe {built}, not {version}: build again")
    setup = dist / f"LocalScribe-Setup-{version}.exe"
    if not setup.is_file():
        sys.exit(f"{setup.name} not found in {dist}: compile packaging\\installer.iss first")

    files = file_list(bundle)
    listing = dist / f"LocalScribe-{version}-files.json"
    listing.write_text(json.dumps({"version": version, "files": files}, separators=(",", ":")), encoding="utf-8")
    print(f"wrote {listing.name} ({len(files)} files)")
    update_from: list[str] = []
    update_size = 0
    bases = older_file_lists(dist, version)
    if not bases:
        print("no file list of an older release in dist: latest.json offers the full installer only")
    else:
        plan = plan_update(files, bases)
        size = sum(files[rel][0] for rel in plan.files)
        if not plan.files:
            print(f"nothing changed since {max(bases, key=update.parse_version)}: no update installer")
        elif size > MAX_UPDATE_BYTES:
            print(f"{size / 1e9:.1f} GB changed (bundled libraries?): latest.json offers the full installer only")
        else:
            BUILD.mkdir(parents=True, exist_ok=True)
            include = BUILD / f"update-{version}.iss"
            include.write_text(inno_include(plan, version), encoding="utf-8-sig", newline="")
            compile_update(include, bundle, dist, args.iscc)
            update_from, update_size = plan.update_from, size
            print(f"wrote LocalScribe-Update-{version}.exe: {len(plan.files)} file(s), {size / 1e6:.0f} MB "
                  f"before compression, for {', '.join(update_from)}")
    stale = dist / f"LocalScribe-Update-{version}.exe"
    if not update_from and stale.is_file():
        print(f"note: {stale.name} in dist is from an earlier run; don't attach it")
    info = latest_info(version, dist, sum(size for size, _ in files.values()), update_from, update_size)
    try:  # LocalScribe has to be able to read it
        update.parse_latest(info, current="0.0.0")
        offered = update.parse_latest(info, current=update_from[0]) if update_from else None
    except UserError as exc:
        sys.exit(f"latest.json would be unreadable: {exc}")
    if update_from and offered.kind != "update":
        sys.exit("latest.json would not offer the update installer")
    (dist / "latest.json").write_text(json.dumps(info, indent=1), encoding="utf-8")
    print(f"wrote latest.json ({len(info['full']['files'])} full installer file(s)"
          f"{', update installer' if update_from else ''}); attach it last, see the README")


if __name__ == "__main__":
    main()
