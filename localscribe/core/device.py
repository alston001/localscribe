"""Hardware detection and CUDA library setup."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path


def prepare_environment() -> None:
    """Must run before torch / ctranslate2 / pyannote are imported."""
    # torch and ctranslate2 each ship Intel's OpenMP runtime; loading both is safe here.
    os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
    # pyannote.audio 4 sends usage telemetry by default. Recordings stay private: turn it off.
    os.environ["PYANNOTE_METRICS_ENABLED"] = "false"
    os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
    os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")


@lru_cache(maxsize=1)
def load_cuda_libraries() -> bool:
    """Import torch first so its bundled cuBLAS/cuDNN DLLs are visible to CTranslate2."""
    prepare_environment()
    try:
        import torch
    except Exception:
        return False
    lib = Path(torch.__file__).parent / "lib"
    if sys.platform == "win32" and lib.is_dir():
        os.add_dll_directory(str(lib))
        os.environ["PATH"] = str(lib) + os.pathsep + os.environ.get("PATH", "")
    return True


@dataclass(frozen=True)
class DeviceInfo:
    cuda: bool
    gpu_name: str
    vram_gb: float
    cpu_name: str
    cpu_threads: int

    def summary(self) -> str:
        if self.cuda:
            return f"{self.gpu_name} ({self.vram_gb:.0f} GB)"
        return self.cpu_name


def _cpu_name() -> str:
    if sys.platform == "win32":
        try:
            import winreg

            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                                r"HARDWARE\DESCRIPTION\System\CentralProcessor\0") as key:
                return str(winreg.QueryValueEx(key, "ProcessorNameString")[0]).strip()
        except OSError:
            pass
    import platform

    return platform.processor() or "CPU"


@lru_cache(maxsize=1)
def detect() -> DeviceInfo:
    load_cuda_libraries()
    threads = os.cpu_count() or 4
    gpu_name, vram, cuda = "", 0.0, False
    try:
        import ctranslate2

        cuda = ctranslate2.get_cuda_device_count() > 0
    except Exception:
        cuda = False
    if cuda:
        try:
            import torch

            props = torch.cuda.get_device_properties(0)
            gpu_name, vram = props.name, props.total_memory / 2**30
        except Exception:
            gpu_name = "NVIDIA GPU"
    return DeviceInfo(cuda, gpu_name, vram, _cpu_name(), threads)


def resolve(preference: str) -> str:
    """'auto' | 'cuda' | 'cpu' -> 'cuda' | 'cpu'."""
    if preference == "cpu":
        return "cpu"
    return "cuda" if detect().cuda else "cpu"


def compute_type(device: str) -> str:
    if device == "cpu":
        return "int8"
    import ctranslate2

    supported = ctranslate2.get_supported_compute_types("cuda")
    for choice in ("float16", "int8_float16", "int8_float32", "float32"):
        if choice in supported:
            return choice
    return "float32"


def auto_whisper_model(device: str) -> str:
    """Best model the hardware handles comfortably."""
    if device == "cuda":
        return "large-v3" if detect().vram_gb >= 5.5 else "large-v3-turbo"
    return "small"


def auto_batch_size(device: str) -> int:
    if device == "cpu":
        return 1
    vram = detect().vram_gb
    if vram >= 12:
        return 16
    if vram >= 7:
        return 8
    return 4
