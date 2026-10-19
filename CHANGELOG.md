# Changelog

## Unreleased

- **A proofreading window.** Right-click a finished file and choose **Proofread**, or click **Proofread…** and pick a `_transcript.json`. Its segments are listed with their time and speaker, and the words Whisper was unsure of are in yellow. Double-click a time to play the recording from there; Space plays and pauses. The list follows the audio until you click another row or scroll, and again once playback starts. Double-click a text or a speaker to correct it, and rename, merge or add speakers in the list beside it. **Ctrl+F** finds text in the segments, upper and lower case alike unless you tick *Match case*, and shows the matches in green; **Ctrl+H** also replaces them, one at a time or all at once. **Undo** (Ctrl+Z) takes back the last edit, a whole Replace all included. **Save** writes the transcript and the files that came out of its run again. It asks first when one of them changed after the transcript was saved, for instance in Word, and stops with a message while one is open in another program. **Save As** (Ctrl+Shift+S) writes them under a new name or in another folder instead and keeps the originals; the window then goes on with the new files. For playback, the recording is decoded into memory as for transcription, so every format plays and no audio is written to disk. When the recording isn't next to the transcript, **Find the recording…** points to it.

### 中文摘要

- **校對視窗**：在完成的檔案上按右鍵選「校對」，或按「校對…」選一份 `_transcript.json`。每一段會列出時間和說話人，Whisper 沒把握的字以黃色標出。雙擊時間會從那裡播放錄音，空白鍵播放或暫停。清單會跟著聲音移動，點選其他列或捲動表格後就停下，再次播放時繼續跟隨。雙擊文字或說話人可以修改，旁邊的說話人清單可以改名、合併或新增。「Ctrl+F」在文字中尋找（不分大小寫，除非勾選「大小寫須相符」），找到的字以綠色標出；「Ctrl+H」還可以取代，一處一處或全部取代。「復原」（Ctrl+Z）可以取消上一個修改，一次全部取代也一次復原。「儲存」會重寫逐字稿和那次轉錄產生的檔案；如果其中有檔案在逐字稿存檔後又被改過（例如在 Word 裡編輯），會先詢問，檔案正被其他程式開啟時則會提醒你先關閉。「另存新檔」（Ctrl+Shift+S）則用新的名稱或存到別的資料夾，原本的檔案不變，之後視窗改用新的檔案。播放時錄音會像轉錄時一樣解碼到記憶體裡，所以各種格式都能播放，也不會寫出任何音檔。錄音不在逐字稿旁邊時，可以用「找錄音…」指定。

## 0.1.5

- **Chinese in Traditional characters.** Whisper often writes Chinese in Simplified characters, also for speakers from Taiwan. Chinese transcripts are now converted to Traditional characters with [OpenCC](https://github.com/BYVoid/OpenCC) in every format, `_transcript.json` included. Only the script changes (软件 becomes 軟件, 处理 becomes 處理), so the words the speaker used stay. *Taiwan wording* under **Settings → Transcription → Chinese output** also swaps Mainland terms for Taiwan's (软件 becomes 軟體, 文件 becomes 檔案), which can change what was actually said; *As Whisper wrote it* keeps the text as it was. On the command line, use `--chinese`. Each word keeps its time and confidence; where a phrase changes length (代码 becomes 程式碼 with Taiwan wording), its words share the new text. Terms in the word bank and in Names and terms keep the spelling you gave them, and 台 stays 台 rather than OpenCC's formal 臺. Japanese is never converted.
- **Fewer invented Chinese lines.** On silence, music or noise, Whisper sometimes writes Chinese lines that nobody says in a recording: the channel appeal 請不吝點贊 訂閱 轉發 打賞支持明鏡與點點欄目, subtitle credits (字幕志願者 and a name, 字幕由 Amara.org 社區提供) and a video site's tag line (優優獨播劇場——YoYo Television Series Exclusive). These are now removed in either script, like the English credits, and only the line itself: speech in the same clip stays. Sign-offs such as 謝謝觀看 and 感謝收聽 are removed when they stand as a sentence of their own and Whisper is less than 50% sure of their first character, the rule for "Thanks for watching!"; 謝謝大家 is always kept. No Chinese test audio made Whisper write these lines, so the rule for sign-offs rests on the English tests. English transcripts don't change: on five 70–80-minute lectures, the old and the new filters removed the same words.
- **A warning for words that repeat.** When the same words come out four times or more in a row, a sentence that keeps coming back or a phrase that loops, the finished file now gets a warning with the times: Whisper sometimes gets stuck like this. Nothing is deleted, since people do repeat themselves. Repeats shorter than 4 Chinese characters or 3 words, such as 對對對 or "no, no, no", count only from 15 times in a row, as when Whisper writes "Thank you." for a whole clip. On the five lectures it came up for none; three times in a row would have flagged three short phrases said at a speaking pace.

### 中文摘要

- **中文改用繁體字**：Whisper 轉出的中文常是簡體字，台灣的說話人也一樣。現在中文逐字稿會用 OpenCC 轉成繁體，所有格式都一樣，包括 `_transcript.json`。預設只轉字（「软件」變成「軟件」），講者用的詞不變。在「設定 → 轉錄 → 中文輸出」可以改成台灣用語或不轉換；台灣用語會把大陸用詞換成台灣說法（「软件」變成「軟體」、「文件」變成「檔案」），可能改掉講者實際說的詞。命令列用 `--chinese`。每個字都保留原本的時間和信心值。詞庫和「專有名詞」裡的寫法不會被改，「台」也會保持「台」，不會變成 OpenCC 的正式寫法「臺」。日文不會被轉換。
- **減少憑空出現的中文句子**：Whisper 在安靜、音樂或雜音處，有時會寫出錄音裡沒人說的中文句子，例如頻道宣傳「請不吝點贊 訂閱 轉發 打賞支持明鏡與點點欄目」、字幕名單（「字幕志願者」加人名、「字幕由 Amara.org 社區提供」）和影音網站標語（「優優獨播劇場——YoYo Television Series Exclusive」）。現在這些句子不論簡繁都會被刪除，和英文的字幕名單一樣只刪那一句，同一段裡的說話內容會保留。「謝謝觀看」「感謝收聽」這類結尾語，要單獨成句、而且 Whisper 對第一個字的把握不到 50% 才會刪除，和「Thanks for watching!」同一套規則；「謝謝大家」一律保留。英文逐字稿不受影響：在五堂 70–80 分鐘的課上，新舊規則刪掉的字完全相同。
- **重複字句的提醒**：同樣的字句連續出現四次以上（同一句一再出現，或片語一直循環）時，完成的檔案會附上提醒和時間點，因為 Whisper 有時會這樣卡住。內容不會被刪除，因為也可能真的有人這樣說。少於 4 個中文字或 3 個英文字的重複（「對對對」、"no, no, no"），要連續 15 次以上才算，例如 Whisper 整段都寫「Thank you.」。在這五堂課上沒有出現這個提醒；如果門檻是連續三次，會有三個用正常語速說的短句被當成重複。

## 0.1.4

- **Updates without downloading everything again.** LocalScribe now checks for a new version when it starts, at most once a day, and offers it in a strip above the file list. **Update** downloads it in the background, and **Restart now** installs it and opens LocalScribe again. It waits while a transcription runs, and settings, word banks and models are kept. Usually only the files that changed are downloaded: between 0.1.0 and 0.1.3, 5 of the 5,145 files in the program folder changed, about 75 MB compressed, against 2.8 GB for the full installer. When bundled libraries such as PyTorch change, the full installer is downloaded instead. Each release now also has `LocalScribe-Update-x.y.z.exe`, which updates the version before it by double-click. The check reads one file from this repository's GitHub releases and sends none of your files or personal data (GitHub sees your IP address, as with any download, and the request names the LocalScribe version). Every download is checked against its SHA-256 when it arrives and again just before it runs. If an update fails, the version that was installed opens again and the same update can be retried. Turn the check off, or check by hand, under **Settings → General → Updates**. A copy from the portable ZIP opens the download page instead. Older versions don't check yet, so this one is installed by hand once; from 0.1.3, the small update installer is enough.

### 中文摘要

- **更新不必再整包重新下載**：LocalScribe 開啟時會檢查有沒有新版本（每天最多一次），有新版本時在檔案清單上方提示。按「更新」在背景下載，按「立即重新啟動」就會安裝並自動重開；轉錄進行中會等完成，設定、詞庫和模型都會保留。通常只下載有變動的檔案：從 0.1.0 到 0.1.3，程式資料夾的 5,145 個檔案只有 5 個不同，壓縮後約 75 MB，完整安裝檔則是 2.8 GB。內建的 PyTorch 等大型套件改版時，才會下載完整安裝檔。每個版本也會附上 `LocalScribe-Update-x.y.z.exe`，在前一版上雙擊就能更新。檢查時只從本專案的 GitHub Releases 讀取一個檔案，不會傳送你的檔案或個人資料（GitHub 看得到 IP 位址和 LocalScribe 的版本，和任何下載一樣）。下載的檔案在下載時和執行前都會核對 SHA-256。萬一更新失敗，原本的版本會重新開啟，同一個更新也可以再試一次。可以在「設定 → 一般 → 更新」關閉自動檢查或手動檢查。ZIP 免安裝版會改成開啟下載頁面。舊版本還不會檢查，所以這一版要手動安裝一次；從 0.1.3 更新的話，只要執行小更新檔就好。

## 0.1.3

- **Even out volume no longer costs accuracy.** It used to transcribe the whole recording from volume-levelled audio. On three real lectures that recovered quiet speech the original audio missed, but it got more technical terms wrong (13 against 5 on one lecture) and put more speaker changes mid-sentence. Now Whisper always transcribes the original audio. The levelled copy is only used to find speech the original leaves without text, at the edges of a clip or as a pause of more than 3 seconds inside one, and just those stretches are transcribed from it. On the same lectures, terms stayed as accurate as without levelling (6 against 5), and there were fewer mid-sentence speaker changes than with the old levelling: 27, 40 and 38, against 43, 41 and 46 (26, 35 and 30 without levelling). The quiet speech filled in (175 and 525 words on two lectures, as confident as normal speech) left every transcript with more words than the old way. It takes 9–27% longer than without levelling.
- **When to use a word bank.** On two more lectures about other topics, the NLP bank gained nothing and wrote a few of its terms where they probably weren't said, and with a bank transcription took 30–60% longer. The word-bank menu, the editor and the README now say to pick a bank only for recordings that use its terms.

### 中文摘要

- **平衡音量不再犧牲準確度**：以前開了平衡音量，就整段用平衡後的音訊轉錄。在三堂真實的課上，這樣雖然能找回原本聽不到的小聲語音，卻讓術語錯誤變多（其中一堂 13 對 5），換人點也更常落在句子中間。現在 Whisper 一律轉錄原始音訊，平衡後的副本只用來找出原始音訊漏掉、沒有文字的語音，再只把那幾段從副本補轉。原始音訊漏掉的地方，包括片段頭尾和片段中間超過 3 秒的停頓，都會從副本補轉。在同樣三堂課上，術語準確度和關閉時一樣（6 對 5），換人點落在句中的次數也比原本做法少：27、40、38 對 43、41、46（不開平衡音量時是 26、35、30）。兩堂課分別補回 175 和 525 個字的小聲語音，信心值和一般語音相當，三份逐字稿的字數都比原本做法多。比不開平衡音量多花 9–27% 的時間。
- **詞庫的使用時機**：在另外兩堂主題不同的課上，NLP 詞庫沒有幫助，還可能把幾個詞寫進沒說的地方，轉錄也慢了三到六成。詞庫選單、編輯視窗和 README 現在都會說明：只在錄音真的會講到這些詞時才選詞庫。

## 0.1.2

Changes since 0.1.1, from a code review and a round of hands-on testing.

### Word banks

- **Word banks for technical terms.** Whisper often mishears jargon, for example writing "tokenization" as "organization". Keep a short list of terms for each course or topic, and pick it in the main window's new **Word bank** menu before you start; the menu is searchable and can create, edit and delete banks. The bank's terms come first, then those in **Settings › Names and terms**. Whisper reads only the first 223 tokens of these terms, about 55 English terms. The editor counts them as you type, and before a run LocalScribe lists any terms that would be left out, instead of letting Whisper drop them silently. Terms in a bank make Whisper more likely to hear them, so keep each bank to the course at hand. Banks are saved in `%LOCALAPPDATA%\LocalScribe\vocabularies.json`, `_transcript.json` records which bank was used, and the command line takes `--vocabulary NAME`.
- **Word banks without side effects.** A bank's terms reach Whisper where the preceding transcript would go. Sent as a bare list, they made Whisper write video credits ("Subtitles by the Amara.org community") in pauses, and skip the first words of some clips. Four changes prevent this:
  - For English recordings the terms now go as one sentence ("This recording covers …").
  - Credit lines and invented sign-offs are removed.
  - Where the text with a bank starts or ends more than 1.5 s inside detected speech, or a stretch comes out empty, that part is transcribed again without the bank.
  - A piece cut out of running speech, which begins mid-sentence, is transcribed without the bank.

  On a real 78-minute lecture, run twice with and twice without a bank, misheard terms fell from 16 to 5. No credit lines or leaked term lists appeared, and nothing was missing that the runs without a bank had. Transcription took about 45% longer with the bank (about a third longer overall). The sentence takes 5 of Whisper's 223 tokens, and the editor and the check before a run count it.

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

### Removed

- **Fast mode.** Batched decoding was about 3× faster on a GPU, but in tests it dropped whole sentences: about 6 times as many deleted words as normal decoding (604 against 97 over 12 synthetic recordings). Each drop was under 30 seconds, so no warning appeared, and it couldn't use the word-bank checks. Normal decoding already transcribes a 78-minute lecture in about 6 minutes on an RTX 3070 Ti, and without a GPU fast mode made no difference. The setting and the `--fast` command-line option are gone; a settings file that had it turned on still loads.

### For developers

- `packaging\make_zip.py [dist folder]` takes the build folder (for example `dist_build`) and checks that `LocalScribe.exe` is in it.
- `.gitignore` covers recordings and transcripts in every folder, not just the project root, plus partial downloads, logs and `.env`.
- The test suite grew from 20 to 306 tests. They use fake models, so no GPU or model download is needed, and they take about 5 seconds.

### 中文摘要

以下是 0.1.1 之後的變更，來自程式碼審查與實機測試。

- **詞庫**：主視窗新增「詞庫」選單，可以為每門課或每個主題建一份專有名詞清單，開始前選好，Whisper 比較不會聽錯，例如把 tokenization 寫成 organization。Whisper 最多只讀約 55 個英文詞，超過時開始前會列出不會被使用的詞。詞庫存在 `%LOCALAPPDATA%\LocalScribe\vocabularies.json`。詞庫原本會讓 Whisper 在停頓處寫出影片字幕致謝，並跳過部分片段的開頭，現在都已處理：
  - 英文錄音改用一句話交出詞庫；
  - 致謝句和憑空結尾語會刪除；
  - 用詞庫轉出的文字如果比語音晚開始或早結束 1.5 秒以上，那一段會不帶詞庫重轉；
  - 從句子中間開始的片段也不用詞庫。

  在一份 78 分鐘的真實課堂錄音上（用與不用詞庫各跑兩次），術語錯誤從 16 降到 5，沒有致謝句或詞表外洩，也沒有比不用詞庫多漏語音。代價是轉錄慢約 45%。
- **標記不確定的字詞**（預設關閉，命令列用 `--mark-uncertain`）：Whisper 把握低於 40% 的字，Word 以黃色標示，txt 和 md 在字後加 (?)，Excel 和 CSV 多一欄列出；字幕不標記。在乾淨和有回音的合成測試錄音中，約每 100 個字標出 1 個，其中一半以上真的聽錯。很有把握卻聽錯的字（例如把 tokenization 聽成 organization）不會被標出，所以要和詞庫、校對一起用。
- **空白段標註**：30 秒以上沒有轉出文字的地方，txt、md 和 Word 會寫上「[沒有轉出文字 00:40:30–00:42:05]」；偵測到 30 秒以上的說話聲卻沒有文字時，寫「[偵測到語音，但沒有轉出文字 …]」，請回去聽是否漏掉內容。字幕和試算表從時間就看得出空白，不加標記。舊版的 `_transcript.json` 仍可讀取。
- **長時間停頓會換段**：停頓超過 10 秒就開新段落，即使 Whisper 沒有加句號，時間戳記也看得出空白。
- **問題會提醒你，不再默默發生**：檔案完成但結果可能較差時，工作清單會顯示「完成（N 項提醒）」，滑鼠停上去可看細節，記錄檔、命令列輸出和 `_transcript.json` 也會記下。涵蓋：檔案損毀或被截斷、顯示卡失敗改用 CPU、設定指定顯示卡卻找不到、分不出說話人或人數少於指定、偵測到 30 秒以上的說話聲卻沒有轉出文字（會列出時間段）。
- **截斷的錄音會被發現**：中途中斷或沒複製完整的檔案，以前會被當成完整的來轉錄；現在會比對實際讀到的長度。轉檔工具也會檢查並標示。
- **沒有語音時直接報錯**，不再產生空白逐字稿。
- **顯示卡失敗時沿用同一個模型**，改用 CPU 繼續，較慢但一樣準確。以前「自動」會換成 small 模型，載入 pyannote 時顯示卡失敗也會讓檔案失敗。設定明確指定顯示卡時，失敗會直接報錯，不會偷偷改用 CPU。
- **逐字稿**：Whisper 憑空寫出、單獨成句、而且把握不到 50% 的「Thank you.」類結尾語會被刪除。換人點只差句首或句尾 1–2 個字時，整句歸給同一個人，換人點會落在句尾或停頓處。`_transcript.json` 可供日後的校對編輯器使用：較新版本的檔案會明確拒絕而不是遺失資料，存檔失敗不會毀掉舊檔。文字修改過後，字幕和試算表以修改後的文字為準。
- **穩定性**：工作執行中關閉視窗會先等它停止，太久會提示並保持開啟，不再當掉。轉檔時按 Esc 等於「取消」，視窗保留並顯示「已停止」。背景錯誤會記錄並跳出提示。輸出檔全部寫完才放到目的地，失敗不留半成品。模型下載遇到伺服器忙碌會重試。損毀的 `settings.json` 會備份成 `settings.json.bad`。`--speakers` 會拒絕 `2-`、`3-1`、`0` 這類值。`.ts` 不再被當成媒體檔。關閉提示改為「正在轉錄中」。
- **隱私與安全**：`_transcript.json` 和 Excel 只記錄檔名，不記錄資料夾；記錄檔也只寫檔名。下載的模型會核對 SHA-256，token 只透過 https 傳送。ffmpeg 只讀本機檔案，檔案標籤無法偽造長度。CSV 與 Excel 中以 `=`、`+`、`-`、`@` 開頭的內容會加上 `'`，不會被當成公式執行。
- **移除快速模式**：批次解碼在顯示卡上約快 3 倍，但測試中會整句漏掉，刪掉的字約是一般模式的 6 倍。每次漏掉都短於 30 秒，所以不會出現提醒，也用不到詞庫的漏字檢查。一般模式在 RTX 3070 Ti 上轉 78 分鐘的課約 6 分鐘，沒有顯示卡時快速模式本來就沒有作用。設定裡的選項和命令列的 `--fast` 都已移除，曾經開過它的設定檔照樣能讀。
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
