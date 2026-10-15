# LocalScribe

Offline transcription with speaker identification for Windows. LocalScribe turns interviews, meetings, lectures and voice memos into transcripts that show who said what. **Everything runs on your own computer; recordings are never uploaded.**

*中文說明請見下方 [中文說明](#中文說明)。*

## Features

- Drag and drop audio or video (mp3, m4a, wav, flac, mp4, mov, mkv, webm, …) and queue many files at once
- **iPhone Voice Memos (.qta) work directly** (the iOS 18.2+ format). LocalScribe uses the file's stereo AAC track and skips the Apple spatial-audio track that Windows can't decode. Files with other extensions are accepted whenever FFmpeg finds audio in them
- **Converter** to M4A, MP3, WAV or FLAC for playback elsewhere. It keeps the recording's title and date and never overwrites files
- **Speech recognition**: Whisper (faster-whisper). It uses large-v3 on NVIDIA GPUs and small on computers without one
- **Speaker identification**, both free:
  - **pyannote** (community-1): the most accurate; needs a one-time free Hugging Face token (see below)
  - **sherpa-onnx**: built in, no account needed; used whenever pyannote isn't installed
- **Scenario presets**: one-on-one interview (exactly 2 speakers), group meeting (2–6), lecture (1–5), online meeting (2–8, with noise reduction)
- **Exports**, any combination: Word, plain text, Markdown, SRT, WebVTT, Excel, CSV. Every run also saves a `_transcript.json` for future editing tools
- Never overwrites: a repeated run saves `name_transcript (2).docx`
- English or Traditional Chinese interface (follows Windows; change it in Settings)

## Download and install

1. Open **Releases** (right side of this page) and download **every file** of the latest version: `LocalScribe-Setup-x.y.z.exe` and its `.bin` parts. GitHub limits files to 2 GB, so the installer is split.
2. Put them in **one folder** and run the `.exe`. It installs for your user account only (no admin rights needed, about 4.6 GB).
3. The installer isn't code-signed, so Windows may say "Windows protected your PC". Click **More info → Run anyway**.

Requirements: Windows 10/11, 64-bit. An NVIDIA GPU makes it much faster; without one it runs on the CPU.

## Usage

1. Drop files into the window (or click **Add files…**)
2. Pick a scenario, the language and the output formats
3. Click **Start**. The first run downloads the Whisper model (about 3 GB with a GPU, 480 MB without); after that everything works offline
4. Double-click a finished row to open the transcript; right-click to open its folder

**iPhone Voice Memos**: drop .qta files straight in; no conversion is needed. To play or share them on Windows, use **Convert…**, and tick **Add converted files to the transcription list** to transcribe them as well.

**Offline computers**: copy `%LOCALAPPDATA%\LocalScribe\models` from a computer that has already downloaded the models, or point **Settings → Model folder** at it.

## Speed

Measured on an RTX 3070 Ti (8 GB) and a Ryzen 7 5800X with an English conversation:

| Setup | 58-minute recording |
|---|---|
| GPU, large-v3, sherpa-onnx | about 12 min (transcription 4.8 + speakers 6.9), 1.7 GB RAM |
| CPU only, small, sherpa-onnx | about 22 min (estimated from shorter files; older laptops may need twice as long) |

**Fast mode** (Settings) transcribes faster on a GPU, at the cost of slightly worse punctuation and speaker-change placement.

## Optional: pyannote (free, one-time)

1. Create a free [Hugging Face](https://huggingface.co/join) account
2. Open [pyannote/speaker-diarization-community-1](https://huggingface.co/pyannote/speaker-diarization-community-1) and accept the conditions
3. Create a token with **Read** access at [Access Tokens](https://huggingface.co/settings/tokens)
4. In LocalScribe open **Settings → Speaker diarization**, paste the token and click **Download pyannote model** (about 33 MB)

The token is used only for that download and is never stored. Public releases don't bundle pyannote because it is gated on Hugging Face. For an internal build, set `LOCALSCRIBE_BUNDLE_PYANNOTE=1` to include a downloaded copy so colleagues don't need their own token.

## Privacy

- All processing happens locally. The network is used only to download models
- pyannote.audio 4 sends usage telemetry by default; LocalScribe turns it off (`PYANNOTE_METRICS_ENABLED=false`)
- The log file `%LOCALAPPDATA%\LocalScribe\localscribe.log` holds file names and timings, never transcript text

## Known limitations

- Always proofread, especially names and technical terms (add them under **Settings → Names and terms**)
- Overlapping speech is often attributed to the wrong person. A short reply ("Right.") that Whisper merges into another person's sentence goes to that person
- sherpa-onnx may not separate two very similar voices; pyannote does better
- Chinese output may use Simplified characters (language-specific tuning is planned)

## Running from source

```bat
setup.bat
run.bat
```

`setup.bat` uses [uv](https://docs.astral.sh/uv/) to create `.venv` with Python 3.11 and PyTorch (CUDA 12.6).

Batch conversion from the command line:

```bat
.venv\Scripts\python.exe -m localscribe.cli interview.m4a meeting.mp4 -f docx,srt -s 2
```

`-s` accepts `auto`, a number (`2`) or a range (`2-6`); see `--help` for all options. The installed app has the same command line: `LocalScribe.exe --cli ...` (output goes to `%LOCALAPPDATA%\LocalScribe\console.log`).

Tests:

```bat
.venv\Scripts\python.exe -m pytest tests
.venv\Scripts\python.exe scripts\make_test_audio.py   :: synthetic recordings with known speakers
```

### Building the installer

```bat
powershell -ExecutionPolicy Bypass -File packaging\build.ps1               :: builds dist\LocalScribe\
"%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" packaging\installer.iss   :: setup.exe + .bin parts
.venv\Scripts\python.exe packaging\make_zip.py                             :: or a portable ZIP
```

Optional extras, for internal (non-public) builds only: `LOCALSCRIBE_BUNDLE_PYANNOTE=1` bundles the pyannote model, and `LOCALSCRIBE_BUNDLE_WHISPER=large-v3,small` bundles Whisper models for computers without internet.

### Project layout

```
localscribe/
  core/          the pipeline (no UI code)
    media.py       FFmpeg decoding, track selection (.qta), volume levelling, noise reduction
    convert.py     audio conversion (M4A / MP3 / WAV / FLAC)
    asr.py         faster-whisper transcription with word timestamps
    diarization/   pyannote and sherpa-onnx engines
    align.py       assigns words to speakers and fixes boundary errors
    pipeline.py    runs the steps, caches models, falls back to the CPU if the GPU fails
    models.py      resumable model downloads
    transcript.py  transcript format (_transcript.json)
  export/        output formats
  ui/            PySide6 desktop interface
  cli.py         command line
```

## License

The code is under the [MIT License](LICENSE). Bundled third-party components and models have their own licenses (FFmpeg GPL-3.0, Qt LGPL-3.0, TitaNet CC-BY-4.0, …); see [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

---

## 中文說明

LocalScribe 是 Windows 上的本機逐字稿工具，可以把錄音或影片轉成逐字稿並分辨說話人。所有處理都在自己的電腦上完成，錄音不會上傳。

**安裝**：到 Releases 下載最新版本的所有檔案（`.exe` 和 `.bin`），放在同一個資料夾，再執行 `.exe`。不需要系統管理員權限。如果出現「Windows 已保護您的電腦」，按「其他資訊」→「仍要執行」。

**使用**：把檔案拖進視窗，選好情境、語言和輸出格式，按「開始轉換」。第一次轉換會自動下載 Whisper 模型（有顯示卡約 3 GB，沒有約 480 MB），之後就完全離線。要改成中文介面，請到「Settings → Interface language」選「繁體中文」。

**iPhone 語音備忘錄（.qta）**：直接拖進視窗就能轉錄，不用先轉檔。要在 Windows 上播放或分享，可以用「轉檔…」轉成 M4A 或 MP3。

**pyannote（選用、免費）**：註冊 Hugging Face 帳號，到模型頁面同意條款，建立一組 Read token，再到「設定 → 語者分離」貼上並下載。沒有安裝 pyannote 時，程式會自動改用內建的 sherpa-onnx。

**注意**：逐字稿務必校對，特別是人名、專有名詞，以及多人同時說話的段落。中文目前可能輸出簡體字。
