"""Zips dist/LocalScribe into dist/LocalScribe-<version>-win64.zip (ZIP64, works past 4 GB).

Colleagues unzip anywhere and double-click LocalScribe.exe; no installer or admin rights needed.
"""

import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from localscribe import __version__  # noqa: E402

source = ROOT / "dist" / "LocalScribe"
target = ROOT / "dist" / f"LocalScribe-{__version__}-win64.zip"
files = [p for p in source.rglob("*") if p.is_file()]
with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6, allowZip64=True) as zf:
    for i, path in enumerate(files, 1):
        zf.write(path, Path("LocalScribe") / path.relative_to(source))
        if i % 500 == 0:
            print(f"{i}/{len(files)} files")
print(f"wrote {target} ({target.stat().st_size / 2**30:.2f} GB)")
