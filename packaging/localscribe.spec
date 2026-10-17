# PyInstaller build: one folder, windowed.   Run packaging\build.ps1 rather than this file directly.
#
# Bundled models: sherpa-onnx always. Whisper models download on first use.
# Opt-in extras for internal (non-public) builds:
#   LOCALSCRIBE_BUNDLE_PYANNOTE=1          ship models\pyannote (gated on Hugging Face, so keep
#                                          it out of public releases)
#   LOCALSCRIBE_BUNDLE_WHISPER=large-v3,small   ship Whisper models for offline computers
import os
from pathlib import Path

from PyInstaller.utils.hooks import (collect_data_files, collect_delvewheel_libs_directory, collect_dynamic_libs,
                                     collect_submodules, copy_metadata)

ROOT = Path(SPECPATH).parent
MODELS = ROOT / "models"

datas, binaries, hiddenimports = [], [], []

for pkg in ("pyannote.audio", "pyannote.core", "pyannote.pipeline", "pyannote.database", "pyannote.metrics",
            "faster_whisper", "docx", "imageio_ffmpeg", "lightning", "lightning_fabric", "pytorch_lightning",
            "torchmetrics", "optuna", "asteroid_filterbanks", "torch_audiomentations"):
    datas += collect_data_files(pkg)
for pkg in ("pyannote.audio", "pyannote.pipeline", "pyannote.core", "pyannote.database", "pyannote.metrics",
            "sherpa_onnx", "lightning_fabric", "pytorch_lightning", "opentelemetry"):
    hiddenimports += collect_submodules(pkg)
for pkg in ("ctranslate2", "sherpa_onnx", "onnxruntime", "torchcodec"):
    binaries += collect_dynamic_libs(pkg)
# OpenCC: its dictionaries, and the msvcp140 copy its wheel carries. The contributed hook takes the whole
# package, so its command-line tools, C headers and static libraries (8 MB) are left out after Analysis.
datas += collect_data_files("opencc", includes=["clib/share/opencc/*"])
datas, binaries = collect_delvewheel_libs_directory("opencc", datas=datas, binaries=binaries)
_OPENCC_BUILD_ONLY = ("opencc/clib/bin/", "opencc/clib/include/", "opencc/clib/lib/")
# importlib.metadata lookups (pyannote's dependency check, opentelemetry entry points, lightning)
for dist in ("pyannote.audio", "faster-whisper", "ctranslate2", "sherpa-onnx", "torch", "torchaudio"):
    datas += copy_metadata(dist, recursive=True)

datas.append((str(MODELS / "sherpa-onnx"), "models/sherpa-onnx"))
if os.environ.get("LOCALSCRIBE_BUNDLE_PYANNOTE") == "1":
    datas.append((str(MODELS / "pyannote"), "models/pyannote"))
for notice in ("LICENSE", "THIRD_PARTY_NOTICES.md"):
    datas.append((str(ROOT / notice), "."))
for name in filter(None, os.environ.get("LOCALSCRIBE_BUNDLE_WHISPER", "").split(",")):
    datas.append((str(MODELS / "whisper" / name.strip()), f"models/whisper/{name.strip()}"))

a = Analysis(
    [str(ROOT / "run_localscribe.py")],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["tkinter", "IPython", "jupyter", "notebook", "pytest", "sphinx", "PyInstaller",
              "PySide6.QtWebEngineCore", "PySide6.QtQml", "PySide6.QtQuick", "PySide6.Qt3DCore"],
    noarchive=False,
)
a.datas, a.binaries = ([entry for entry in toc if not entry[0].replace("\\", "/").startswith(_OPENCC_BUILD_ONLY)]
                       for toc in (a.datas, a.binaries))  # its .exe tools count as binaries
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="LocalScribe",
    icon=str(ROOT / "packaging" / "localscribe.ico"),
    console=False,
    upx=False,
    version=None,
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="LocalScribe")
