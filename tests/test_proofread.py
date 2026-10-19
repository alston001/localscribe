"""Proofreading without Qt: edits to a Transcript, writing its files again, and playback."""

import os
import sys
import time
import types
from pathlib import Path

import numpy as np
import pytest

from localscribe.core import proofread
from localscribe.core.errors import UserError
from localscribe.core.transcript import Gap, Segment, Transcript, TWord
from localscribe.export import write_outputs
from localscribe.export.common import ExportOptions, segment_words


def make_transcript() -> Transcript:
    return Transcript(
        source="class.m4a", duration=60.0, language="en", created="2026-10-17T10:00:00", app_version="0.1.5",
        settings={}, speakers={"S1": "Speaker 1", "S2": "Speaker 2"},
        segments=[Segment("S1", 0.0, 0.9, "Hello, everyone.", [TWord(0.0, 0.4, " Hello,", 0.9),
                                                                TWord(0.5, 0.9, " everyone.", 0.3)]),
                  Segment("S2", 1.5, 2.4, "Thanks Sam.", [TWord(1.5, 1.9, " Thanks", 0.9),
                                                          TWord(2.0, 2.4, " Sam.", 0.9)]),
                  Segment("S1", 3.0, 3.9, "Let's start.", [TWord(3.0, 3.4, " Let's", 0.9),
                                                            TWord(3.5, 3.9, " start.", 0.9)])],
        gaps=[Gap(10.0, 60.0, False)])


# ---- edits --------------------------------------------------------------------------
def test_renaming_a_speaker_names_all_their_segments():
    t = make_transcript()
    assert proofread.rename_speaker(t, "S1", "  Prof.   Lee ")
    assert t.speakers == {"S1": "Prof. Lee", "S2": "Speaker 2"}
    assert not proofread.rename_speaker(t, "S1", "   ")  # an empty name is no name
    assert not proofread.rename_speaker(t, "S1", "Prof. Lee")  # nothing changed


def test_merging_speakers_moves_their_segments():
    t = make_transcript()
    assert proofread.merge_speakers(t, "S2", "S1") == 1
    assert [s.speaker for s in t.segments] == ["S1", "S1", "S1"] and t.speakers == {"S1": "Speaker 1"}
    assert proofread.merge_speakers(t, "S1", "S1") == 0


def test_a_segment_can_go_to_another_or_a_new_speaker():
    t = make_transcript()
    assert proofread.set_speaker(t, 1, "S1") and t.segments[1].speaker == "S1"
    assert not proofread.set_speaker(t, 1, "S1")  # nothing changed
    new = proofread.add_speaker(t, " Student ")
    assert new == "S3" and t.speakers[new] == "Student"
    assert proofread.set_speaker(t, 2, new) and t.segments[2].speaker == "S3"
    assert not proofread.set_speaker(t, 2, "S9")  # no such speaker


def test_edited_text_wins_and_its_words_come_back_with_it():
    t = make_transcript()
    assert proofread.set_text(t, 0, "  Hello, everybody. ")
    assert t.segments[0].text == "Hello, everybody." and len(t.segments[0].words) == 2
    assert [w.text for w in segment_words(t.segments[0])] == ["Hello, everybody."]  # the text is the truth
    assert proofread.set_text(t, 0, "Hello, everyone.")
    assert segment_words(t.segments[0]) == t.segments[0].words  # timing and confidence are back
    assert not proofread.set_text(t, 0, "   ")  # deleting is its own action
    assert not proofread.set_text(t, 0, "Hello, everyone.")


def test_deleting_a_segment_and_speakers_left_without_any():
    t = make_transcript()
    proofread.delete_segment(t, 1)
    assert [s.text for s in t.segments] == ["Hello, everyone.", "Let's start."]
    assert proofread.unused_speakers(t) == ["S2"]
    proofread.drop_unused_speakers(t)
    assert t.speakers == {"S1": "Speaker 1"}


def test_the_segment_playing_at_a_time():
    t = make_transcript()
    assert [proofread.segment_at(t, x) for x in (-1.0, 0.0, 1.0, 1.6, 2.9, 3.0, 50.0)] == [None, 0, 0, 1, 1, 2, 2]


def test_talk_time_per_speaker():
    assert proofread.talk_time(make_transcript()) == {"S1": pytest.approx(1.8), "S2": pytest.approx(0.9)}


def test_the_recording_is_looked_for_next_to_the_transcript(tmp_path):
    json_path = tmp_path / "class_transcript.json"
    assert proofread.find_recording(make_transcript(), json_path) is None
    (tmp_path / "class.m4a").write_bytes(b"")
    assert proofread.find_recording(make_transcript(), json_path) == tmp_path / "class.m4a"
    assert proofread.find_recording(make_transcript(), json_path, hint=tmp_path / "x.wav") == tmp_path / "class.m4a"
    (tmp_path / "x.wav").write_bytes(b"")
    assert proofread.find_recording(make_transcript(), json_path, hint=tmp_path / "x.wav") == tmp_path / "x.wav"


# ---- writing the files again ----------------------------------------------------------
def test_saving_writes_the_transcript_and_its_formats_again(tmp_path):
    t = make_transcript()
    written = write_outputs(t, tmp_path, ["txt", "srt"], ExportOptions())
    json_path = next(p for p in written if p.suffix == ".json")
    (tmp_path / "other_transcript.txt").write_text("someone else's", encoding="utf-8")
    proofread.set_text(t, 1, "Thank you, Sam.")
    proofread.set_speaker(t, 1, "S1")
    rewritten = proofread.save(t, json_path, ExportOptions())
    assert t.speakers == {"S1": "Speaker 1", "S2": "Speaker 2"}  # the window may still give S2 a segment
    assert Transcript.load(json_path).speakers == {"S1": "Speaker 1"}
    assert sorted(p.name for p in rewritten) == sorted(p.name for p in written)  # the same files, no new ones
    assert "Thank you, Sam." in (tmp_path / "class_transcript.txt").read_text(encoding="utf-8")
    assert Transcript.load(json_path).segments[1].text == "Thank you, Sam."
    assert (tmp_path / "other_transcript.txt").read_text(encoding="utf-8") == "someone else's"
    assert not [p for p in tmp_path.iterdir() if p.name.startswith(".localscribe-")]  # no staging left


def test_files_changed_after_the_transcript_are_named_before_they_are_replaced(tmp_path):
    t = make_transcript()
    written = write_outputs(t, tmp_path, ["txt", "docx"], ExportOptions())
    json_path = next(p for p in written if p.suffix == ".json")
    assert proofread.changed_since(json_path) == []
    later = time.time() + 60
    os.utime(tmp_path / "class_transcript.docx", (later, later))  # edited in Word afterwards
    assert proofread.changed_since(json_path) == [tmp_path / "class_transcript.docx"]


def test_a_locked_file_stops_the_save_before_anything_is_replaced(tmp_path, monkeypatch):
    t = make_transcript()
    written = write_outputs(t, tmp_path, ["txt"], ExportOptions())
    json_path = next(p for p in written if p.suffix == ".json")
    before = {p.name: p.read_bytes() for p in written}
    locked = tmp_path / "class_transcript.txt"
    real_open = open

    def fake_open(path, mode="r", *args, **kwargs):  # Word holds the file the way Windows locks it
        if os.path.abspath(path) == os.path.abspath(locked) and mode == "r+b":
            raise PermissionError(13, "in use", str(path))
        return real_open(path, mode, *args, **kwargs)

    monkeypatch.setattr("builtins.open", fake_open)
    proofread.set_text(t, 0, "Changed.")
    with pytest.raises(UserError) as caught:
        proofread.save(t, json_path, ExportOptions())
    assert caught.value.key == "err_file_in_use" and caught.value.kwargs["path"] == str(locked)
    assert {p.name: p.read_bytes() for p in written} == before


def test_save_as_writes_new_files_and_keeps_the_ones_it_came_from(tmp_path):
    t = make_transcript()
    written = write_outputs(t, tmp_path, ["txt", "srt"], ExportOptions())
    json_path = next(p for p in written if p.suffix == ".json")
    before = {p.name: p.read_bytes() for p in written}
    (tmp_path / "checked").mkdir()
    copy = tmp_path / "checked" / "class-checked_transcript.json"
    proofread.set_text(t, 1, "Thank you, Sam.")
    saved = proofread.save_as(t, json_path, copy, ExportOptions())
    assert sorted(p.name for p in saved) == ["class-checked_transcript.json", "class-checked_transcript.srt",
                                             "class-checked_transcript.txt"]  # the formats of the run
    assert {p.parent for p in saved} == {copy.parent} and saved[-1] == copy  # the transcript last
    assert Transcript.load(copy).segments[1].text == "Thank you, Sam."
    assert "Thank you, Sam." in (copy.parent / "class-checked_transcript.txt").read_text(encoding="utf-8")
    assert {p.name: p.read_bytes() for p in written} == before
    assert not [p for p in copy.parent.iterdir() if p.name.startswith(".localscribe-")]


def test_a_name_typed_for_save_as_becomes_a_transcript_name(tmp_path):
    for typed in ("checked", "checked.json", "checked_transcript", "checked_transcript.json"):
        assert proofread.transcript_path(tmp_path / typed) == tmp_path / "checked_transcript.json", typed
    assert proofread.transcript_path(tmp_path / "class_transcript (2).json") == tmp_path / "class_transcript (2).json"


def test_save_as_suggests_a_name_that_replaces_nothing(tmp_path):
    written = write_outputs(make_transcript(), tmp_path, ["txt"], ExportOptions())
    json_path = next(p for p in written if p.suffix == ".json")
    assert proofread.save_as_name(json_path) == tmp_path / "class_transcript (2).json"
    (tmp_path / "class_transcript (2).txt").write_text("another run", encoding="utf-8")
    assert proofread.save_as_name(json_path) == tmp_path / "class_transcript (3).json"
    assert proofread.save_as_files(json_path, tmp_path / "x_transcript.json") == [tmp_path / "x_transcript.txt",
                                                                                  tmp_path / "x_transcript.json"]


def test_a_folder_that_cannot_be_written_is_a_message(tmp_path, monkeypatch):
    written = write_outputs(make_transcript(), tmp_path, ["txt"], ExportOptions())
    json_path = next(p for p in written if p.suffix == ".json")

    def refused(*args, **kwargs):  # as in a folder only administrators may write to
        raise PermissionError(13, "Access is denied", str(Path(kwargs["dir"]) / ".localscribe-x"))

    monkeypatch.setattr(proofread.tempfile, "mkdtemp", refused)
    with pytest.raises(UserError) as caught:
        proofread.save_as(make_transcript(), json_path, tmp_path / "x_transcript.json", ExportOptions())
    assert caught.value.key == "err_write" and caught.value.kwargs["path"] == str(tmp_path / "x_transcript.json")


def test_the_bundle_takes_sounddevice_with_one_portaudio_library():
    root = Path(__file__).resolve().parent.parent
    spec = (root / "packaging" / "localscribe.spec").read_text(encoding="utf-8")
    assert 'Path(entry[0]).name == "libportaudio64bit.dll"' in spec  # not the ASIO or other builds
    assert any(line.startswith("sounddevice==") for line in (root / "requirements.txt").read_text().splitlines())


# ---- playback ---------------------------------------------------------------------------
class FakeStream:
    made: list["FakeStream"] = []

    def __init__(self, samplerate, channels, dtype, callback, finished_callback=None):
        self.samplerate, self.channels, self.dtype = samplerate, channels, dtype
        self.callback, self.finished_callback = callback, finished_callback
        self.started = self.closed = False
        FakeStream.made.append(self)

    def start(self):
        self.started = True

    def stop(self):
        pass

    def close(self):
        self.closed = True

    def pull(self, frames: int) -> np.ndarray | None:
        """What the sound card would get next; None once the callback said stop."""
        out = np.full((frames, 1), 99, np.int16)
        try:
            self.callback(out, frames, None, None)
        except CallbackStop:
            return None if not out.any() else out[:, 0]
        return out[:, 0]


class CallbackStop(Exception):
    pass


@pytest.fixture
def fake_sound(monkeypatch):
    FakeStream.made = []
    module = types.ModuleType("sounddevice")
    module.OutputStream, module.CallbackStop, module.PortAudioError = FakeStream, CallbackStop, OSError
    monkeypatch.setitem(sys.modules, "sounddevice", module)
    return module


def test_playing_a_stretch_sends_just_that_audio(fake_sound):
    from localscribe.core.playback import Player

    audio = (np.arange(16000 * 3) % 1000 / 1000.0).astype(np.float32)  # 3 s
    player = Player(audio)
    player.play(1.0, 1.5)
    stream = FakeStream.made[-1]
    assert stream.started and stream.samplerate == 16000 and stream.channels == 1 and player.playing
    first = stream.pull(4000)
    assert np.array_equal(first, (audio[16000:20000] * 32767).astype(np.int16))
    assert player.position() == pytest.approx(1.25)
    rest = stream.pull(8000)  # 4000 frames left, then silence
    assert np.array_equal(rest[:4000], (audio[20000:24000] * 32767).astype(np.int16)) and not rest[4000:].any()
    assert stream.pull(100) is None


def test_playing_again_stops_the_stretch_before(fake_sound):
    from localscribe.core.playback import Player

    player = Player(np.zeros(16000 * 5, np.float32))
    player.play(0.0)
    player.play(2.0, 3.0)
    assert FakeStream.made[0].closed and not FakeStream.made[1].closed
    player.stop()
    assert FakeStream.made[1].closed and not player.playing


def test_no_sound_card_is_a_message_not_a_crash(fake_sound):
    from localscribe.core.playback import Player

    def broken(*args, **kwargs):
        raise OSError("Error querying device -1")

    fake_sound.OutputStream = broken
    with pytest.raises(UserError) as caught:
        Player(np.zeros(1600, np.float32)).play(0.0)
    assert caught.value.key == "err_playback" and "device" in caught.value.kwargs["detail"]
