# Changelog

## Unreleased

Changes since 0.1.1, from a code review and a round of hands-on testing.

### Word banks

- **Word banks for technical terms.** Whisper often mishears jargon, for example writing "tokenization" as "organization". Keep a short list of terms for each course or topic, and pick it in the main window's new **Word bank** menu before you start; the menu is searchable and can create, edit and delete banks. The bank's terms come first, then those in **Settings › Names and terms**. Whisper reads only the first 223 tokens of these terms, about 55 English terms. The editor counts them as you type, and before a run LocalScribe lists any terms that would be left out, instead of letting Whisper drop them silently. Terms in a bank make Whisper more likely to hear them, so keep each bank to the course at hand. Banks are saved in `%LOCALAPPDATA%\LocalScribe\vocabularies.json`, `_transcript.json` records which bank was used, and the command line takes `--vocabulary NAME`.
- **Word banks without side effects.** A bank's terms reach Whisper where the preceding transcript would go. Sent as a bare list, they made Whisper write video credits ("Subtitles by the Amara.org community") in pauses, and skip the first words of some clips. Four changes prevent this:
  - For English recordings the terms now go as one sentence ("This recording covers …").
  - Credit lines and invented sign-offs are removed.
  - Where the text with a bank starts or ends more than 1.5 s inside detected speech, or a stretch comes out empty, that part is transcribed again without the bank.
  - A piece cut out of running speech, which begins mid-sentence, is transcribed without the bank.

  On a real 78-minute lecture, run twice with and twice without a bank, misheard terms fell from 16 to 5. No credit lines or leaked term lists appeared, and nothing was missing that the runs without a bank had. Transcription took about 45% longer with the bank (about a third longer overall). The sentence takes 5 of Whisper's 223 tokens, and the editor and the check before a run count it. Fast mode doesn't have the re-check yet, so there a bank can still drop the first words of a clip.

### Proofreading aids

- **Mark unsure words** (off by default; in the main window, or `--mark-uncertain` on the command line). Words Whisper gave less than 40% confidence are highlighted in yellow in Word, followed by `(?)` in text and Markdown, and listed in an extra *Unsure words* column in Excel and CSV, so the text column stays as spoken. Subtitles stay unmarked. The 40% comes from synthetic test recordings with a known script: in the clean and reverberant ones it marked about 1 word in 100, and more than half of the marked words were real recognition errors; at 50%, four in five of the extra marks were correct words. Most errors are not marked, because Whisper is often confident when it mishears ("organization" for "tokenization"), so this complements word banks and proofreading.
- **Stretches without text are marked.** Where no text came out for 30 seconds or more, text, Markdown and Word transcripts get a line such as `[Nothing transcribed 00:40:30–00:42:05]`, in the language of the headings. Where the voice detector heard 30 seconds of speech or more, the line says `[Speech detected, nothing transcribed …]` instead; these are the stretches the lost-speech warning lists. The plain line doesn't promise silence, since up to 30 seconds of speech can hide in it. Subtitles and spreadsheets show silences through their times, so they get no markers. `_transcript.json` keeps the stretches in a new `gaps` list; files from earlier versions still load, without markers.
- **A long silence starts a new paragraph.** After more than 10 seconds of silence a new paragraph begins, even when Whisper left out the period before it, so the timestamps show the jump. Before, with one speaker, such a silence could stay hidden inside a paragraph.

### Problems are reported instead of hidden

- **Warnings on finished files.** When a file finishes but the result may be worse than usual, LocalScribe now says so. The queue shows "Done (1 warning(s))" (hover for details), and the warning also goes to the log, the command-line output and `_transcript.json`. Cases covered:
  - a damaged or cut-off recording, where only part of the audio could be read;
  - the GPU failing, so the file ran on the CPU instead (later files in the same session are marked too);
  - Settings asking for the GPU when no usable NVIDIA GPU is found;
  - no speakers could be told apart, or fewer speakers were found than you asked for;
  - speech was detected for 30 seconds or more, but no text came out (the warning names the stretch, such as 12:05–13:50).
- **Cut-off recordings are caught.** A recording that stops early, such as a copy that didn't finish, used to be transcribed as if it were complete, because ffmpeg reads such files without an error. LocalScribe now compares the length it read with the length the file claims. The audio converter does the same and marks the row.
- **No speech is an error.** A file in which no speech is found now fails with a clear message instead of producing an empty transcript.
- **A GPU failure keeps the model.** If the GPU fails, transcription and speaker identification continue on the CPU with the Whisper model the GPU would have used: slower, but just as accurate. Before, "Automatic" switched to the small model, and a GPU failure while loading pyannote stopped the file. When Settings explicitly asks for the GPU, a GPU failure now stops the file with an error for speaker identification too, instead of quietly switching to the CPU.
- If hardware detection fails, the status bar no longer stays at "Detecting hardware…".

### Transcripts

- **Fewer invented "Thank you."** Whisper sometimes writes "Thank you." or "Thanks for watching!" where nobody said it: at the end of a 28-second piece that was cut mid-sentence, or over a hum, distant chatter or music. In tests, Whisper's confidence in the first word of these was 26% or less, while spoken thanks came out at 77% or more. A stand-alone sign-off like this is now removed when that confidence is below 50%, and the log says how many words were removed. Sentences that go on, such as "Thank you for the question.", are kept.
- **Speaker changes land between sentences.** When speaker identification put a change one or two words into a sentence, the whole sentence now goes to the speaker of the rest of it, so the change falls at the sentence end or at a pause. A change after a silence or a comma stays where it is, so quick replies such as "Right." are kept. On synthetic test recordings, sentences split between two speakers went from 4 to 2. A short reply with no punctuation that runs straight into the next speaker's words can still be merged into the previous speaker.
- **Ready for a proofreading editor.** Loading a `_transcript.json` from a newer LocalScribe fails with a clear message instead of silently losing data, and unknown fields are ignored. Saving goes through a temporary file, so a failed save never destroys the previous one.
- **Edited text wins.** If a segment's text no longer matches its word timings, for example after it was corrected, subtitles and spreadsheets use the corrected text.
- **The punctuation hint is English-only.** Fast mode nudges Whisper to keep punctuation with an English example sentence. It is now used only when the language is set to English, not on auto-detect, where it could bias the result toward English.

### Stability

- **Safe closing.** Closing the main window, Settings or the converter while work is running now waits for the work to stop. If that takes too long, the window says so and stays open instead of crashing.
- **Esc in the converter** stops the conversion like Cancel and keeps the dialog open, with the row marked "Stopped".
- **Crash reports.** Unexpected errors in background work are logged and shown in a message box. Native crashes are written to `%LOCALAPPDATA%\LocalScribe\console.log`, or to the console when there is one.
- **No half-written exports.** Output files are written to a temporary folder and moved into place only after all of them succeed. A full disk or a locked file reports which file failed and leaves nothing behind.
- **Model downloads** retry when the server is busy (HTTP 429 or 5xx), Stop works during the wait, and network and disk problems show a clear message.
- **A damaged `settings.json`** is kept as `settings.json.bad`, and the defaults are used.
- A file whose length can't be read no longer stops the files after it from showing their lengths.
- On the command line, `--speakers` rejects values such as `2-`, `3-1` or `0` with a clear message.
- `.ts` files are no longer treated as media, because that is also the extension of TypeScript source files.
- The quit confirmation now says a transcription, not a conversion, is running.

### Privacy and security

- **No folder names in outputs.** `_transcript.json` and the Excel export store the recording's file name only, because folder names (a client's, a course's) can identify people. Log lines name files, not folders; the technical details of an unexpected error can still include a path (see README › Privacy).
- **Downloads are checked.** Large Hugging Face files are verified against their SHA-256. A file listed with a path outside the model folder is refused. A Hugging Face token is only sent over https, which matters if you set `HF_ENDPOINT`. sherpa-onnx files whose size the server doesn't report are refused, because a cut-off download would look complete.
- **ffmpeg reads local files only.** A crafted playlist or media file can't make it open network addresses, and text in a file's tags, such as its title, can no longer fake its length or audio streams.
- **No formulas in spreadsheets.** CSV and Excel cells that start with `=`, `+`, `-`, `@` or a tab get a leading apostrophe, so Excel shows them as text instead of running them.
- Explorer is started by its full Windows path.

### For developers

- `packaging\make_zip.py [dist folder]` takes the build folder (for example `dist_build`) and checks that `LocalScribe.exe` is in it.
- `.gitignore` covers recordings and transcripts in every folder, not just the project root, plus partial downloads, logs and `.env`.
- The test suite grew from 20 to 306 tests. They use fake models, so no GPU or model download is needed, and they take about 5 seconds.

### 中文摘要

以下是 0.1.1 之後的變更，來自程式碼審查與實機測試，尚未發佈。

- **詞庫**：主視窗新增「詞庫」選單，可以為每門課或每個主題建一份專有名詞清單，開始前選好，Whisper 比較不會聽錯，例如把 tokenization 寫成 organization。Whisper 最多只讀約 55 個英文詞，超過時開始前會列出不會被使用的詞。詞庫存在 `%LOCALAPPDATA%\LocalScribe\vocabularies.json`。詞庫原本會讓 Whisper 在停頓處寫出影片字幕致謝，並跳過部分片段的開頭，現在都已處理：
  - 英文錄音改用一句話交出詞庫；
  - 致謝句和憑空結尾語會刪除；
  - 用詞庫轉出的文字如果比語音晚開始或早結束 1.5 秒以上，那一段會不帶詞庫重轉；
  - 從句子中間開始的片段也不用詞庫。

  在一份 78 分鐘的真實課堂錄音上（用與不用詞庫各跑兩次），術語錯誤從 16 降到 5，沒有致謝句或詞表外洩，也沒有比不用詞庫多漏語音。代價是轉錄慢約 45%。快速模式還沒有這項重新檢查。
- **標記不確定的字詞**（預設關閉，命令列用 `--mark-uncertain`）：Whisper 把握低於 40% 的字，Word 以黃色標示，txt 和 md 在字後加 (?)，Excel 和 CSV 多一欄列出；字幕不標記。在乾淨和有回音的合成測試錄音中，約每 100 個字標出 1 個，其中一半以上真的聽錯。很有把握卻聽錯的字（例如把 tokenization 聽成 organization）不會被標出，所以要和詞庫、校對一起用。
- **空白段標註**：30 秒以上沒有轉出文字的地方，txt、md 和 Word 會寫上「[沒有轉出文字 00:40:30–00:42:05]」；偵測到 30 秒以上的說話聲卻沒有文字時，寫「[偵測到語音，但沒有轉出文字 …]」，請回去聽是否漏掉內容。字幕和試算表從時間就看得出空白，不加標記。舊版的 `_transcript.json` 仍可讀取。
- **長時間停頓會換段**：停頓超過 10 秒就開新段落，即使 Whisper 沒有加句號，時間戳記也看得出空白。
- **問題會提醒你，不再默默發生**：檔案完成但結果可能較差時，工作清單會顯示「完成（N 項提醒）」，滑鼠停上去可看細節，記錄檔、命令列輸出和 `_transcript.json` 也會記下。涵蓋：檔案損毀或被截斷、顯示卡失敗改用 CPU、設定指定顯示卡卻找不到、分不出說話人或人數少於指定、偵測到 30 秒以上的說話聲卻沒有轉出文字（會列出時間段）。
- **截斷的錄音會被發現**：中途中斷或沒複製完整的檔案，以前會被當成完整的來轉錄；現在會比對實際讀到的長度。轉檔工具也會檢查並標示。
- **沒有語音時直接報錯**，不再產生空白逐字稿。
- **顯示卡失敗時沿用同一個模型**，改用 CPU 繼續，較慢但一樣準確。以前「自動」會換成 small 模型，載入 pyannote 時顯示卡失敗也會讓檔案失敗。設定明確指定顯示卡時，失敗會直接報錯，不會偷偷改用 CPU。
- **逐字稿**：Whisper 憑空寫出、單獨成句、而且把握不到 50% 的「Thank you.」類結尾語會被刪除。換人點只差句首或句尾 1–2 個字時，整句歸給同一個人，換人點會落在句尾或停頓處。`_transcript.json` 可供日後的校對編輯器使用：較新版本的檔案會明確拒絕而不是遺失資料，存檔失敗不會毀掉舊檔。文字修改過後，字幕和試算表以修改後的文字為準。快速模式的英文標點提示只在語言設為英文時使用。
- **穩定性**：工作執行中關閉視窗會先等它停止，太久會提示並保持開啟，不再當掉。轉檔時按 Esc 等於「取消」，視窗保留並顯示「已停止」。背景錯誤會記錄並跳出提示。輸出檔全部寫完才放到目的地，失敗不留半成品。模型下載遇到伺服器忙碌會重試。損毀的 `settings.json` 會備份成 `settings.json.bad`。`--speakers` 會拒絕 `2-`、`3-1`、`0` 這類值。`.ts` 不再被當成媒體檔。關閉提示改為「正在轉錄中」。
- **隱私與安全**：`_transcript.json` 和 Excel 只記錄檔名，不記錄資料夾；記錄檔也只寫檔名。下載的模型會核對 SHA-256，token 只透過 https 傳送。ffmpeg 只讀本機檔案，檔案標籤無法偽造長度。CSV 與 Excel 中以 `=`、`+`、`-`、`@` 開頭的內容會加上 `'`，不會被當成公式執行。
- **開發者**：`make_zip.py` 可指定建置資料夾；`.gitignore` 涵蓋所有資料夾中的錄音與逐字稿；測試從 20 個增加到 306 個。

## 0.1.1

Tested on a real 78-minute classroom recording (iPhone Voice Memos, several speakers).

- **Fewer skipped sentences.** Speech is now found with a more sensitive voice detector and split into clips of at most 28 seconds at natural pauses; Whisper decodes each clip on its own. Before, quiet remarks and some students' questions near Whisper's 30-second window edges were dropped, and one phone number came out as "9888" instead of "988". When we decoded those passages in isolation, Whisper heard them clearly, so the speech was really there.
- **pyannote verified end to end.** With the pyannote model installed, speaker identification on a GPU took about 1.5 minutes for the 78-minute recording (sherpa-onnx on the CPU: about 10 minutes).
- **Presets no longer cap speakers too tightly.** Lecture and online-meeting presets now detect any number of speakers, and group meetings allow up to 10. On the classroom recording (7 voices: two main speakers and five students), a cap of 5 made pyannote split one main speaker in two. Without the cap, pyannote and sherpa-onnx agreed on 99% of the main speakers' words.
- Quieter logs: harmless warnings from pyannote and PyTorch are no longer printed.
- `run.bat` explains what to do when the virtual environment's Python is missing, instead of failing with "No Python at …".
- README: screenshots, settings reference, troubleshooting and FAQ.

## 0.1.0

First release: offline transcription with speaker identification for Windows. It includes Whisper (GPU/CPU), pyannote and sherpa-onnx speaker identification, scenario presets, seven export formats, iPhone Voice Memos (.qta) support, an audio converter and an English/Traditional Chinese interface.
