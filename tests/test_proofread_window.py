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
        self.callback = callback
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

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QMessageBox
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

out["merged"] = window.merge_speaker("S2", "S1")
app.processEvents()
out["speakers_merged"] = dict(window.t.speakers)
out["saved"] = window.save()
out["clean_title"] = not window.windowTitle().startswith("* ")
out["txt"] = (folder / "class_transcript.txt").read_text(encoding="utf-8")
saved = Transcript.load(json_path)
out["json_speakers"] = saved.speakers
out["json_texts"] = [s.text for s in saved.segments]

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
fake = types.SimpleNamespace(_proofreaders={}, settings=Settings())
first = MainWindow.open_proofread(fake, json_path)
out["reused"] = MainWindow.open_proofread(fake, json_path) is first and len(fake._proofreaders) == 1
(folder / "other.json").write_text('{"name": "not a transcript"}', encoding="utf-8")
out["stray"] = MainWindow.open_proofread(fake, folder / "other.json") is None and len(warnings) == 1
first.close()
out["forgotten"] = fake._proofreaders == {}

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
    assert out["edit"] and out["dirty_title"] and "edited" in out["edited_tip"]
    assert out["speakers_renamed"] == {"S1": "Prof. Lee", "S2": "Speaker 2"} and out["row0_speaker"] == "Prof. Lee"
    assert out["list"] == ["Prof. Lee", "Speaker 2"] and out["list_after_empty"] == ["Prof. Lee", "Speaker 2"]
    assert out["speaker_edit"]
    assert out["streams"] == 1 and out["row_follows"] == 1  # the audio reached the second segment
    assert out["paused"] and out["resumed_at"] == 1.6  # play again goes on where the pause stopped
    assert out["merged"] == 2 and out["speakers_merged"] == {"S1": "Prof. Lee"}
    assert out["saved"] and out["clean_title"]
    assert "Thank you, Sam." in out["txt"] and "Speaker 2" not in out["txt"]
    assert out["json_speakers"] == {"S1": "Prof. Lee"}
    assert out["json_texts"] == ["Hello, everyone.", "Thank you, Sam.", "Let's start."]
    assert out["cancel_keeps_open"] and out["discard_closes"] and out["discarded"] == "Hello, everyone."
    assert out["reused"] and out["stray"] and out["forgotten"]
    assert out["big_rows"] == 3000 and out["no_recording"]
    assert out["big_seconds"] < 10, out["big_seconds"]
