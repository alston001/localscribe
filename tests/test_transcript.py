"""_transcript.json is what a proofreading editor will read: it must load safely and say one thing."""

import json
import pathlib

import numpy as np
import pytest

from localscribe.core import asr, transcript as transcript_module
from localscribe.core.errors import UserError
from localscribe.core.transcript import FORMAT_VERSION, Gap, Segment, Transcript, TWord
from localscribe.export.common import segment_words, sentence_rows


def full_transcript() -> Transcript:
    return Transcript(
        source="訪談.m4a", duration=95.0, language="zh", created="2026-10-15T10:00:00", app_version="0.1.1",
        settings={"whisper_model": "large-v3", "timings_s": {"decode": 0.4}},
        speakers={"S1": "說話人 1", "S2": "Speaker 2"},
        segments=[Segment("S1", 0.0, 1.2, "大家好。", [TWord(0.0, 0.6, "大家", 0.912), TWord(0.6, 1.2, "好。", 0.8)]),
                  Segment("S2", 2.0, 3.5, "Hi there.", [TWord(2.0, 2.5, " Hi", 0.9), TWord(2.6, 3.5, " there.", 1.0)])],
        warnings=[{"key": "warn_fewer_speakers", "found": 2, "requested": 3}],
        gaps=[Gap(3.5, 41.25, True), Gap(41.25, 95.0)])


def write(path, data: dict) -> pathlib.Path:
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return path


# ---- B1 / B5: load ---------------------------------------------------------------
def test_every_field_survives_a_round_trip(tmp_path):
    original = full_transcript()
    original.save(tmp_path / "t.json")
    assert "說話人" in (tmp_path / "t.json").read_text(encoding="utf-8")  # readable, not \u escapes
    assert Transcript.load(tmp_path / "t.json") == original


def test_unknown_keys_are_ignored(tmp_path):
    data = full_transcript().to_dict()
    data["reviewed_by"] = "editor"
    data["segments"][0]["note"] = "check this"
    data["segments"][0]["words"][0]["style"] = "bold"
    data["gaps"][0]["reason"] = "lecture break"
    assert Transcript.load(write(tmp_path / "t.json", data)) == full_transcript()


def test_a_newer_format_is_refused(tmp_path):
    data = full_transcript().to_dict()
    data["format_version"] = FORMAT_VERSION + 1
    with pytest.raises(UserError) as caught:
        Transcript.load(write(tmp_path / "t.json", data))
    assert caught.value.key == "err_transcript_newer"


def test_older_files_get_defaults_for_newer_fields(tmp_path):
    data = full_transcript().to_dict()
    del data["warnings"], data["format_version"], data["gaps"]
    for seg in data["segments"]:
        del seg["words"]
    loaded = Transcript.load(write(tmp_path / "t.json", data))
    assert loaded.warnings == [] and [s.words for s in loaded.segments] == [[], []]
    assert loaded.gaps == []  # files before the gap markers: no markers, rather than guessed ones


def test_gaps_say_whether_speech_was_heard(tmp_path):
    full_transcript().save(tmp_path / "t.json")
    data = json.loads((tmp_path / "t.json").read_text(encoding="utf-8"))
    assert data["gaps"] == [{"start": 3.5, "end": 41.25, "speech": True},
                            {"start": 41.25, "end": 95.0, "speech": False}]


# ---- B2: one text source ---------------------------------------------------------
def test_words_are_used_when_they_match_the_text():
    seg = full_transcript().segments[1]
    assert segment_words(seg) == seg.words


def test_edited_text_wins_over_stale_words():
    seg = full_transcript().segments[1]
    seg.text = "Hi there, Sam."  # corrected in an editor; the word timings were not
    words = segment_words(seg)
    assert [w.text for w in words] == ["Hi there, Sam."]
    assert (words[0].start, words[0].end) == (seg.start, seg.end)


def test_cjk_words_match_their_text():
    seg = full_transcript().segments[0]
    assert segment_words(seg) == seg.words
    assert sentence_rows(full_transcript())[0][3] == "大家好。"


# ---- B3: atomic save -------------------------------------------------------------
def test_a_failed_save_keeps_the_previous_file(tmp_path, monkeypatch):
    path = tmp_path / "t.json"
    full_transcript().save(path)
    before = path.read_bytes()

    def disk_full(self, text, encoding=None, **kwargs):
        with open(self, "w", encoding=encoding) as f:
            f.write(text[: len(text) // 2])
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(pathlib.Path, "write_text", disk_full)
    with pytest.raises(OSError):
        full_transcript().save(path)
    monkeypatch.undo()
    assert path.read_bytes() == before
    assert [p.name for p in tmp_path.iterdir()] == ["t.json"]


# ---- B4: language ----------------------------------------------------------------
def test_no_clips_does_not_claim_english(monkeypatch):
    monkeypatch.setattr(asr, "speech_clips", lambda audio: [])
    transcriber = object.__new__(asr.Transcriber)
    result = transcriber.transcribe(np.zeros(16000, np.float32), language=None)
    assert result.language == "" and result.words == []


def test_a_damaged_gap_list_costs_only_the_gaps(tmp_path):
    # Gaps are extras: a null list or a gap without times must not make the transcript unreadable.
    data = full_transcript().to_dict()
    data["gaps"] = None
    assert Transcript.load(write(tmp_path / "a.json", data)).gaps == []
    data["gaps"] = [{"start": 3.5}, "x", {"start": 41.25, "end": 95.0}]
    assert Transcript.load(write(tmp_path / "b.json", data)).gaps == [Gap(41.25, 95.0)]
