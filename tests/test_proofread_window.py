"""The proofreading window, offscreen with a fake sound card, in a process of its own (one QApplication)."""

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

SCRIPT = r'''
import json, sys, time, types, wave
from pathlib import Path
import numpy as np

folder = Path(sys.argv[1])
from localscribe import paths
paths.user_data_dir = lambda: folder / "data"


class Stream:  # a sound card that keeps what it is asked to play
    made = []

    def __init__(self, samplerate, channels, dtype, callback, finished_callback=None):
        self.callback, self.finished = callback, finished_callback
        Stream.made.append(self)

    def start(self):
        pass

    def stop(self):
        pass

    def close(self):
        pass


class CallbackStop(Exception):
    pass


sd = types.ModuleType("sounddevice")
sd.OutputStream, sd.CallbackStop = Stream, CallbackStop
sys.modules["sounddevice"] = sd

from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QMouseEvent, QWheelEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox
app = QApplication([])
from localscribe import i18n
i18n.set_language("en")
from localscribe.config import Settings
from localscribe.core.transcript import Gap, Segment, Transcript, TWord
from localscribe.export import write_outputs
from localscribe.export.common import ExportOptions
from localscribe.ui.main_window import MainWindow
from localscribe.ui.proofread_window import SPEAKER, TEXT, TIME, ProofreadWindow


def wait(condition, seconds=20):
    deadline = time.time() + seconds
    while not condition() and time.time() < deadline:
        app.processEvents()
        time.sleep(0.02)
    app.processEvents()


def play_frames(frames):  # the sound card takes more; once the callback stops, PortAudio says it finished
    stream = Stream.made[-1]
    try:
        stream.callback(np.zeros((frames, 1), np.int16), frames, None, None)
    except CallbackStop:
        stream.finished()


def double_click(widget, pos):  # as Windows sends it: QTest.mouseDClick sends the double-click alone
    for kind in (QEvent.MouseButtonPress, QEvent.MouseButtonRelease, QEvent.MouseButtonDblClick,
                 QEvent.MouseButtonRelease):
        buttons = Qt.NoButton if kind == QEvent.MouseButtonRelease else Qt.LeftButton
        QApplication.sendEvent(widget, QMouseEvent(kind, QPointF(pos), QPointF(widget.mapToGlobal(pos)), Qt.LeftButton,
                                                   buttons, Qt.NoModifier))


t = Transcript(
    source="class.wav", duration=5.0, language="en", created="2026-10-17T10:00:00", app_version="0.1.5",
    settings={}, speakers={"S1": "Speaker 1", "S2": "Speaker 2"},
    segments=[Segment("S1", 0.0, 0.9, "Hello, everyone.", [TWord(0.0, 0.4, " Hello,", 0.9),
                                                            TWord(0.5, 0.9, " everyone.", 0.3)]),
              Segment("S2", 1.5, 2.4, "Thanks Sam.", [TWord(1.5, 1.9, " Thanks", 0.9), TWord(2.0, 2.4, " Sam.", 0.9)]),
              Segment("S1", 3.0, 3.9, "Let's start.", [TWord(3.0, 3.4, " Let's", 0.9),
                                                        TWord(3.5, 3.9, " start.", 0.9)])])
written = write_outputs(t, folder, ["txt"], ExportOptions())
json_path = next(p for p in written if p.suffix == ".json")
with wave.open(str(folder / "class.wav"), "wb") as w:  # the recording, next to its transcript
    w.setnchannels(1)
    w.setsampwidth(2)
    w.setframerate(16000)
    w.writeframes((np.sin(np.arange(16000 * 5) / 10) * 8000).astype(np.int16).tobytes())

out = {}
window = ProofreadWindow(json_path, Settings())
window.show()
wait(lambda: window.player is not None)
model = window.model
out["loaded"] = window.player is not None and window.btn_play.isEnabled()
out["rows"] = [[model.index(r, c).data() for c in range(3)] for r in range(model.rowCount())]
out["unsure_tip"] = model.index(0, TEXT).data(Qt.ToolTipRole)
from PySide6.QtGui import QColor, QPalette
from localscribe.ui.proofread_window import unsure_colors
dark = QPalette(app.palette())
dark.setColor(QPalette.Base, QColor("#1F2937"))
dark.setColor(QPalette.Text, QColor("#F3F4F6"))
out["unsure_colors"] = [list(unsure_colors(app.palette())), list(unsure_colors(dark))]

out["edit"] = model.setData(model.index(1, TEXT), "Thank you, Sam.")
out["dirty_title"] = window.windowTitle().startswith("* ")
out["edited_tip"] = model.index(1, TEXT).data(Qt.ToolTipRole)
window.speaker_list.item(0).setText("Prof. Lee")  # typed into the list
app.processEvents()
out["speakers_renamed"] = dict(window.t.speakers)
out["row0_speaker"] = model.index(0, SPEAKER).data()
out["list"] = [window.speaker_list.item(i).text() for i in range(window.speaker_list.count())]
window.speaker_list.item(1).setText("   ")  # an empty name is refused
app.processEvents()
out["list_after_empty"] = [window.speaker_list.item(i).text() for i in range(window.speaker_list.count())]
out["speaker_edit"] = model.setData(model.index(2, SPEAKER), "S2")

window.play_from(0)
out["streams"] = len(Stream.made)
Stream.made[-1].callback(np.zeros((25600, 1), np.int16), 25600, None, None)  # 1.6 s play
window._tick()
out["row_follows"] = window.table.currentIndex().row()
window.toggle_play()
out["paused"] = not window.player.playing and window.btn_play.text() == "Play"
window.toggle_play()
out["resumed_at"] = round(window.player.position(), 2)
window.toggle_play()

# Clicking another row stops the list following the audio; playing again (Space) follows it again.
view = window.table
window.play_from(0)
QTest.mouseClick(view.viewport(), Qt.LeftButton, Qt.NoModifier, view.visualRect(model.index(2, TEXT)).center())
Stream.made[-1].callback(np.zeros((25600, 1), np.int16), 25600, None, None)  # on to the second segment
window._tick()
out["click_stays"] = view.currentIndex().row()
QTest.keyClick(view, Qt.Key_Space)  # pause
QTest.keyClick(view, Qt.Key_Space)  # and play on from there
window._tick()
out["space_follows"] = view.currentIndex().row()
window.toggle_play()

out["merged"] = window.merge_speaker("S2", "S1")
app.processEvents()
out["speakers_merged"] = dict(window.t.speakers)
window.undo()
app.processEvents()
out["unmerged"] = [dict(window.t.speakers), [s.speaker for s in window.t.segments]]
window.merge_speaker("S2", "S1")
window.delete_segment(0)
out["rows_after_delete"] = model.rowCount()
window.undo()
out["rows_after_undo"] = [model.rowCount(), model.index(0, TEXT).data()]
model.setData(model.index(2, TEXT), "Let us start.")
window.undo()
out["text_undone"] = model.index(2, TEXT).data()
out["saved"] = window.save()
out["clean_title"] = not window.windowTitle().startswith("* ")
out["txt"] = (folder / "class_transcript.txt").read_text(encoding="utf-8")
saved = Transcript.load(json_path)
out["json_speakers"] = saved.speakers
out["json_texts"] = [s.text for s in saved.segments]

model.setData(model.index(0, TEXT), "Hello again.")
out["dirty_after_edit"] = window.dirty
window.undo()
out["clean_after_undo"] = not window.dirty and not window.windowTitle().startswith("* ")
model.setData(model.index(0, TEXT), "Hello again.")
QMessageBox.exec = lambda self: self.button(QMessageBox.Cancel).click()
window.close()
out["cancel_keeps_open"] = window.isVisible()
QMessageBox.exec = lambda self: self.button(QMessageBox.Discard).click()
window.close()
out["discard_closes"] = not window.isVisible()
out["discarded"] = Transcript.load(json_path).segments[0].text

# Opening from the main window: the same transcript twice gives the same window; a stray JSON a message.
warnings = []
QMessageBox.warning = lambda *args: warnings.append(args[2])
fake = types.SimpleNamespace(_proofreaders=[], settings=Settings())
first = MainWindow.open_proofread(fake, json_path)
out["reused"] = MainWindow.open_proofread(fake, json_path) is first and len(fake._proofreaders) == 1
(folder / "other.json").write_text('{"name": "not a transcript"}', encoding="utf-8")
out["stray"] = MainWindow.open_proofread(fake, folder / "other.json") is None and len(warnings) == 1
first.close()
out["forgotten"] = fake._proofreaders == []

# Save As: new files under the name typed; the window goes on with those, and the old ones stay.
originals = {p.name: p.read_bytes() for p in folder.glob("class_transcript*")}
suggested = []
QFileDialog.getSaveFileName = lambda *args, **kwargs: (suggested.append(Path(args[2]).name) or str(folder / "checked"), "")
copy = MainWindow.open_proofread(fake, json_path)
copy.model.setData(copy.model.index(0, TEXT), "Hello, all.")
out["save_as"] = copy.save_as()
out["save_as_suggested"] = suggested
out["save_as_files"] = sorted(p.name for p in folder.glob("checked_transcript*"))
out["save_as_text"] = Transcript.load(folder / "checked_transcript.json").segments[0].text
out["save_as_clean"] = not copy.dirty and copy.windowTitle().startswith("Proofread: checked_transcript.json")
copy.model.setData(copy.model.index(0, TEXT), "Hello, you all.")
out["then_save"] = copy.save() and Transcript.load(folder / "checked_transcript.json").segments[0].text
out["originals_kept"] = {p.name: p.read_bytes() for p in folder.glob("class_transcript*")} == originals
out["by_new_name"] = MainWindow.open_proofread(fake, folder / "checked_transcript.json") is copy
again = MainWindow.open_proofread(fake, json_path)
out["by_old_name"] = again is not copy and again.t.segments[0].text == "Hello, everyone."
QFileDialog.getSaveFileName = lambda *args, **kwargs: (str(folder / "checked_transcript.json"), "")
out["refused_while_open"] = not again.save_as() and "another proofreading window" in warnings[-1]
copy.close()
questions = []
QMessageBox.question = lambda *args, **kwargs: questions.append(args[2]) or QMessageBox.No
out["asked_first"] = not again.save_as() and ["checked_transcript.txt" in q and "checked_transcript.json" in q
                                              for q in questions] == [True]
out["kept_when_no"] = Transcript.load(folder / "checked_transcript.json").segments[0].text == "Hello, you all."
again.close()
out["all_forgotten"] = fake._proofreaders == []

# Scrolling stops the list following the audio too; double-clicking a time follows it again.
with wave.open(str(folder / "many.wav"), "wb") as w:
    w.setnchannels(1)
    w.setsampwidth(2)
    w.setframerate(16000)
    w.writeframes(np.zeros(16000 * 10, np.int16).tobytes())
many = Transcript(source="many.wav", duration=10.0, language="en", created="", app_version="0.1.5", settings={},
                  speakers={"S1": "Speaker 1"},
                  segments=[Segment("S1", k / 10, k / 10 + 0.09, f"Line {k}.") for k in range(100)])
many.save(folder / "many_transcript.json")
scroller = ProofreadWindow(folder / "many_transcript.json", Settings())
scroller.show()
wait(lambda: scroller.player is not None)
view = scroller.table
scroller.play_from(0)
middle = view.viewport().rect().center()
QApplication.sendEvent(view.viewport(), QWheelEvent(QPointF(middle), QPointF(view.viewport().mapToGlobal(middle)), QPoint(),
                                                    QPoint(0, -120), Qt.NoButton, Qt.NoModifier, Qt.NoScrollPhase, False))
out["wheel_scrolled"] = view.verticalScrollBar().value() > 0
Stream.made[-1].callback(np.zeros((32000, 1), np.int16), 32000, None, None)  # 2 s on
scroller._tick()
out["scroll_stays"] = view.currentIndex().row()
row = view.rowAt(middle.y())
double_click(view.viewport(), view.visualRect(scroller.model.index(row, TIME)).center())
followed = []
for _ in range(2):  # the window scrolls to the audio itself, and that goes on following it
    Stream.made[-1].callback(np.zeros((32000, 1), np.int16), 32000, None, None)
    scroller._tick()
    followed.append(view.currentIndex().row() - row)
out["dclick_follows"] = followed
scroller.close()

# Find (Ctrl+F) and replace (Ctrl+H) in the texts; each replacement is undone like any edit.
from PySide6.QtGui import QShortcut
from localscribe.ui.proofread_window import highlight
out["pieces"] = highlight([("Sam said ", False), ("hello", True), (" to Sam.", False)], [(0, 3), (18, 21)], (18, 21))
out["pieces_over_unsure"] = highlight([("a ", False), ("bc", True), (" d", False)], [(3, 5)], None)
Transcript(source="none.wav", duration=6.0, language="en", created="", app_version="0.1.5", settings={},
           speakers={"S1": "A", "S2": "B"},
           segments=[Segment("S1", 0.0, 1.0, "Sam said hello to Sam."), Segment("S2", 1.5, 2.5, "Then Pam left."),
                     Segment("S1", 3.0, 4.0, "sam is here."), Segment("S2", 4.5, 5.0, "Nothing.")]
           ).save(folder / "find_transcript.json")
finder = ProofreadWindow(folder / "find_transcript.json", Settings())
finder.show()
app.processEvents()
out["find_keys"] = sorted(s.key().toString() for s in finder.findChildren(QShortcut))
QTest.keyClick(finder.table, Qt.Key_F, Qt.ControlModifier)
out["find_shown"] = [finder.find_bar.isVisible(), finder.edit_replace.isVisible(), finder.edit_find.hasFocus()]
QTest.keyClicks(finder.edit_find, "sam")  # found as it is typed
out["first"] = [finder._match, finder.lbl_matches.text(), finder.table.currentIndex().row()]
steps = []
for modifier in (Qt.NoModifier, Qt.NoModifier, Qt.NoModifier, Qt.ShiftModifier):  # Enter, and Shift+Enter
    QTest.keyClick(finder.edit_find, Qt.Key_Return, modifier)
    steps.append(finder._match)
out["steps"] = steps
delegate = finder.table.itemDelegateForColumn(TEXT)
out["delegate"] = [delegate.found, delegate.current]
finder.chk_match_case.setChecked(True)
out["match_case"] = [finder._match, finder.lbl_matches.text()]
finder.chk_match_case.setChecked(False)
QTest.keyClick(finder.edit_find, Qt.Key_H, Qt.ControlModifier)
out["replace_shown"] = finder.edit_replace.isVisible()
finder.edit_replace.setText("Pam")
out["replace"] = [finder.replace(), finder.t.segments[2].text, finder._match, finder.dirty]
finder.undo()
out["replace_undone"] = [finder.t.segments[2].text, finder.dirty]
out["replace_all"] = [finder.replace_all(), [s.text for s in finder.t.segments], finder.lbl_status.text(),
                      finder.lbl_matches.text()]
finder.undo()  # all of them in one step
out["all_undone"] = [[s.text for s in finder.t.segments], finder.dirty]
out["replace_finds_first"] = [finder.replace(), finder._match, finder.t.segments[0].text, finder.lbl_matches.text()]
finder.edit_replace.setText("")
finder.edit_find.setText("Nothing.")
out["never_empty"] = [finder.replace(), finder.t.segments[3].text, "delete" in finder.lbl_status.text().lower()]
QTest.keyClick(finder.edit_find, Qt.Key_Escape)
out["find_hidden"] = [finder.find_bar.isVisible(), delegate.found, finder.table.hasFocus()]
finder.close()

# Shift+Enter splits a text at the cursor, and the list of speakers opens for the new segment.
from PySide6.QtWidgets import QAbstractItemView, QComboBox
Transcript(source="class.wav", duration=5.0, language="en", created="", app_version="0.1.5", settings={},
           speakers={"S1": "Speaker 1", "S2": "Speaker 2"},
           segments=[Segment("S1", 0.0, 0.9, "Hello, everyone.", [TWord(0.0, 0.4, " Hello,", 0.9),
                                                                   TWord(0.5, 0.9, " everyone.", 0.9)]),
                     Segment("S2", 1.5, 3.9, "Thanks Sam. Let's start.", [
                         TWord(1.5, 1.9, " Thanks", 0.9), TWord(2.0, 2.4, " Sam.", 0.9),
                         TWord(3.0, 3.4, " Let's", 0.9), TWord(3.5, 3.9, " start.", 0.9)]),
                     Segment("S1", 4.0, 4.9, "Good.", [TWord(4.0, 4.5, " Good.", 0.9)])]
           ).save(folder / "split_transcript.json")
splitter = ProofreadWindow(folder / "split_transcript.json", Settings())
splitter.show()
wait(lambda: splitter.player is not None)
view = splitter.table
editing = lambda: view.state() == QAbstractItemView.EditingState


def edit_text(row, cursor):
    double_click(view.viewport(), view.visualRect(splitter.model.index(row, TEXT)).center())
    editor = QApplication.focusWidget()
    editor.setCursorPosition(cursor)
    return editor


QTest.keyClick(edit_text(1, 12), Qt.Key_Return)  # Enter still only finishes the edit
app.processEvents()
out["enter_keeps"] = [len(splitter.t.segments), editing()]
QTest.keyClick(edit_text(1, 12), Qt.Key_Return, Qt.ShiftModifier)  # "Thanks Sam. |Let's start."
app.processEvents()
out["split"] = [[s.speaker, s.start, s.end, s.text] for s in splitter.t.segments]
combo = next((c for c in view.viewport().findChildren(QComboBox) if c.isVisible()), None)
wait(lambda: combo is not None and combo.view().isVisible(), 5)
out["asks_speaker"] = [editing(), view.currentIndex().row(), view.currentIndex().column(),
                       combo is not None and combo.view().isVisible()]
combo.view().setCurrentIndex(combo.model().index(combo.findData("S1"), 0))
QTest.keyClick(combo.view(), Qt.Key_Return)  # picked in the open list
splitter.activateWindow()  # as Windows does once the list closes; the offscreen platform doesn't
app.processEvents()
out["picked"] = [s.speaker for s in splitter.t.segments]
splitter.undo()
out["speaker_undone"] = [s.speaker for s in splitter.t.segments]
splitter.undo()
out["split_undone"] = [[s.speaker, s.start, s.end, s.text, len(s.words)] for s in splitter.t.segments]

# While a text is being edited, only its segment plays: to its end, and from its start if the audio
# was elsewhere. Space then goes on after it.
splitter.play_from(1)
editor = edit_text(1, 0)
play_frames(16000)
out["edit_plays_on"] = splitter.player.playing  # 2.5 s, inside the segment
play_frames(32000)
splitter._tick()
out["edit_stops"] = [splitter.player.playing, round(splitter.player.position(), 2), splitter.btn_play.text()]
QTest.keyClick(editor, Qt.Key_Return)
app.processEvents()  # Qt closes the editor once Enter's event is done
QTest.keyClick(view, Qt.Key_Space)
out["space_goes_on"] = [splitter.player.playing, round(splitter.player.position(), 2)]
streams = len(Stream.made)
editor = edit_text(0, 0)  # the audio is at 3.9 s, and the first segment is edited
out["jumped"] = [len(Stream.made) - streams, round(splitter.player.position(), 2)]
play_frames(32000)
splitter._tick()
out["jump_stops"] = [splitter.player.playing, round(splitter.player.position(), 2)]
QTest.keyClick(editor, Qt.Key_Escape)
splitter.play_from(2)
QTest.keyClick(edit_text(2, 0), Qt.Key_Return)  # done before the segment ends: it plays on
app.processEvents()
play_frames(16000)
out["plays_on_after_edit"] = [splitter.player.playing, round(splitter.player.position(), 2)]
splitter.toggle_play()
out["split_clean"] = not splitter.dirty
splitter.close()

# A long lecture opens quickly.
words = [TWord(i * 0.5, i * 0.5 + 0.4, f" word{i % 50}", 0.2 if i % 7 == 0 else 0.9) for i in range(30000)]
segments = [Segment(f"S{1 + k % 3}", words[k * 10].start, words[k * 10 + 9].end,
                    " ".join(w.text.strip() for w in words[k * 10:k * 10 + 10]), words[k * 10:k * 10 + 10])
            for k in range(3000)]
big = Transcript(source="none.wav", duration=15000.0, language="en", created="", app_version="0.1.5", settings={},
                 speakers={"S1": "A", "S2": "B", "S3": "C"}, segments=segments)
big.save(folder / "big_transcript.json")
started = time.perf_counter()
long_window = ProofreadWindow(folder / "big_transcript.json", Settings())
long_window.show()
app.processEvents()
out["big_seconds"] = round(time.perf_counter() - started, 2)
out["big_rows"] = long_window.model.rowCount()
out["no_recording"] = long_window.btn_find.isVisible() and not long_window.btn_play.isEnabled()
long_window.close()
print(json.dumps(out))
'''


def test_the_proofreading_window(tmp_path):
    env = {**os.environ, "QT_QPA_PLATFORM": "offscreen"}
    proc = subprocess.run([sys.executable, "-c", SCRIPT, str(tmp_path)], cwd=ROOT, env=env,
                          capture_output=True, text=True, encoding="utf-8", timeout=180)
    assert proc.returncode == 0, proc.stderr[-3000:]
    out = json.loads(proc.stdout.strip().splitlines()[-1])
    assert out["loaded"]
    assert out["rows"] == [["00:00:00", "Speaker 1", "Hello, everyone."], ["00:00:01", "Speaker 2", "Thanks Sam."],
                           ["00:00:03", "Speaker 1", "Let's start."]]
    assert out["unsure_tip"] == "Words Whisper was unsure of: everyone."
    # Yellow as in Word exports on a light background; on a dark one, light text on dark amber.
    assert out["unsure_colors"] == [["#FEF08A", "#111827"], ["#854D0E", "#f3f4f6"]]
    assert out["edit"] and out["dirty_title"] and "edited" in out["edited_tip"]
    assert out["speakers_renamed"] == {"S1": "Prof. Lee", "S2": "Speaker 2"} and out["row0_speaker"] == "Prof. Lee"
    assert out["list"] == ["Prof. Lee", "Speaker 2"] and out["list_after_empty"] == ["Prof. Lee", "Speaker 2"]
    assert out["speaker_edit"]
    assert out["streams"] == 1 and out["row_follows"] == 1  # the audio reached the second segment
    assert out["paused"] and out["resumed_at"] == 1.6  # play again goes on where the pause stopped
    assert out["click_stays"] == 2 and out["space_follows"] == 1  # picked while playing: kept until play again
    assert out["wheel_scrolled"] and out["scroll_stays"] == 0
    assert out["dclick_follows"] == [20, 40]  # 2 s is 20 segments on
    assert out["pieces"] == [["Sam", "match"], [" said ", None], ["hello", "unsure"], [" to ", None],
                             ["Sam", "current"], [".", None]]
    assert out["pieces_over_unsure"] == [["a ", None], ["b", "unsure"], ["c ", "match"], ["d", None]]
    assert {"Ctrl+F", "Ctrl+H", "F3", "Shift+F3"} <= set(out["find_keys"])
    assert out["find_shown"] == [True, False, True]
    assert out["first"] == [[0, 0, 3], "1 of 3", 0]
    assert out["steps"] == [[0, 18, 21], [2, 0, 3], [0, 0, 3], [2, 0, 3]]  # around the end, both ways
    assert out["delegate"] == [["sam", False], [2, 0, 3]]
    assert out["match_case"] == [[2, 0, 3], "1 of 1"]
    assert out["replace_shown"]
    assert out["replace"] == [True, "Pam is here.", [0, 0, 3], True]  # and on to the next match
    assert out["replace_undone"] == ["sam is here.", False]
    assert out["replace_all"] == [3, ["Pam said hello to Pam.", "Then Pam left.", "Pam is here.", "Nothing."],
                                  "Replaced: 3.", "No matches"]
    assert out["all_undone"] == [["Sam said hello to Sam.", "Then Pam left.", "sam is here.", "Nothing."], False]
    assert out["replace_finds_first"] == [False, [0, 0, 3], "Sam said hello to Sam.", "1 of 3"]  # shown, not replaced
    assert out["never_empty"] == [False, "Nothing.", True]
    assert out["find_hidden"] == [False, None, True]
    assert out["enter_keeps"] == [3, False]
    assert out["split"] == [["S1", 0.0, 0.9, "Hello, everyone."], ["S2", 1.5, 2.4, "Thanks Sam."],
                            ["S2", 3.0, 3.9, "Let's start."], ["S1", 4.0, 4.9, "Good."]]
    assert out["asks_speaker"] == [True, 2, 1, True]  # the new segment's speaker, its list open
    assert out["picked"] == ["S1", "S2", "S1", "S1"] and out["speaker_undone"] == ["S1", "S2", "S2", "S1"]
    assert out["split_undone"] == [["S1", 0.0, 0.9, "Hello, everyone.", 2],
                                   ["S2", 1.5, 3.9, "Thanks Sam. Let's start.", 4], ["S1", 4.0, 4.9, "Good.", 1]]
    assert out["edit_plays_on"] and out["edit_stops"] == [False, 3.9, "Play"]
    assert out["space_goes_on"] == [True, 3.9]
    assert out["jumped"] == [1, 0.0] and out["jump_stops"] == [False, 0.9]
    assert out["plays_on_after_edit"] == [True, 5.0] and out["split_clean"]
    assert out["merged"] == 2 and out["speakers_merged"] == {"S1": "Prof. Lee"}
    assert out["unmerged"] == [{"S1": "Prof. Lee", "S2": "Speaker 2"}, ["S1", "S2", "S2"]]
    assert out["rows_after_delete"] == 2 and out["rows_after_undo"] == [3, "Hello, everyone."]
    assert out["text_undone"] == "Let's start."
    assert out["dirty_after_edit"] and out["clean_after_undo"]
    assert out["saved"] and out["clean_title"]
    assert "Thank you, Sam." in out["txt"] and "Speaker 2" not in out["txt"]
    assert out["json_speakers"] == {"S1": "Prof. Lee"}
    assert out["json_texts"] == ["Hello, everyone.", "Thank you, Sam.", "Let's start."]
    assert out["cancel_keeps_open"] and out["discard_closes"] and out["discarded"] == "Hello, everyone."
    assert out["reused"] and out["stray"] and out["forgotten"]
    assert out["save_as"] and out["save_as_suggested"] == ["class_transcript (2).json"]  # replaces nothing
    assert out["save_as_files"] == ["checked_transcript.json", "checked_transcript.txt"]  # the run's formats
    assert out["save_as_text"] == "Hello, all." and out["save_as_clean"]
    assert out["then_save"] == "Hello, you all." and out["originals_kept"]  # Save goes on with the new files
    assert out["by_new_name"] and out["by_old_name"]
    assert out["refused_while_open"] and out["asked_first"] and out["kept_when_no"]
    assert out["all_forgotten"]
    assert out["big_rows"] == 3000 and out["no_recording"]
    assert out["big_seconds"] < 10, out["big_seconds"]
