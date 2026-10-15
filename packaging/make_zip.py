"""Zips <dist>/LocalScribe into <dist>/LocalScribe-<version>-win64.zip (ZIP64, works past 4 GB).

Usage: python packaging/make_zip.py [dist folder, default dist]   e.g. dist_build

Colleagues unzip anywhere and double-click LocalScribe.exe; no installer or admin rights needed.
"""

import argparse
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from localscribe import __version__  # noqa: E402


def main(argv: list[str] | None = None) -> Path:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("dist", nargs="?", type=Path, default=ROOT / "dist", help="folder that contains LocalScribe/")
    dist = p.parse_args(argv).dist.resolve()
    source = dist / "LocalScribe"
    if not (source / "LocalScribe.exe").is_file():
        sys.exit(f"{source / 'LocalScribe.exe'} not found: build first, or pass the folder given to build.ps1 -DistPath")
    target = dist / f"LocalScribe-{__version__}-win64.zip"
    files = [p for p in source.rglob("*") if p.is_file()]
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6, allowZip64=True) as zf:
        for i, path in enumerate(files, 1):
            zf.write(path, Path("LocalScribe") / path.relative_to(source))
            if i % 500 == 0:
                print(f"{i}/{len(files)} files")
    print(f"wrote {target} ({target.stat().st_size / 2**30:.2f} GB)")
    return target


if __name__ == "__main__":
    main()
