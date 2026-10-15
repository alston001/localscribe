import json

from localscribe.config import Settings
from localscribe.core.transcript import Segment, Transcript, TWord
from localscribe.export import FORMATS, output_base, write_outputs
from localscribe.export.common import ExportOptions, clock, sentence_rows, subtitle_cues


def make_transcript(language="en"):
    def seg(speaker, start, text):
        tokens, t, ws = text.split(), start, []
        for tok in tokens:
            ws.append(TWord(t, t + 0.3, " " + tok, 0.9))
            t += 0.35
        return Segment(speaker, ws[0].start, ws[-1].end, text, ws)

    return Transcript(
        source="C:/rec/interview.mp4", duration=30.0, language=language, created="2026-10-15T10:00:00",
        app_version="test", settings={"whisper_model": "large-v3", "diarizer": "pyannote"},
        speakers={"S1": "Speaker 1", "S2": "Speaker 2"},
        segments=[
            seg("S1", 0.0, "Thank you for coming. Could you introduce yourself?"),
            seg("S2", 5.0, "Sure. I study how older adults use voice assistants at home every day."),
            seg("S1", 12.0, "Great."),
        ])


def test_clock_formats():
    assert clock(3723.456) == "01:02:03"
    assert clock(3723.456, millis=True, sep=",") == "01:02:03,456"
    assert clock(-1) == "00:00:00"


def test_sentence_rows_split_segments():
    rows = sentence_rows(make_transcript())
    assert [r[3] for r in rows][:3] == ["Thank you for coming.", "Could you introduce yourself?", "Sure."]
    assert rows[2][2] == "Speaker 2"


def test_subtitles_label_speaker_changes_only_and_avoid_orphans():
    cues = subtitle_cues(make_transcript(), ExportOptions())
    labelled = [c for c in cues if c.speaker]
    assert [c.speaker for c in labelled] == ["Speaker 1", "Speaker 2", "Speaker 1"]
    texts = [" ".join(c.lines) for c in cues]
    assert not any(t.strip() in ("home.", "day.") for t in texts)
    assert all(len(line) <= 60 for c in cues for line in c.lines)
    for a, b in zip(cues, cues[1:]):
        assert a.end <= b.start


def test_output_base_never_overwrites(tmp_path):
    (tmp_path / "talk_transcript.docx").write_text("x")
    assert output_base(tmp_path, "talk", ["txt"]) == "talk_transcript"
    assert output_base(tmp_path, "talk", ["docx", "txt"]) == "talk_transcript (2)"


def test_write_all_formats(tmp_path):
    written = write_outputs(make_transcript(), tmp_path, list(FORMATS), ExportOptions(lang="zh_TW"))
    assert [p.suffix for p in written] == [".json"] + [ext for ext, _ in FORMATS.values()]
    data = json.loads(written[0].read_text(encoding="utf-8"))
    assert data["format_version"] == 1 and data["speakers"]["S2"] == "Speaker 2"
    assert (tmp_path / "interview_transcript.txt").read_text(encoding="utf-8").count("Speaker 1:") == 2
    assert (tmp_path / "interview_transcript.csv").read_bytes().startswith(b"\xef\xbb\xbf")
    srt = (tmp_path / "interview_transcript.srt").read_text(encoding="utf-8")
    assert srt.startswith("1\n00:00:00,000 --> ")


def test_transcript_round_trip(tmp_path):
    t = make_transcript()
    t.save(tmp_path / "t.json")
    again = Transcript.load(tmp_path / "t.json")
    assert again.segments[1].words[0].text == " Sure."
    assert again.speaker_name("S1") == "Speaker 1"


def test_settings_ignore_bad_values(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"formats": ["docx", "bogus"], "speakers_exact": "two", "preset": "zzz",
                                "unknown_key": 1}), encoding="utf-8")
    s = Settings.load(path)
    assert s.formats == ["docx"] and s.speakers_exact == 2 and s.preset == "custom"
    path.write_text("{not json", encoding="utf-8")
    assert Settings.load(path).formats == ["docx", "txt"]
