# Third-party notices

LocalScribe's own code is under the MIT License (see `LICENSE`). The Windows release bundles
the components below, each under its own license.

## Models

| Model | Source | License |
|---|---|---|
| Whisper (large-v3, small, …), downloaded on first use | OpenAI, converted to CTranslate2 by SYSTRAN (`Systran/faster-whisper-*`) | MIT |
| pyannote segmentation-3.0 (ONNX export, bundled) | pyannote, via the sherpa-onnx project | MIT |
| TitaNet-Large speaker embeddings (ONNX export, bundled) | NVIDIA NeMo, via the sherpa-onnx project | CC-BY-4.0 |
| pyannote speaker-diarization-community-1 (**not bundled**; each user downloads it with their own Hugging Face token) | pyannote | CC-BY-4.0 |

## Software

| Component | License |
|---|---|
| FFmpeg 7.1 (gyan.dev "essentials" build, shipped by imageio-ffmpeg) | GPL-3.0 |
| PyAV (with its bundled FFmpeg libraries) | BSD-3-Clause / LGPL |
| PySide6 / Qt 6 | LGPL-3.0 |
| PyTorch, torchaudio | BSD-3-Clause / BSD-2-Clause |
| NVIDIA CUDA runtime libraries shipped with PyTorch (cuBLAS, cuDNN, …) | NVIDIA CUDA / cuDNN license (redistributable) |
| CTranslate2, faster-whisper | MIT |
| pyannote.audio | MIT |
| sherpa-onnx | Apache-2.0 |
| OpenCC (Simplified to Traditional Chinese, with its dictionaries) | Apache-2.0 |
| python-sounddevice, with the PortAudio library it ships (playback while proofreading) | MIT / PortAudio license (MIT-style) |
| CFFI | MIT-0 |
| pycparser | BSD-3-Clause |
| ONNX Runtime | MIT |
| Lightning, torchmetrics, huggingface_hub, tokenizers, safetensors, requests, OpenTelemetry | Apache-2.0 |
| NumPy, SciPy, scikit-learn, pandas | BSD-3-Clause |
| python-docx, openpyxl, optuna, einops, PyYAML, asteroid-filterbanks, pytorch-metric-learning, torch-audiomentations, truststore | MIT |
| Matplotlib | Matplotlib license (PSF-based) |
| Pillow | MIT-CMU (HPND) |
| Python 3.11 | PSF License |

### FFmpeg source code

The bundled `ffmpeg` executable is an unmodified build of FFmpeg 7.1 from
https://www.gyan.dev/ffmpeg/builds/. Its source code is available at
https://ffmpeg.org/releases/ffmpeg-7.1.tar.xz, and the build configuration is listed on the
gyan.dev page. LocalScribe runs it as a separate program and does not link against it.

### Qt (LGPL-3.0)

Qt is used as unmodified, dynamically linked libraries (`PySide6\*.dll` in the install folder),
which you may replace with your own builds. Qt source code: https://download.qt.io/official_releases/qt/
