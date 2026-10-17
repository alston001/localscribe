"""Interface strings in Traditional Chinese and English.

Add a language by adding a column to every entry and a code to LANGUAGES.
"""

from __future__ import annotations

import locale

LANGUAGES = {"zh_TW": "繁體中文", "en": "English"}
_COLUMN = {"zh_TW": 0, "en": 1}
_current = "en"

STRINGS: dict[str, tuple[str, str]] = {
    # main window
    "app_subtitle": ("逐字稿與語者辨識", "Transcription & speaker identification"),
    "add_files": ("加入檔案…", "Add files…"),
    "remove": ("移除", "Remove"),
    "clear_finished": ("清除已完成", "Clear finished"),
    "settings": ("設定", "Settings"),
    "col_file": ("檔案", "File"),
    "col_length": ("長度", "Length"),
    "col_status": ("狀態", "Status"),
    "col_progress": ("進度", "Progress"),
    "drop_hint": ("把音訊或影片檔拖曳到這裡\n或按「加入檔案…」",
                  "Drop audio or video files here\nor click “Add files…”"),
    "file_dialog_title": ("選擇音訊或影片檔", "Choose audio or video files"),
    "file_filter_media": ("音訊與影片", "Audio and video"),
    "file_filter_all": ("所有檔案", "All files"),
    "unsupported_files": ("以下檔案不是支援的影音格式，已略過：\n{names}",
                          "These files are not a supported audio/video format and were skipped:\n{names}"),
    # converter
    "convert": ("轉檔…", "Convert…"),
    "convert_title": ("轉換音訊格式", "Convert audio format"),
    "convert_intro": (
        "把錄音轉成常見格式，方便在其他程式播放或分享，例如 iPhone 語音備忘錄的 .qta 轉成 .m4a。\n"
        "轉錄不需要先轉檔：.qta 等格式可以直接拖進主視窗。",
        "Converts recordings to common formats so other programs can play or share them, "
        "e.g. iPhone Voice Memos .qta to .m4a.\n"
        "You don't need to convert before transcribing: .qta and similar files can go straight into the main window."),
    "convert_drop_hint": ("把要轉檔的檔案拖曳到這裡", "Drop files to convert here"),
    "convert_format": ("輸出格式", "Format"),
    "cfmt_m4a": ("M4A（AAC）：檔案小、相容性高", "M4A (AAC): small, widely compatible"),
    "cfmt_mp3": ("MP3：幾乎所有裝置都能播放", "MP3: plays almost everywhere"),
    "cfmt_wav": ("WAV：無壓縮，檔案較大", "WAV: uncompressed, large"),
    "cfmt_flac": ("FLAC：無損壓縮", "FLAC: lossless"),
    "convert_add_queue": ("轉完後加入轉錄清單", "Add converted files to the transcription list"),
    "convert_start": ("開始轉檔", "Convert"),
    "convert_done": ("轉檔完成：{ok} 個成功，{bad} 個失敗。", "Conversion finished: {ok} succeeded, {bad} failed."),
    "convert_stopped": ("已停止轉檔：{ok} 個成功，{bad} 個失敗。", "Conversion stopped: {ok} succeeded, {bad} failed."),
    "convert_warn_note": ("其中 {n} 個有提醒，請看清單。", "Warnings for {n}; see the list."),
    "close": ("關閉", "Close"),
    "cancel": ("取消", "Cancel"),
    # statuses
    "st_waiting": ("等待中", "Waiting"),
    "st_decode": ("讀取音訊", "Reading audio"),
    "st_download": ("下載模型", "Downloading model"),
    "st_load": ("載入模型", "Loading model"),
    "st_transcribe": ("轉錄中", "Transcribing"),
    "st_diarize": ("分辨說話人", "Identifying speakers"),
    "st_export": ("匯出檔案", "Saving files"),
    "st_done": ("完成", "Done"),
    "st_done_warn": ("完成（{n} 項提醒）", "Done ({n} warning(s))"),
    "st_failed": ("失敗", "Failed"),
    "st_stopped": ("已停止", "Stopped"),
    # options panel
    "options": ("轉換設定", "Options"),
    "scenario": ("情境", "Scenario"),
    "preset_interview": ("一對一訪談", "One-on-one interview"),
    "preset_focus_group": ("小組會議／焦點團體", "Group meeting / focus group"),
    "preset_lecture": ("演講／課堂", "Lecture / class"),
    "preset_online": ("線上會議錄影", "Online meeting recording"),
    "preset_custom": ("自訂", "Custom"),
    "preset_interview_tip": ("固定 2 位說話人", "Exactly 2 speakers"),
    "preset_focus_group_tip": ("自動判斷 2–10 人，平衡音量", "Detects 2–10 speakers, evens out volume"),
    "preset_lecture_tip": ("自動判斷人數，平衡音量", "Detects how many people speak, evens out volume"),
    "preset_online_tip": ("自動判斷人數，平衡音量並降噪",
                          "Detects how many people speak, evens out volume, reduces noise"),
    "language": ("語言", "Language"),
    "lang_auto": ("自動偵測", "Detect automatically"),
    "speakers": ("說話人數", "Speakers"),
    "spk_auto": ("自動判斷", "Automatic"),
    "spk_exact": ("固定人數", "Exactly"),
    "spk_range": ("人數範圍", "Between"),
    "spk_to": ("到", "and"),
    "normalize": ("平衡音量", "Even out volume"),
    "normalize_tip": ("找出原始音訊聽不到的小聲語音（離麥克風遠、線上的人），只把那幾段用平衡音量後的音訊補轉；"
                      "其餘照原始音訊轉錄，術語和換人的位置比較準",
                      "Finds quiet voices the original audio misses (far from the mic, remote callers) and "
                      "transcribes just those stretches from a levelled copy; the rest uses the original, which "
                      "keeps terms and speaker changes more accurate"),
    "denoise": ("降低雜音", "Reduce noise"),
    "denoise_tip": ("減少背景雜音；錄音乾淨時建議關閉", "Reduces background noise; leave off for clean recordings"),
    "formats": ("輸出格式", "Output formats"),
    "fmt_docx": ("Word (.docx)", "Word (.docx)"),
    "fmt_txt": ("純文字 (.txt)", "Plain text (.txt)"),
    "fmt_md": ("Markdown (.md)", "Markdown (.md)"),
    "fmt_srt": ("字幕 SRT (.srt)", "Subtitles SRT (.srt)"),
    "fmt_vtt": ("字幕 WebVTT (.vtt)", "Subtitles WebVTT (.vtt)"),
    "fmt_xlsx": ("Excel 表格 (.xlsx)", "Excel (.xlsx)"),
    "fmt_csv": ("CSV 表格 (.csv)", "CSV (.csv)"),
    "timestamps": ("包含時間戳記", "Include timestamps"),
    "mark_uncertain": ("標記不確定的字詞", "Mark unsure words"),
    "mark_uncertain_tip": ("標出 Whisper 沒把握、可能聽錯的字，方便回去重聽：Word 以黃色標示，txt 和 md 在字後加 (?)，"
                           "Excel 和 CSV 多一欄列出。字幕不標記。很有把握卻聽錯的字不會被標出。",
                           "Marks words Whisper was unsure of, so you know where to listen again: highlighted in "
                           "Word, followed by (?) in txt and md, listed in an extra column in Excel and CSV. "
                           "Subtitles stay unmarked. A word misheard with confidence is not marked."),
    "save_to": ("儲存位置", "Save to"),
    "save_same": ("與原檔相同的資料夾", "Same folder as the original"),
    "save_custom": ("指定資料夾", "This folder"),
    "choose": ("選擇…", "Choose…"),
    "start": ("開始轉換", "Start"),
    "stop": ("停止", "Stop"),
    "stopping": ("正在停止…", "Stopping…"),
    "show_log": ("紀錄", "Log"),
    # status bar
    "detecting": ("正在偵測硬體…", "Detecting hardware…"),
    "sb_device": ("運算：{v}", "Device: {v}"),
    "sb_model": ("轉錄模型：{v}", "Model: {v}"),
    "sb_diarizer": ("語者分離：{v}", "Diarization: {v}"),
    "cpu_only": ("CPU（未偵測到 NVIDIA 顯示卡）", "CPU (no NVIDIA GPU found)"),
    # row menu
    "open_folder": ("開啟輸出資料夾", "Open output folder"),
    "open_transcript": ("開啟逐字稿", "Open transcript"),
    "run_again": ("重新轉換", "Run again"),
    "show_error": ("顯示錯誤訊息", "Show error"),
    # messages
    "no_files": ("請先加入要轉換的檔案。", "Add some files to convert first."),
    "no_formats": ("請至少勾選一種輸出格式。", "Choose at least one output format."),
    "no_folder": ("請選擇儲存的資料夾。", "Choose a folder to save to."),
    "all_done": ("全部完成：{ok} 個成功，{bad} 個失敗。", "Finished: {ok} succeeded, {bad} failed."),
    "still_stopping": ("仍在停止目前的工作，請稍候再關閉。", "Still stopping the current work. Try closing again in a moment."),
    "confirm_quit": ("正在轉錄中。關閉程式會中斷目前的工作，確定要關閉嗎？",
                     "A transcription is running. Closing will stop it. Close anyway?"),
    "error_title": ("發生錯誤", "Something went wrong"),
    # settings dialog
    "general": ("一般", "General"),
    "ui_language": ("介面語言", "Interface language"),
    "speaker_label": ("說話人標籤", "Speaker label"),
    "speaker_label_tip": ("例如填 Speaker 會顯示成 Speaker 1、Speaker 2",
                          "“Speaker” becomes Speaker 1, Speaker 2, …"),
    "subtitle_speakers": ("字幕中顯示說話人", "Show speaker names in subtitles"),
    "transcription": ("轉錄", "Transcription"),
    "model": ("模型", "Model"),
    "model_auto": ("自動（依硬體選擇）", "Automatic (based on your hardware)"),
    "model_large-v3": ("large-v3：最準確（3.1 GB）", "large-v3: most accurate (3.1 GB)"),
    "model_large-v3-turbo": ("large-v3-turbo：快很多、稍不準（1.6 GB）",
                             "large-v3-turbo: much faster, slightly less accurate (1.6 GB)"),
    "model_medium": ("medium（1.5 GB）", "medium (1.5 GB)"),
    "model_small": ("small：適合沒有顯示卡的電腦（480 MB）", "small: good for computers without a GPU (480 MB)"),
    "model_base": ("base：最快、最不準（150 MB）", "base: fastest, least accurate (150 MB)"),
    "device": ("運算裝置", "Device"),
    "device_auto": ("自動", "Automatic"),
    "device_cuda": ("NVIDIA 顯示卡 (CUDA)", "NVIDIA GPU (CUDA)"),
    "device_cpu": ("CPU", "CPU"),
    "hotwords": ("專有名詞", "Names and terms"),
    "hotwords_tip": ("幫助 Whisper 拼對人名、地名或術語，用逗號分隔（選填）",
                     "Helps Whisper spell names and jargon correctly; separate with commas (optional)"),
    "hotwords_placeholder": ("例如：Dr. Patel, NVivo, MATLAB", "e.g. Dr. Patel, NVivo, MATLAB"),
    # word banks: picker in the main window, editor, check before a run
    "vocabulary": ("詞庫", "Word bank"),
    "vocabulary_tip": ("專有名詞清單（例如一個主題一個），幫助 Whisper 拼對術語。只在錄音真的會講到這些詞時才選，"
                       "否則選「不使用」。設定裡的「專有名詞」也會一起使用",
                       "Technical terms, e.g. one bank per topic, to help Whisper spell jargon. Pick one only when the "
                       "recording uses its terms; otherwise choose None. Names and terms from Settings are added as well"),
    "vocab_none": ("不使用", "None"),
    "vocab_search": ("搜尋", "Search"),
    "vocab_no_match": ("沒有符合的詞庫", "No matching word bank"),
    "vocab_new": ("＋ 新增詞庫…", "+ New word bank…"),
    "vocab_edit": ("編輯", "Edit"),
    "vocab_delete": ("刪除", "Delete"),
    "vocab_term_count": ("{n} 個詞", "{n} term(s)"),
    "vocab_new_title": ("新增詞庫", "New word bank"),
    "vocab_edit_title": ("編輯詞庫", "Edit word bank"),
    "vocab_name": ("名稱", "Name"),
    "vocab_name_placeholder": ("例如：NLP 課、實驗室會議", "e.g. NLP class, Lab meeting"),
    "vocab_terms": ("詞彙", "Terms"),
    "vocab_use_hint": ("只在錄音真的會講到這些詞時才選這個詞庫，否則選「不使用」。詞彙和內容無關時沒有幫助，"
                       "Whisper 還可能把它們寫進沒說的地方，而且轉錄會變慢（測試中慢三到六成）。",
                       "Pick this bank only for recordings that use its terms; otherwise choose None. Unrelated terms "
                       "don't help, Whisper may write them where they weren't said, and transcription is slower "
                       "(30–60% in tests)."),
    "vocab_terms_hint": ("一行一個詞，也可以直接貼上用逗號分隔的清單；空白行和重複的詞會自動略過。",
                         "One term per line, or paste a comma-separated list. Empty lines and duplicates are ignored."),
    "vocab_tokens": ("{terms} 個詞，{n} / {limit} 個 token", "{terms} term(s), {n} / {limit} tokens"),
    "vocab_tokens_estimate": ("{terms} 個詞，約 {n} / {limit} 個 token（估計值）",
                              "{terms} term(s), about {n} / {limit} tokens (estimate)"),
    "vocab_estimate_tip": ("精確計數需要所選 Whisper 模型的 tokenizer，會和模型一起下載。",
                           "Exact counts need the chosen Whisper model's tokenizer, which comes with the model download."),
    "vocab_with_hotwords": ("加上設定裡的「專有名詞」：{n} / {limit} 個 token",
                            "With Names and terms from Settings: {n} / {limit} tokens"),
    "vocab_over_limit": ("Whisper 最多只讀 {limit} 個 token，超過的詞不會被使用。",
                         "Whisper reads at most {limit} tokens; terms past that are left out."),
    "vocab_save": ("儲存", "Save"),
    "vocab_name_missing": ("請輸入詞庫名稱。", "Enter a name for the word bank."),
    "vocab_name_taken": ("已經有名為「{name}」的詞庫。", "There is already a word bank called “{name}”."),
    "vocab_delete_confirm": ("要刪除詞庫「{name}」嗎？這個動作無法復原。", "Delete the word bank “{name}”? This can't be undone."),
    "vocab_save_failed": ("無法儲存詞庫：{detail}", "Could not save the word banks: {detail}"),
    "vocab_dropped": ("Whisper 最多只讀 {limit} 個 token 的詞彙（詞庫加上設定裡的「專有名詞」）。以下 {n} 個詞放不下，不會被使用：",
                      "Whisper reads at most {limit} tokens of terms (the word bank plus Names and terms from "
                      "Settings). These {n} term(s) don't fit and will be left out:"),
    "vocab_dropped_estimate": ("Whisper 最多只讀 {limit} 個 token 的詞彙（詞庫加上設定裡的「專有名詞」）。依估計，以下 {n} 個詞可能放不下：",
                               "Whisper reads at most {limit} tokens of terms (the word bank plus Names and terms "
                               "from Settings). By an estimate, these {n} term(s) may not fit:"),
    "vocab_dropped_more": ("…另外還有 {n} 個", "… and {n} more"),
    "vocab_dropped_question": ("要直接開始，還是先回去刪減詞彙？", "Start anyway, or go back and shorten the list?"),
    "vocab_start_anyway": ("仍要開始", "Start anyway"),
    "vocab_go_back": ("返回修改", "Go back"),
    "diarization": ("語者分離", "Speaker diarization"),
    "engine": ("引擎", "Engine"),
    "engine_auto": ("自動（有 pyannote 就用 pyannote）", "Automatic (pyannote when installed)"),
    "engine_pyannote": ("pyannote：較準確", "pyannote: more accurate"),
    "engine_sherpa": ("sherpa-onnx：不需帳號", "sherpa-onnx: no account needed"),
    "pyannote_installed": ("pyannote 模型：已安裝", "pyannote model: installed"),
    "pyannote_missing": ("pyannote 模型：尚未安裝", "pyannote model: not installed"),
    "pyannote_help": (
        "pyannote 完全免費，只需做一次：\n"
        "1. 註冊 Hugging Face 帳號（免費）\n"
        "2. 開啟模型頁面，按下同意使用條款\n"
        "3. 建立一組 Read 權限的 token，貼到下面再按下載\n"
        "token 只用來下載，不會被儲存。",
        "pyannote is free. One-time setup:\n"
        "1. Create a free Hugging Face account\n"
        "2. Open the model page and accept the conditions\n"
        "3. Create a token with Read access, paste it below, and click Download\n"
        "The token is only used for this download and is not saved."),
    "open_model_page": ("開啟模型頁面", "Open model page"),
    "create_token": ("建立 token", "Create a token"),
    "download_pyannote": ("下載 pyannote 模型", "Download pyannote model"),
    "downloading": ("下載中… {v}", "Downloading… {v}"),
    "pyannote_ok": ("pyannote 模型安裝完成。", "The pyannote model is installed."),
    "models_folder": ("模型存放位置", "Model folder"),
    "open": ("開啟", "Open"),
    "settings_restart_note": ("變更會在下一個檔案開始時生效。", "Changes apply from the next file."),
    "updates": ("更新", "Updates"),
    "upd_auto": ("開啟程式時檢查新版本（每天最多一次）", "Check for a new version at start (at most once a day)"),
    "upd_auto_tip": ("只會從 GitHub 讀取一個版本資訊檔，不會傳送你的檔案或個人資料；GitHub 只看得到任何下載都有的資訊，"
                     "例如 IP 位址和 LocalScribe 的版本。",
                     "Reads one version file from GitHub. None of your files or personal data is sent; GitHub sees "
                     "only what any download shows, such as your IP address and LocalScribe's version."),
    "upd_check_now": ("立即檢查", "Check now"),
    "upd_checking": ("正在檢查…", "Checking…"),
    "upd_version": ("目前版本：{version}", "This is version {version}."),
    "upd_latest": ("已是最新版本（{version}）。", "You have the latest version ({version})."),
    "upd_found": ("有新版本 {version}：關閉設定後，可以在主視窗上方更新。",
                  "Version {version} is available: update from the top of the main window once Settings is closed."),
    # update strip in the main window
    "upd_available": ("有新版本：LocalScribe {version}（下載 {size}）。", "LocalScribe {version} is available ({size} download)."),
    "upd_available_manual": ("有新版本：LocalScribe {version}。", "LocalScribe {version} is available."),
    "upd_downloading": ("正在下載 LocalScribe {version}… {progress}", "Downloading LocalScribe {version}… {progress}"),
    "upd_verifying": ("正在檢查 LocalScribe {version} 的安裝檔… {progress}",
                      "Checking LocalScribe {version} before installing… {progress}"),
    "upd_stopping": ("正在停止下載…", "Stopping the download…"),
    "upd_ready": ("LocalScribe {version} 已下載完成，重新啟動就會安裝。", "LocalScribe {version} is downloaded. Restart to install it."),
    "upd_failed": ("無法下載更新：{detail}", "Could not download the update: {detail}"),
    "upd_whats_new": ("更新內容", "What's new"),
    "upd_update": ("更新", "Update"),
    "upd_restart": ("立即重新啟動", "Restart now"),
    "upd_retry": ("重試", "Retry"),
    "upd_page": ("下載頁面", "Download page"),
    "upd_later": ("稍後", "Later"),
    "upd_busy": ("轉錄完成後才能重新啟動。", "You can restart once the transcription finishes."),
    "upd_done": ("已更新到 LocalScribe {version}。", "Updated to LocalScribe {version}."),
    # errors raised by the pipeline (UserError keys)
    "err_hf_token_invalid": ("Hugging Face 拒絕了這個 token，請確認有完整複製（以 hf_ 開頭）。",
                             "Hugging Face rejected the token. Check that you copied all of it (it starts with hf_)."),
    "err_hf_terms": ("還沒有取得模型使用權。請登入 Hugging Face，到 {url} 按下同意條款後再試一次。",
                     "You don't have access to the model yet. Sign in to Hugging Face, accept the conditions at {url}, then try again."),
    "err_hf_token_missing": ("請先貼上 Hugging Face token。", "Paste your Hugging Face token first."),
    "err_network": ("網路連線失敗：{detail}", "Network error: {detail}"),
    "err_download_incomplete": ("{file} 下載不完整，請再試一次。", "Download of {file} was incomplete. Please try again."),
    "err_download_corrupt": ("{file} 下載後檢查碼不符，已刪除，請再試一次。",
                             "{file} failed its checksum after downloading and was deleted. Please try again."),
    "err_size_unknown": ("伺服器沒有提供 {file} 的檔案大小，無法確認下載完整，請稍後再試。",
                         "The server didn't report the size of {file}, so a complete download can't be confirmed. Please try again later."),
    "err_unsafe_path": ("模型清單裡有不安全的檔案路徑（{file}），已停止下載。",
                        "The model listing has an unsafe file path ({file}), so the download was stopped."),
    "err_insecure_endpoint": ("HF_ENDPOINT（{url}）不是 https，為了保護 token 已停止。",
                              "HF_ENDPOINT ({url}) isn't https, so the token was not sent."),
    "err_unknown_model": ("未知的模型：{name}", "Unknown model: {name}"),
    "err_decode": ("無法讀取這個檔案：{detail}", "Could not read this file: {detail}"),
    "err_no_audio": ("這個檔案裡沒有可用的音訊。", "This file has no usable audio."),
    "err_no_speech": ("這個檔案裡沒有辨識到語音。", "No speech was found in this file."),
    "err_pyannote_missing": ("尚未安裝 pyannote 模型。請到「設定」下載，或把引擎改成 sherpa-onnx。",
                             "The pyannote model isn't installed. Download it in Settings or switch the engine to sherpa-onnx."),
    "err_transcript_newer": ("這份逐字稿來自較新版本的 LocalScribe（格式 {version}），請更新程式後再開啟。",
                             "This transcript comes from a newer LocalScribe (format {version}). Update the app to open it."),
    "err_write": ("無法寫入檔案：{path}", "Cannot write the file: {path}"),
    "err_codec": ("這個檔案的音訊編碼（{detail}）無法解碼。", "This file's audio codec ({detail}) can't be decoded."),
    "err_convert": ("轉檔失敗：{detail}", "Conversion failed: {detail}"),
    "err_unexpected": ("發生未預期的錯誤：{detail}", "Unexpected error: {detail}"),
    "err_update_info": ("更新資訊有誤（{detail}），請稍後再試。", "The update information is invalid ({detail}). Please try again later."),
    "err_update_missing": ("GitHub 上最新的版本沒有附上更新資訊（latest.json），請稍後再試，或到下載頁面看看。",
                           "The newest release on GitHub has no update information (latest.json). Try again later, "
                           "or look at the download page."),
    "err_update_space": ("磁碟空間不足：更新需要 {need}，只剩 {free}。",
                         "Not enough disk space: the update needs {need} and {free} is free."),
    "err_update_launch": ("無法啟動安裝程式：{detail}", "Could not start the installer: {detail}"),
    # warnings: the file finished, but the result may be worse than usual
    "warn_partial_decode": ("檔案可能已損毀：只讀到 {decoded}，原本應有 {expected}。",
                            "The file may be damaged: only {decoded} of {expected} could be read."),
    "warn_gpu_fallback": ("顯示卡執行失敗，已改用 CPU（較慢）。", "The GPU failed, so this ran on the CPU (slower)."),
    "warn_cuda_unavailable": ("設定指定使用顯示卡，但找不到可用的 NVIDIA 顯示卡，已改用 CPU。",
                              "Settings ask for the GPU, but no usable NVIDIA GPU was found, so this ran on the CPU."),
    "warn_no_turns": ("沒有分辨出說話人，全部標成同一人。", "No speakers could be told apart, so everything is labeled as one speaker."),
    "warn_fewer_speakers": ("只分辨出 {found} 位說話人，少於指定的 {requested} 位。",
                            "Only {found} speaker(s) were found, fewer than the {requested} requested."),
    "warn_lost_speech": ("{times} 偵測到說話聲，卻沒有轉出任何文字，請聽一下是否有遺漏。",
                         "No text came out for {times}, although speech was detected there. "
                         "Please listen to check whether something is missing."),
    # export headings
    "exp_source": ("原始檔案", "Source file"),
    "exp_date": ("轉錄日期", "Transcribed"),
    "exp_duration": ("長度", "Duration"),
    "exp_speakers": ("說話人", "Speakers"),
    "exp_model": ("模型", "Model"),
    "exp_start": ("開始", "Start"),
    "exp_end": ("結束", "End"),
    "exp_speaker": ("說話人", "Speaker"),
    "exp_text": ("內容", "Text"),
    "exp_sheet_transcript": ("逐字稿", "Transcript"),
    "exp_sheet_info": ("資訊", "Info"),
    "exp_page": ("第 {n} 頁", "Page {n}"),
    "exp_generated": ("由 LocalScribe 在本機離線產生，請在使用前校對。",
                      "Generated offline by LocalScribe. Please proofread before use."),
    # A plain gap may still hold up to 30 s of detected speech, so it claims no silence.
    "exp_gap_silence": ("[沒有轉出文字 {start}–{end}]", "[Nothing transcribed {start}–{end}]"),
    "exp_gap_speech": ("[偵測到語音，但沒有轉出文字 {start}–{end}]", "[Speech detected, nothing transcribed {start}–{end}]"),
    "exp_uncertain": ("不確定的字詞", "Unsure words"),
    "exp_uncertain_note_mark": ("Whisper 沒把握的字後面標有 {mark}。", "{mark} follows words Whisper was unsure of."),
    "exp_uncertain_note_highlight": ("Whisper 沒把握的字以黃色標出。", "Words Whisper was unsure of are highlighted in yellow."),
}


def default_language() -> str:
    try:
        import ctypes

        lang_id = ctypes.windll.kernel32.GetUserDefaultUILanguage()
        return "zh_TW" if (lang_id & 0x3FF) == 0x04 else "en"  # 0x04 = Chinese
    except Exception:
        code = (locale.getlocale()[0] or "").lower()
        return "zh_TW" if code.startswith(("zh", "chinese")) else "en"


def set_language(lang: str) -> None:
    global _current
    _current = lang if lang in LANGUAGES else "en"


def current_language() -> str:
    return _current


def tr(key: str, **kwargs) -> str:
    return tr_in(_current, key, **kwargs)


def tr_warning(warning: dict) -> str:
    """A transcript warning ({"key": ..., **format args}) in the current language."""
    return tr(warning["key"], **{k: v for k, v in warning.items() if k != "key"})


def tr_in(lang: str, key: str, **kwargs) -> str:
    entry = STRINGS.get(key)
    if entry is None:
        return key
    text = entry[_COLUMN.get(lang, 1)]
    return text.format(**kwargs) if kwargs else text
