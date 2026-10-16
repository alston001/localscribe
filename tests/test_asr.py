"""What the voice detector heard versus what Whisper wrote, with fake segments (no model needed)."""

import types

import numpy as np

from localscribe.core import asr
from localscribe.core.asr import Word, drop_sign_offs, lost_speech, text_gaps


def talk(start: float, end: float) -> list[Word]:
    """A word every half second."""
    return [Word(float(t), float(t) + 0.4, " word", 0.9) for t in np.arange(start, end, 0.5)]


def say(*spec: tuple[str, float]) -> list[Word]:
    """Words with the given text and probability, 0.3 s apart."""
    return [Word(i * 0.3, i * 0.3 + 0.25, text, p) for i, (text, p) in enumerate(spec)]


def text(words: list[Word]) -> str:
    return "".join(w.text for w in words)


# ---- invented sign-offs --------------------------------------------------------------
# Probabilities as large-v3 gave them on synthetic audio: invented sign-offs started with a
# word at p 0.02-0.26, spoken ones at p 0.79 or more, also when quiet or over chatter.
def test_an_unsure_thank_you_inside_a_sentence_is_dropped():
    # "...then it has Thank you. the meeting that you want": the end of a clip cut mid-sentence
    words = say((" then", 0.9), (" it", 0.95), (" has", 0.9), (" Thank", 0.07), (" you.", 0.99),
                (" the", 0.8), (" meeting", 0.9))
    assert text(drop_sign_offs(words)) == " then it has the meeting"


def test_sign_offs_invented_for_noise_are_dropped():
    assert drop_sign_offs(say((" Thank", 0.15), (" you.", 1.0))) == []  # a hum
    assert drop_sign_offs(say((" Thanks", 0.02), (" for", 0.9), (" watching!", 0.95))) == []  # music
    assert drop_sign_offs(say((" Thank", 0.26), (" you", 0.99), (" so", 0.9), (" much.", 0.97))) == []


def test_spoken_thanks_are_kept():
    for words in (say((" Thank", 0.89), (" you.", 0.95)), say((" Okay,", 0.9), (" thank", 0.85), (" you.", 0.97)),
                  say((" Thanks.", 0.83),), say((" Right.", 0.9), (" Thank", 0.79), (" you.", 0.95))):
        assert drop_sign_offs(words) == words


def test_sign_offs_about_listening_are_dropped_too():
    # With a word bank sent as a sentence, the sign-off on hum and music became "Thank you for
    # listening." (p 0.16-0.17 for "Thank"), and once it ran on into far-off chatter.
    assert drop_sign_offs(say((" Thank", 0.16), (" you", 1.0), (" for", 0.06), (" listening.", 0.32))) == []
    assert drop_sign_offs(say((" Thanks", 0.2), (" for", 0.5), (" listening!", 0.6))) == []
    words = say((" on.", 1.0), (" Thank", 0.08), (" you", 0.99), (" for", 0.08), (" listening", 0.41), (" to", 0.42),
                (" the", 0.24), (" Thursday", 0.45), (" afternoon.", 0.96))
    assert text(drop_sign_offs(words)) == " on."


def test_longer_sign_offs_are_dropped_to_the_end_of_their_sentence():
    # From a second set of test clips, with and without a word bank.
    words = say((" Thank", 0.18), (" you", 0.99), (" so", 0.32), (" much", 1.0), (" for", 0.37), (" watching,", 0.74),
                (" and", 0.67), (" we'll", 0.6), (" see", 0.94), (" you", 1.0), (" on", 0.57), (" the", 0.86),
                (" next", 0.71), (" one.", 0.35))
    assert drop_sign_offs(words) == []
    words = say(*[(" Thank", 0.13), (" you", 0.99), (" for", 0.3), (" listening", 0.44)]
                + [(f" {w}", 0.5) for w in "to my lecture on how to skip the next part of the budget.".split()])
    assert drop_sign_offs(words) == []


def test_sure_thanks_that_run_on_are_kept():
    words = say((" Thank", 0.9), (" you", 1.0), (" for", 0.9), (" listening,", 0.9), (" and", 0.9), (" the", 0.9),
                (" essay", 0.9), (" is", 0.9), (" due", 0.9), (" Friday.", 0.9))
    assert drop_sign_offs(words) == words


def test_thanks_that_go_on_are_kept():
    # Not a sign-off, even when Whisper is unsure of the first word.
    words = say((" Thank", 0.3), (" you", 0.9), (" for", 0.9), (" the", 0.9), (" question.", 0.9))
    assert drop_sign_offs(words) == words


def test_video_credits_are_dropped_however_sure_whisper_is():
    # With a word bank, hum, music or far-off chatter came out as these at p 0.6-1.0. Only the
    # credit goes: the lecture that follows in the same clip stays.
    words = say((" Subtitles", 0.62), (" by", 0.94), (" the", 0.86), (" Amara", 1.0), (".org", 1.0),
                (" community", 1.0), (" Byte", 0.18), (" pair", 0.03), (" encoding", 0.99), (" starts.", 1.0))
    assert text(drop_sign_offs(words)) == " Byte pair encoding starts."
    assert drop_sign_offs(say((" Transcription", 0.38), (" by", 1.0), (" CastingWords", 0.93))) == []
    assert drop_sign_offs(say((" Transcription", 0.32), (" by", 0.97), (" ESO.", 0.61), (" Translation", 1.0),
                              (" by", 1.0), (" �", 0.99))) == []
    words = say((" Okay.", 0.9), (" Please", 0.6), (" like,", 0.9), (" share,", 0.9), (" and", 0.9),
                (" subscribe", 0.9), (" to", 0.9), (" our", 0.9), (" channel!", 0.9))
    assert text(drop_sign_offs(words)) == " Okay."


def test_sentences_that_only_look_like_credits_are_kept():
    for words in (say((" Transcription", 0.9), (" by", 0.9), (" hand", 0.9), (" is", 0.9), (" slow.", 0.9)),
                  say((" Please", 0.9), (" subscribe", 0.9), (" to", 0.9), (" the", 0.9), (" mailing", 0.9),
                      (" list.", 0.9)),
                  say((" I'd", 0.9), (" like", 0.9), (" to", 0.9), (" share", 0.9), (" this.", 0.9))):
        assert drop_sign_offs(words) == words


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



# ---- gaps: long stretches without text --------------------------------------------
def test_long_stretches_without_text_are_gaps():
    words = talk(0.0, 20.0) + talk(60.0, 80.0)  # nothing between 19.9 s and 60 s, nor after 79.9 s
    assert text_gaps(words, 120.0, []) == [(19.9, 60.0, False), (79.9, 120.0, False)]


def test_pauses_shorter_than_30_seconds_are_not_gaps():
    assert text_gaps(talk(0.0, 20.0) + talk(49.5, 60.0), 60.0, []) == []  # 29.6 s


def test_silence_before_the_first_word_is_a_gap():
    assert text_gaps(talk(45.0, 60.0), 60.0, []) == [(0.0, 45.0, False)]


def test_lost_speech_inside_a_gap_is_a_gap_of_its_own():
    words = talk(0.0, 20.0) + talk(200.0, 220.0)
    assert text_gaps(words, 220.0, [(60.0, 150.0)]) == [
        (19.9, 60.0, False), (60.0, 150.0, True), (150.0, 200.0, False)]


def test_short_silence_beside_lost_speech_is_left_out():
    words = talk(0.0, 20.0) + talk(130.0, 150.0)
    assert text_gaps(words, 150.0, [(30.0, 120.0)]) == [(30.0, 120.0, True)]


def test_no_words_at_all_is_one_gap_split_by_lost_speech():
    assert text_gaps([], 100.0, [(3.0, 50.0)]) == [(3.0, 50.0, True), (50.0, 100.0, False)]


def test_gaps_follow_the_lost_speech_report():
    # The same numbers as test_speech_without_words_is_reported: the markers must agree with the warning.
    speech = [(0.0, 27.0), (27.5, 55.0), (55.4, 83.0), (83.2, 110.0), (110.3, 130.0)]
    words = talk(0.0, 26.0) + talk(111.0, 130.0)
    assert text_gaps(words, 130.0, lost_speech(speech, words)) == [(25.9, 111.0, True)]

# ---- what Transcriber.transcribe reports ---------------------------------------------
class FakeSegment:
    def __init__(self, start, end, words, text=None):
        self.start, self.end, self.words = start, end, words
        self.text = text if text is not None else "".join(w.word for w in words)


class FakeWord:
    def __init__(self, start, end, word, probability=0.9):
        self.start, self.end, self.word, self.probability = start, end, word, probability


class FakeModel:
    """Stands in for faster_whisper.WhisperModel: one segment per call, with a word near each end
    of every clip (so the text covers them), or at the start of the audio without clips."""

    def __init__(self):
        self.calls = []

    def transcribe(self, audio, **options):
        self.calls.append((len(audio), options))
        stamps = options.get("clip_timestamps") or [0.0, 1.9]
        words = []
        for start, end in zip(stamps[::2], stamps[1::2]):
            words += [FakeWord(start + 0.3, start + 0.7, " Hello."), FakeWord(end - 0.7, end - 0.3, " Again.")]
        info = type("Info", (), {"language": options.get("language") or "en", "language_probability": 1.0})()
        return iter([FakeSegment(words[0].start, words[-1].end, words)]), info


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


def test_clips_cut_out_of_running_speech_go_without_the_word_bank(monkeypatch):
    # A clip that starts where the previous one ended begins mid-sentence. With a word bank,
    # Whisper dropped the first words of 8 of 162 such test clips; without one, of none.
    clips = [(1.0, 28.0), (28.0, 55.0), (56.5, 80.0), (80.0, 99.0)]
    transcriber = fake_transcriber(monkeypatch, clips)
    result = transcriber.transcribe(np.zeros(16000 * 100, np.float32), language="en", hotwords="Quuxian, Vexley")
    calls = [options for _, options in transcriber.model.calls]
    assert [(c["clip_timestamps"], c["hotwords"]) for c in calls] == [
        ([1.0, 28.0, 56.5, 80.0], "Quuxian, Vexley"), ([28.0, 55.0, 80.0, 99.0], None)]
    assert len(result.words) == 8 and result.speech == clips  # both decodes' words, all the speech


def test_without_a_word_bank_all_clips_go_in_one_decode(monkeypatch):
    clips = [(1.0, 28.0), (28.0, 55.0)]
    transcriber = fake_transcriber(monkeypatch, clips)
    transcriber.transcribe(np.zeros(16000 * 60, np.float32), language="en")
    assert [options["clip_timestamps"] for _, options in transcriber.model.calls] == [[1.0, 28.0, 28.0, 55.0]]


def test_the_second_decode_keeps_the_detected_language_and_progress_only_grows(monkeypatch):
    clips = [(1.0, 28.0), (28.0, 55.0)]
    transcriber = fake_transcriber(monkeypatch, clips)
    seen = []
    transcriber.transcribe(np.zeros(16000 * 60, np.float32), language=None, hotwords="Quuxian", progress=seen.append)
    assert [options["language"] for _, options in transcriber.model.calls] == [None, "en"]
    assert seen == sorted(seen) and seen[-1] <= 1.0


# ---- speech a word bank left without text ---------------------------------------------
def test_a_clip_without_text_is_uncovered_whole():
    assert asr.uncovered((10.0, 30.0), []) == [(10.0, 30.0)]
    credit_only = say((" Subtitles", 0.6), (" by", 0.9), (" the", 0.9), (" Amara.org", 1.0), (" community", 1.0))
    assert asr.uncovered((0.0, 20.0), credit_only) == [(0.0, 20.0)]  # dropped later, so it covers nothing


def test_text_that_starts_or_ends_well_inside_a_clip_leaves_those_parts_uncovered():
    words = [Word(14.0, 14.4, " The", 0.9), Word(14.4, 15.0, " test.", 0.9)]
    assert asr.uncovered((10.0, 30.0), words) == [(10.0, 14.0), (15.0, 30.0)]
    # Normal margins: the voice detector's padding and Whisper's timing, about 0.3-1.4 s.
    assert asr.uncovered((13.7, 16.2), words) == []


def test_gaps_are_filled_from_the_second_decode_without_repeats():
    kept = [Word(14.0, 14.4, " The", 0.9), Word(14.4, 15.0, " test.", 0.9)]
    other = [Word(10.5, 10.9, " First,", 0.8), Word(11.0, 11.4, " we", 0.8), Word(11.5, 13.0, " see", 0.8),
             Word(13.5, 13.95, " the", 0.7),  # the kept "The", timed a little earlier
             Word(14.4, 15.0, " test.", 0.9),  # inside the kept text
             Word(15.05, 15.5, " test.", 0.7),  # the kept "test.", timed a little later
             Word(16.0, 16.5, " Then", 0.8), Word(16.5, 17.0, " more.", 0.8)]
    filled = asr.fill_gaps([(10.0, 14.0), (15.0, 30.0)], kept, other)
    assert [w.text for w in filled] == [" First,", " we", " see", " Then", " more."]


def test_no_piece_of_an_invented_sign_off_fills_a_gap():
    # The second decode's "Thank you very much." straddled the kept text: "very much." alone would
    # have filled the gap after it, and drop_sign_offs could no longer recognise it.
    kept = [Word(244.0, 244.5, " Cosine", 0.9), Word(253.7, 254.6, " vectors.", 0.9)]
    other = [Word(247.4, 248.8, " Thank", 0.14), Word(248.8, 250.2, " you", 1.0), Word(250.2, 259.9, " very", 0.02),
             Word(259.9, 260.0, " much.", 1.0)]
    assert asr.fill_gaps([(237.6, 244.0), (254.6, 260.3)], kept, other) == []


class BankShy:
    """A model that, given hotwords, writes one word in the middle of each clip; without, a word
    every second all through it."""

    def __init__(self):
        self.calls = []

    def transcribe(self, audio, clip_timestamps, hotwords=None, **options):
        self.calls.append((list(clip_timestamps), hotwords))
        segments = []
        for start, end in zip(clip_timestamps[::2], clip_timestamps[1::2]):
            middle = (start + end) / 2
            times = ([(middle - 0.5, middle + 0.5)] if hotwords
                     else [(float(t), float(t) + 0.8) for t in np.arange(start + 0.3, end - 0.8)])
            words = [FakeWord(a, b, f" w{a:.2f}") for a, b in times]
            segments.append(FakeSegment(words[0].start, words[-1].end, words))
        info = types.SimpleNamespace(language=options.get("language") or "en", language_probability=1.0)
        return iter(segments), info


def test_speech_a_word_bank_left_out_is_decoded_again_without_it(monkeypatch):
    clips = [(1.0, 21.0), (25.0, 26.5)]
    monkeypatch.setattr(asr, "speech_clips", lambda audio: clips)
    transcriber = object.__new__(asr.Transcriber)
    transcriber.model = BankShy()
    seen = []
    result = transcriber.transcribe(np.zeros(16000 * 30, np.float32), language="en", hotwords="Quuxian",
                                    progress=seen.append)
    # With the bank, the first clip's text covers 10.5-11.5 s only; the short second clip is fine.
    assert transcriber.model.calls == [([1.0, 21.0, 25.0, 26.5], "Quuxian"), ([1.0, 21.0], None)]
    starts = [round(w.start, 2) for w in result.words]
    head = [round(1.3 + k, 2) for k in range(9)]  # 1.3-9.3; the word at 10.3 is where the bank's own is
    tail = [round(11.3 + k, 2) for k in range(9)]  # 11.3-19.3: their middles fall after the bank word's end
    assert starts == head + [10.5] + tail + [25.25]  # the bank's words stay, with the gaps filled around them
    assert seen == sorted(seen) and seen[-1] == 1.0


class SignsOff:
    """With hotwords, a sign-off in the middle of the clip; without, another one and then speech."""

    def transcribe(self, audio, clip_timestamps, hotwords=None, **options):
        start, end = clip_timestamps[0], clip_timestamps[1]
        spec = ([(" Thank", 0.1), (" you", 0.9), (" for", 0.3), (" watching.", 0.8)] if hotwords
                else [(" Thank", 0.1), (" you.", 0.9), (" Real", 0.9), (" words.", 0.9)])
        words = [FakeWord(start + 5 + 0.3 * i + (0.1 if not hotwords else 0), start + 5.25 + 0.3 * i, w, p)
                 for i, (w, p) in enumerate(spec)]
        info = types.SimpleNamespace(language=options.get("language") or "en", language_probability=1.0)
        return iter([FakeSegment(words[0].start, words[-1].end, words)]), info


def test_a_clip_decoded_again_keeps_no_sign_off_of_the_first_decode(monkeypatch):
    # The two decodes' sign-offs, merged by time, would read "Thank Thank you you. for watching."
    # and get past drop_sign_offs.
    monkeypatch.setattr(asr, "speech_clips", lambda audio: [(1.0, 21.0)])
    transcriber = object.__new__(asr.Transcriber)
    transcriber.model = SignsOff()
    result = transcriber.transcribe(np.zeros(16000 * 25, np.float32), language="en", hotwords="Quuxian")
    assert text(result.words) == " Real words."  # each decode's sign-off dropped whole


def test_a_stretch_of_exactly_30_seconds_is_a_gap():
    words = [Word(0.0, 10.0, " one", 0.9), Word(40.0, 41.0, " two.", 0.9)]
    assert text_gaps(words, 41.0, []) == [(10.0, 40.0, False)]
    assert text_gaps(words, 41.0, [], min_length=30.01) == []
