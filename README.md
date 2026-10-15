# LocalScribe：本機逐字稿與語者辨識

把錄音或影片轉成逐字稿，並分辨不同的說話人。**全部在自己的電腦上執行，錄音不會上傳到任何地方。**

*English quick start: see [For colleagues (English)](#for-colleagues-english) below.*

## 功能

- 拖曳或選擇音訊、影片檔（mp3、m4a、wav、flac、mp4、mov、mkv、webm 等），可一次排入多個檔案
- **iPhone 語音備忘錄的 .qta 可直接使用**（iOS 18.2 起的格式）：自動選用檔案內的立體聲 AAC 音軌，避開 Windows 無法解碼的 Apple 空間音訊音軌。副檔名不在清單裡的檔案，只要 ffmpeg 讀得出音訊也會接受
- **轉檔**：把錄音轉成 M4A、MP3、WAV 或 FLAC，方便在其他程式播放或分享（保留錄音標題、日期等資訊，不會覆蓋舊檔）
- **語音辨識**：Whisper（faster-whisper）。有 NVIDIA 顯示卡用 large-v3，沒有就自動改用 small 跑 CPU
- **語者分離**，兩個引擎都免費：
  - **pyannote**（community-1）：比較準，需要一次性取得 Hugging Face token（見下方）
  - **sherpa-onnx**：不需要帳號，沒有 pyannote 模型時自動使用
- **情境預設**：一對一訪談（固定 2 人）、小組會議（2–6 人）、演講課堂（1–5 人）、線上會議錄影（2–8 人，含降噪）
- **輸出格式**（可複選）：Word、純文字、Markdown、SRT、WebVTT、Excel、CSV。每次都會另存一份 `_transcript.json`，之後做校對編輯器時直接讀取
- 不會覆蓋舊檔：同名時自動存成 `xxx_transcript (2).docx`
- 介面：繁體中文／English（設定中切換）

## 速度參考

測試環境：RTX 3070 Ti（8 GB）＋ Ryzen 7 5800X，英文對話錄音。

| 設定 | 58 分鐘錄音實測 |
|---|---|
| 顯示卡、large-v3、sherpa-onnx | 約 12 分鐘（轉錄 4.8 分＋分辨說話人 6.9 分），記憶體約 1.7 GB |
| 只用 CPU、small、sherpa-onnx | 約 22 分鐘（由短檔推算；較舊的筆電可能要 2 倍） |

> 「快速模式」（設定中開啟）在顯示卡上轉錄較快，代價是標點和換人位置稍微不準。安裝 pyannote 後，有顯示卡的電腦會改用 pyannote 分辨說話人，速度會再快一些。

## 下載與安裝

1. 到本頁右側的 **Releases**，下載最新版本的**所有檔案**：`LocalScribe-Setup-x.y.z.exe` 和同名的 `.bin` 檔（GitHub 限制單檔 2 GB，所以安裝程式被分成好幾個檔案）
2. 把它們放在**同一個資料夾**，執行 `.exe`。安裝到使用者資料夾，不需要系統管理員權限（安裝後約 4.6 GB）
3. 開啟 LocalScribe → 把檔案拖進視窗 → 選情境 → 勾輸出格式 → 按「開始轉換」
4. 第一次轉換會自動下載 Whisper 模型（有顯示卡約 3 GB，沒有約 480 MB），之後就完全離線

需求：Windows 10/11 64 位元。有 NVIDIA 顯示卡會快很多，沒有也能用（改跑 CPU）。

> 安裝程式沒有數位簽章（簽章憑證需付費），Windows 可能顯示「Windows 已保護您的電腦」。按「其他資訊」→「仍要執行」即可。

完成後雙擊檔案列可直接開啟逐字稿，右鍵可開啟所在資料夾。

### iPhone 語音備忘錄（.qta）

直接把 .qta 拖進主視窗即可轉錄，不需要先轉檔。若想在 Windows 上播放或傳給別人，按「轉檔…」轉成 M4A 或 MP3；勾選「轉完後加入轉錄清單」可一併轉錄。

### 沒有網路的電腦

把已經下載好模型的電腦上的 `%LOCALAPPDATA%\LocalScribe\models` 整個資料夾複製過去即可（或在「設定 → 模型存放位置」指向該資料夾）。

## pyannote 設定（一次性、免費）

1. 註冊 [Hugging Face](https://huggingface.co/join) 帳號（免費）
2. 開啟 [pyannote/speaker-diarization-community-1](https://huggingface.co/pyannote/speaker-diarization-community-1)，填寫並同意使用條件
3. 到 [Access Tokens](https://huggingface.co/settings/tokens) 建立一組 **Read** 權限的 token
4. 在 LocalScribe 的「設定 → 語者分離」貼上 token，按「下載 pyannote 模型」（約 33 MB）

token 只用來下載，不會被儲存。沒有設定 pyannote 時，程式會自動改用 sherpa-onnx，一樣能分辨說話人。

公開的 Release 不內建 pyannote 模型（它在 Hugging Face 上需要同意條款才能下載）。實驗室內部自行打包時，可設定 `LOCALSCRIBE_BUNDLE_PYANNOTE=1` 把已下載的模型包進去，同事就不用各自申請。

## 隱私

- 所有處理都在本機；網路只用在第一次下載模型
- pyannote.audio 4 預設會傳送使用統計，本程式啟動時已將其關閉（`PYANNOTE_METRICS_ENABLED=false`）
- 紀錄檔位置：`%LOCALAPPDATA%\LocalScribe\localscribe.log`（只有檔名與處理時間，沒有逐字稿內容）

## 已知限制

- 逐字稿仍需校對，特別是人名、專有名詞（可在「設定 → 專有名詞」提示 Whisper）
- 多人同時說話的片段，語者歸屬容易出錯；很短的附和（如 "Right."）若被 Whisper 併進別人的句子，會跟著歸給那個人
- 兩個人聲音非常相近時，sherpa-onnx 可能無法分開；pyannote 在這種情況較好
- 中文目前可能輸出簡體字（繁體轉換等語言專屬調整尚未加入）

## 從原始碼執行（開發用）

```bat
setup.bat
run.bat
```

`setup.bat` 會用 [uv](https://docs.astral.sh/uv/) 在專案內建立 `.venv`（Python 3.11、PyTorch CUDA 12.6 版）。

命令列批次轉換：

```bat
.venv\Scripts\python.exe -m localscribe.cli 錄音1.m4a 錄音2.mp4 -f docx,srt -s 2
```

`-s` 可填 `auto`、人數（如 `2`）或範圍（如 `2-6`）；`--help` 看全部選項。打包後的版本也能用：`LocalScribe.exe --cli ...`（輸出寫到 `%LOCALAPPDATA%\LocalScribe\console.log`）。

測試：

```bat
.venv\Scripts\python.exe -m pytest tests
.venv\Scripts\python.exe scripts\make_test_audio.py   :: 產生有標準答案的合成對話音檔
```

### 打包給同事

```bat
powershell -ExecutionPolicy Bypass -File packaging\build.ps1           :: 產生 dist\LocalScribe\
"%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" packaging\installer.iss  :: 產生安裝程式（setup.exe + .bin）
.venv\Scripts\python.exe packaging\make_zip.py                           :: 或產生免安裝 ZIP
```

選擇性加入的內容（只建議用在不公開的內部版本）：`LOCALSCRIBE_BUNDLE_PYANNOTE=1` 內建 pyannote 模型；`LOCALSCRIBE_BUNDLE_WHISPER=large-v3,small` 內建 Whisper 模型，給沒有網路的電腦使用。

### 程式結構

```
localscribe/
  core/          轉錄流程（不依賴介面）
    media.py       ffmpeg 解碼、挑選音軌（.qta）、音量平衡、降噪
    convert.py     轉檔（M4A / MP3 / WAV / FLAC）
    asr.py         faster-whisper 轉錄（逐字時間戳）
    diarization/   pyannote 與 sherpa-onnx 兩個引擎
    align.py       把每個字對到說話人，修正換人處的邊界誤差
    pipeline.py    串接各步驟、模型快取、顯示卡失敗時改用 CPU
    models.py      模型下載（可續傳）
    transcript.py  逐字稿資料格式（_transcript.json）
  export/        各種輸出格式
  ui/            PySide6 桌面介面
  cli.py         命令列
```

## 授權

程式碼採用 [MIT License](LICENSE)。安裝程式內附的第三方元件與模型（FFmpeg 為 GPL-3.0、Qt 為 LGPL-3.0、TitaNet 模型為 CC-BY-4.0 等）各有其授權，詳見 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。

---

## For colleagues (English)

LocalScribe turns audio and video recordings into transcripts that label who is speaking. Everything runs on your own computer; recordings never leave it.

1. From **Releases**, download every file of the latest version (`LocalScribe-Setup-x.y.z.exe` plus its `.bin` parts; GitHub caps files at 2 GB), put them in one folder, and run the `.exe`. No admin rights needed. The installer is unsigned, so Windows may show "Windows protected your PC": click **More info → Run anyway**.
2. The interface follows your Windows display language. To change it, open **Settings (設定) → Interface language (介面語言)**.
3. Drop files into the window, pick a scenario (interview, group meeting, lecture, online meeting), tick the output formats, and click **Start**.
4. The first run downloads the speech model (about 3 GB with an NVIDIA GPU, 480 MB without). After that it works offline.

Double-click a finished row to open the transcript; right-click for the output folder. Always proofread the result, especially names and overlapping speech.

iPhone Voice Memos (.qta) files work directly. Use **Convert…** to turn recordings into M4A, MP3, WAV or FLAC for playback elsewhere.
