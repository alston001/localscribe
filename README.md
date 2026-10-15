# LocalScribe

Offline transcription with speaker identification for Windows. LocalScribe turns interviews, meetings, lectures and voice memos into transcripts that show who said what. **Everything runs on your own computer; recordings are never uploaded.**

![LocalScribe main window](docs/screenshot.png)

*中文說明請見下方 [中文說明](#中文說明)。*

- [Features](#features)
- [Download and install](#download-and-install)
- [Usage](#usage)
- [Settings](#settings)
- [Output formats](#output-formats)
- [Accuracy and speed](#accuracy-and-speed)
- [Optional: pyannote](#optional-pyannote-free-one-time)
- [Troubleshooting](#troubleshooting)
- [FAQ](#faq)
- [Running from source](#running-from-source)

## Features

- Drag and drop audio or video (mp3, m4a, wav, flac, mp4, mov, mkv, webm, …) and queue many files at once
- **iPhone Voice Memos (.qta) work directly** (the iOS 18.2+ format). LocalScribe uses the file's stereo AAC track and skips the Apple spatial-audio track that Windows can't decode. Files with other extensions are accepted whenever FFmpeg finds audio in them
- **Converter** to M4A, MP3, WAV or FLAC for playback elsewhere. It keeps the recording's title and date and never overwrites files
- **Speech recognition**: Whisper (faster-whisper). It uses large-v3 on NVIDIA GPUs and small on computers without one
- **Speaker identification**, both free:
  - **pyannote** (community-1): the most accurate; needs a one-time free Hugging Face token (see below)
  - **sherpa-onnx**: built in, no account needed; used whenever pyannote isn't installed
- **Scenario presets**: one-on-one interview (exactly 2 speakers), group meeting (2–10), lecture (any number), online meeting (any number, with noise reduction)
- **Exports**, any combination: Word, plain text, Markdown, SRT, WebVTT, Excel, CSV. Every run also saves a `_transcript.json` for future editing tools
- Never overwrites: a repeated run saves `name_transcript (2).docx`
- English or Traditional Chinese interface (follows Windows; change it in Settings)

## Download and install

1. Open **[Releases](https://github.com/alston001/localscribe/releases)** and download **every file** of the latest version: `LocalScribe-Setup-x.y.z.exe` and its `.bin` parts. GitHub limits files to 2 GB, so the installer is split.
2. Put them in **one folder** and run the `.exe`. It installs for your user account only (no admin rights needed).
3. The installer isn't code-signed, so Windows may say "Windows protected your PC". Click **More info → Run anyway**.

**Requirements**

| | Minimum | Recommended |
|---|---|---|
| System | Windows 10 or 11, 64-bit | |
| Disk | 5 GB for the app + 0.5 GB for the CPU model | 5 GB + 3 GB for the GPU model |
| Memory | 8 GB RAM | 16 GB RAM |
| GPU | none (runs on the CPU, much slower) | NVIDIA with 6 GB+ VRAM and a recent driver (CUDA 12) |

## Usage

1. Drop files into the window (or click **Add files…**)
2. Pick a **scenario**, the **language** and the **output formats**
3. Click **Start**. The first run downloads the Whisper model (about 3 GB with a GPU, 480 MB without); after that everything works offline
4. Double-click a finished row to open the transcript; right-click to open its folder, see an error, or run it again

**How it works**: FFmpeg decodes the file to 16 kHz mono → a voice detector finds speech and cuts it into clips of up to 28 s at natural pauses → Whisper transcribes each clip with word timestamps → pyannote or sherpa-onnx works out who spoke when → each word is matched to a speaker, and boundary words that land on the wrong side of a speaker change are pulled back into their sentence → the result is written in every format you picked.

**iPhone Voice Memos**: drop .qta files straight in; no conversion is needed. To play or share them on Windows, use **Convert…**, and tick **Add converted files to the transcription list** to transcribe them as well.

**Offline computers**: copy `%LOCALAPPDATA%\LocalScribe\models` from a computer that has already downloaded the models, or point **Settings → Model folder** at it.

**Command line**: the installed app can also run without a window, e.g. `LocalScribe.exe --cli recording.m4a -f docx,srt -s 2` (output goes to `%LOCALAPPDATA%\LocalScribe\console.log`; `--cli --help` lists all options).

## Settings

Main window:

| Option | What it does |
|---|---|
| Scenario | Fills in the speaker count and audio clean-up for common situations. Changing those by hand switches to *Custom* |
| Language | Language spoken in the recording. *Detect automatically* works too, but naming the language is more reliable |
| Speakers | *Automatic*, *Exactly N* or *Between N and M*. A known count is the single biggest help for speaker identification, but never set a maximum below the real number of voices: on a class with 7 voices, a cap of 5 split the lecturer into two speakers |
| Even out volume | Levels quiet and loud voices (far from the microphone, remote callers). Used for speech recognition only; speaker identification always hears the original audio |
| Reduce noise | Mild background-noise reduction. Leave it off for clean recordings |
| Output formats / Save to | Which files to write, and where |

Settings dialog:

| Option | What it does |
|---|---|
| Interface language | English or Traditional Chinese |
| Speaker label | The word used in transcripts, e.g. "Speaker" gives Speaker 1, Speaker 2 |
| Model | *Automatic* picks large-v3 on a GPU and small on a CPU. large-v3-turbo is much faster with slightly lower accuracy |
| Device | *Automatic*, NVIDIA GPU or CPU. If the GPU fails, Automatic switches to the CPU by itself |
| Fast mode | Batched decoding: faster on a GPU, but punctuation and speaker changes are slightly less accurate |
| Names and terms | Comma-separated names and jargon (e.g. `Dr. Patel, NVivo`) to help Whisper spell them |
| Speaker diarization engine | *Automatic* uses pyannote when it is installed, otherwise sherpa-onnx |
| Model folder | Where models are stored and downloaded |

## Output formats

| Format | Contents |
|---|---|
| Word (.docx) | One paragraph per speaker turn with a coloured speaker name and timestamp, page numbers, recording details |
| Plain text (.txt) | `[00:01:23] Speaker 1: …` per turn (timestamps optional) |
| Markdown (.md) | Same as text, formatted for Markdown viewers |
| SRT / WebVTT | Subtitles of up to 2 lines, with the speaker named when the speaker changes |
| Excel (.xlsx) / CSV | One row per sentence: start, end, speaker, text. Handy for coding qualitative data |
| JSON (always) | Every word with its time, confidence and speaker, for future editing tools |

## Accuracy and speed

Always proofread. Speech recognition errors cluster around names, technical terms and overlapping speech.

**A real recording.** We transcribed a 78-minute classroom recording with several speakers and compared the result with the transcript that iPhone Voice Memos produced for the same file. Neither transcript is ground truth. The two agreed on about 88% of the words. In 60 sampled passages where they differed, LocalScribe's wording fit the context better far more often, especially for technical terms (it wrote "chatbot", "COBOL", "embeddings" where the other had misspellings or unrelated words). The phone's transcript has no speaker labels or timestamps. LocalScribe adds both, but nobody has checked its speaker labels against the audio, so spot-check them.

**Synthetic tests** (two recorded voices, known script): 100% of words attributed to the right speaker for a two-person interview and a three-person panel.

**Speed** on an RTX 3070 Ti (8 GB) with a Ryzen 7 5800X:

| Recording | Setup | Time |
|---|---|---|
| 78 min classroom | GPU, large-v3, pyannote | about 8 min (speech 6.2 + speakers 1.5) |
| 58 min conversation | GPU, large-v3, sherpa-onnx | about 12 min (speech 4.8 + speakers 6.9) |
| 1 hour | CPU only, small, sherpa-onnx | about 22 min (estimated; older laptops may take twice as long) |

## Optional: pyannote (free, one-time)

pyannote separates similar voices better than the built-in engine, and it is much faster on a GPU.

1. Create a free [Hugging Face](https://huggingface.co/join) account
2. Open [pyannote/speaker-diarization-community-1](https://huggingface.co/pyannote/speaker-diarization-community-1) and accept the conditions
3. Create a token with **Read** access at [Access Tokens](https://huggingface.co/settings/tokens)
4. In LocalScribe open **Settings → Speaker diarization**, paste the token and click **Download pyannote model** (about 33 MB)

The token is used only for that download and is never stored. Public releases don't bundle pyannote because it is gated on Hugging Face. For an internal build, set `LOCALSCRIBE_BUNDLE_PYANNOTE=1` to include a downloaded copy so colleagues don't need their own token.

## Privacy

- All processing happens locally. The network is used only to download models
- pyannote.audio 4 sends usage telemetry by default; LocalScribe turns it off (`PYANNOTE_METRICS_ENABLED=false`)
- The log file `%LOCALAPPDATA%\LocalScribe\localscribe.log` holds file names (not folders) and timings, never transcript text. The technical details of an unexpected error can include a file's location, so check them before you share the log
- `_transcript.json` and the Excel export store the recording's file name, not its folder

## Troubleshooting

| Problem | What to do |
|---|---|
| "Windows protected your PC" when installing | The installer isn't code-signed. Click **More info → Run anyway** |
| Installer says the path is too long | Windows limits paths to 260 characters. Install to a shorter folder such as `C:\LocalScribe` |
| The status bar shows the CPU although you have an NVIDIA GPU | Update the NVIDIA driver (CUDA 12 support is required), then restart LocalScribe |
| Very slow | Without a GPU, expect about 20+ minutes per hour of audio. Try **Settings → Model → small**, or turn on Fast mode if you have a GPU |
| A file fails with "can't be decoded" | The audio codec isn't supported. Convert it with another tool, or check that the file plays |
| pyannote download: "token rejected" | Copy the whole token (it starts with `hf_`) and make sure it has Read access |
| pyannote download: "no access yet" | Sign in to Hugging Face and accept the conditions on the model page first |
| Wrong number of speakers | Set the exact number under **Speakers**, or install pyannote |
| A speaker's short replies are attributed to someone else | Common when people overlap. Proofread those spots; pyannote helps |
| Running from source: "No Python at …" | `.venv` was created with a Python that isn't installed. Run `setup.bat` again (see below) |

Logs for bug reports: `%LOCALAPPDATA%\LocalScribe\localscribe.log`.

## FAQ

**Is it really offline?** Yes. After the models are downloaded, you can disconnect from the internet.

**Which languages?** Whisper understands about 99 languages; pick one in the Language menu or use automatic detection. The interface is English or Traditional Chinese.

**Can I name the speakers?** Version 0.1 labels them Speaker 1, 2, … (the label word is configurable). Use Find and Replace in Word, or edit the `.json`; a built-in proofreading editor is planned.

**Where are my files?** Next to the original recording (or in the folder you chose), named `<recording>_transcript.<ext>`.

**How do I uninstall?** Windows Settings → Apps → LocalScribe → Uninstall. Downloaded models stay in `%LOCALAPPDATA%\LocalScribe`; delete that folder to remove them too.

## Running from source

```bat
setup.bat
run.bat
```

`setup.bat` uses [uv](https://docs.astral.sh/uv/) to create `.venv` with Python 3.11 and PyTorch (CUDA 12.6). If `run.bat` reports a missing Python, run `uv python install 3.11` or `setup.bat` again.

Batch conversion from the command line:

```bat
.venv\Scripts\python.exe -m localscribe.cli interview.m4a meeting.mp4 -f docx,srt -s 2
```

`-s` accepts `auto`, a number (`2`) or a range (`2-6`); see `--help` for all options.

Tests:

```bat
.venv\Scripts\python.exe -m pytest tests
.venv\Scripts\python.exe scripts\make_test_audio.py   :: synthetic recordings with known speakers
```

### Building the installer

```bat
powershell -ExecutionPolicy Bypass -File packaging\build.ps1               :: builds dist\LocalScribe\
"%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" packaging\installer.iss   :: setup.exe + .bin parts
.venv\Scripts\python.exe packaging\make_zip.py [dist]                      :: or a portable ZIP
```

Optional extras, for internal (non-public) builds only: `LOCALSCRIBE_BUNDLE_PYANNOTE=1` bundles the pyannote model, and `LOCALSCRIBE_BUNDLE_WHISPER=large-v3,small` bundles Whisper models for computers without internet.

### Project layout

```
localscribe/
  core/          the pipeline (no UI code)
    media.py       FFmpeg decoding, track selection (.qta), volume levelling, noise reduction
    convert.py     audio conversion (M4A / MP3 / WAV / FLAC)
    asr.py         speech clips + faster-whisper transcription with word timestamps
    diarization/   pyannote and sherpa-onnx engines
    align.py       assigns words to speakers and fixes boundary errors
    pipeline.py    runs the steps, caches models, falls back to the CPU if the GPU fails
    models.py      resumable model downloads
    transcript.py  transcript format (_transcript.json)
  export/        output formats
  ui/            PySide6 desktop interface
  cli.py         command line
```

See [CHANGELOG.md](CHANGELOG.md) for what changed in each version.

## License

The code is under the [MIT License](LICENSE). Bundled third-party components and models have their own licenses (FFmpeg GPL-3.0, Qt LGPL-3.0, TitaNet CC-BY-4.0, …); see [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

---

## 中文說明

LocalScribe 是 Windows 上的本機逐字稿工具，可以把錄音或影片轉成逐字稿並分辨說話人。所有處理都在自己的電腦上完成，錄音不會上傳。

**安裝**：到 [Releases](https://github.com/alston001/localscribe/releases) 下載最新版本的所有檔案（`.exe` 和 `.bin`），放在同一個資料夾，再執行 `.exe`。不需要系統管理員權限。如果出現「Windows 已保護您的電腦」，按「其他資訊」→「仍要執行」。有 NVIDIA 顯示卡會快很多，沒有也能用。

**使用**：把檔案拖進視窗，選好情境、語言和輸出格式，按「開始轉換」。第一次轉換會自動下載 Whisper 模型（有顯示卡約 3 GB，沒有約 480 MB），之後就完全離線。完成後雙擊該列可開啟逐字稿。要改成中文介面，請到「Settings → Interface language」選「繁體中文」。

**情境**：一對一訪談（固定 2 人）、小組會議（2–10 人）、演講課堂（自動判斷人數）、線上會議（自動判斷人數，含降噪）。知道確切人數時，直接指定人數，分辨說話人的效果最好；但不要把上限設得比實際人數少，否則同一個人可能被拆成兩位。

**iPhone 語音備忘錄（.qta）**：直接拖進視窗就能轉錄，不用先轉檔。要在 Windows 上播放或分享，可以用「轉檔…」轉成 M4A 或 MP3。

**pyannote（選用、免費）**：註冊 Hugging Face 帳號，到模型頁面同意條款，建立一組 Read token，再到「設定 → 語者分離」貼上並下載。分辨聲音相近的人比內建的 sherpa-onnx 準，用顯示卡也快很多。沒有安裝時會自動改用 sherpa-onnx。

**準確度**：用一份 78 分鐘的上課錄音測試，和 iPhone 語音備忘錄內建的逐字稿比較（兩邊都不當作標準答案），約 88% 的字一致；不一致的地方，LocalScribe 在專有名詞上通常比較合理。逐字稿務必校對，特別是人名、專有名詞，以及多人同時說話的段落。中文目前可能輸出簡體字。

**疑難排解**：遇到問題時，請參考上方英文的 [Troubleshooting](#troubleshooting) 表格；回報問題時可附上 `%LOCALAPPDATA%\LocalScribe\localscribe.log`（記錄檔只有檔名與耗時，不含逐字稿內容；但未預期錯誤的技術細節可能含有檔案位置，分享前請先檢查）。
