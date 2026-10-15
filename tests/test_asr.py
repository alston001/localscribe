"""What the voice detector heard versus what Whisper wrote, with fake segments (no model needed)."""

import sys
import types

import numpy as np

from localscribe.core import asr
from localscribe.core.asr import Word, lost_speech


def talk(start: float, end: float) -> list[Word]:
    """A word every half second."""
    return [Word(float(t), float(t) + 0.4, " word", 0.9) for t in np.arange(start, end, 0.5)]


# ---- lost speech -------------------------------------------------------------------
def test_speech_without_words_is_reported():
    speech = [(0.0, 27.0), (27.5, 55.0), (55.4, 83.0), (83.2, 110.0), (110.3, 130.0)]
    words = talk(0.0, 26.0) + talk(111.0, 130.0)  # the text stops at 25.9 s and resumes at 111 s
    assert lost_speech(speech, words) == [(25.9, 111.0)]


def test_real_silence_is_not_reported():
    speech = [(0.0, 26.0), (111.0, 130.0)]
    assert lost_speech(speech, talk(0.0, 26.0) + talk(111.0, 130.0)) == []


def test_scattered_noises_in_a_long_silence_are_not_reported():
    # A cough or a chair every 20 s for ten minutes: 43 s of "speech", but never 30 s at a stretch.
    noises = [(float(t), float(t) + 1.5) for t in range(30, 600, 20)]
    speech = [(0.0, 20.0)] + noises + [(600.0, 620.0)]
    assert lost_speech(speech, talk(0.0, 20.0) + talk(600.0, 620.0)) == []


def test_a_short_stretch_without_words_is_not_reported():
    speech = [(0.0, 20.0), (20.5, 40.0), (40.5, 60.0)]
    assert lost_speech(speech, talk(0.0, 20.0) + talk(40.5, 60.0)) == []


def test_lost_speech_at_the_start_and_end_is_reported():
    speech = [(0.0, 28.0), (28.0, 56.0), (56.0, 60.0), (60.0, 88.0), (88.0, 116.0)]
    assert lost_speech(speech, talk(56.0, 60.0)) == [(0.0, 56.0), (59.9, 116.0)]


def test_no_words_at_all_is_one_stretch():
    assert lost_speech([(3.0, 30.0), (31.0, 50.0)], []) == [(3.0, 50.0)]


# ---- what Transcriber.transcribe reports ---------------------------------------------
class FakeSegment:
    def __init__(self, start, end, words, text=None):
        self.start, self.end, self.words = start, end, words
        self.text = text if text is not None else "".join(w.word for w in words)


class FakeWord:
    def __init__(self, start, end, word, probability=0.9):
        self.start, self.end, self.word, self.probability = start, end, word, probability


class FakeModel:
    """Stands in for faster_whisper.WhisperModel: one segment per call, at the start of the audio."""

    def __init__(self):
        self.calls = []

    def transcribe(self, audio, **options):
        self.calls.append((len(audio), options))
        words = [FakeWord(0.5, 0.9, " Hello."), FakeWord(1.0, 1.4, " Again.")]
        info = type("Info", (), {"language": options.get("language") or "en", "language_probability": 1.0})()
        return iter([FakeSegment(0.5, 1.4, words)]), info


def fake_transcriber(monkeypatch, clips):
    monkeypatch.setattr(asr, "speech_clips", lambda audio: clips)
    transcriber = object.__new__(asr.Transcriber)
    transcriber.model = FakeModel()
    return transcriber


def test_transcribe_reports_where_it_heard_speech(monkeypatch):
    clips = [(1.0, 20.0), (25.0, 40.0)]
    transcriber = fake_transcriber(monkeypatch, clips)
    result = transcriber.transcribe(np.zeros(16000 * 45, np.float32), language="en")
    assert result.speech == clips


def test_fast_mode_reports_the_regions_it_decoded(monkeypatch):
    used = {}

    class FakeBatched:
        def __init__(self, model):
            self.model = model

        def transcribe(self, audio, batch_size, vad_filter, vad_parameters, **options):
            used["decoded with"] = vad_parameters
            return self.model.transcribe(audio, **options)

    def get_speech_timestamps(audio, options):
        used["checked with"] = options
        return [{"start": 16000, "end": 16000 * 20}, {"start": 16000 * 25, "end": 16000 * 40}]

    fake_fw = types.ModuleType("faster_whisper")
    fake_fw.BatchedInferencePipeline = FakeBatched
    fake_vad = types.ModuleType("faster_whisper.vad")
    fake_vad.VadOptions = lambda **kw: dict(kw)
    fake_vad.get_speech_timestamps = get_speech_timestamps
    monkeypatch.setitem(sys.modules, "faster_whisper", fake_fw)
    monkeypatch.setitem(sys.modules, "faster_whisper.vad", fake_vad)
    transcriber = fake_transcriber(monkeypatch, [])
    result = transcriber.transcribe(np.zeros(16000 * 45, np.float32), language="en", batch_size=8)
    assert result.speech == [(1.0, 20.0), (25.0, 40.0)]
    assert used["checked with"] is used["decoded with"]
