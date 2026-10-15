from localscribe.core.align import (assign_speakers, ends_sentence, group_utterances, join_words,
                                    sentence_spans, smooth_speakers)
from localscribe.core.asr import Word
from localscribe.core.diarization import Turn


def words(spec):
    """spec: [(start, end, text)]"""
    return [Word(s, e, t) for s, e, t in spec]


def test_assign_by_largest_overlap_and_nearest_turn_for_gaps():
    ws = words([(0.0, 0.5, " Hi."), (1.0, 1.4, " Hello"), (3.0, 3.2, " there.")])
    turns = [Turn(0.0, 0.6, "A"), Turn(0.9, 2.0, "B")]
    labels, coverage = assign_speakers(ws, turns)
    assert labels == ["A", "B", "B"]  # last word falls in a gap: nearest turn is B
    assert coverage[0] == 1.0 and coverage[2] == 0.0


def test_no_turns_means_single_speaker():
    labels, _ = assign_speakers(words([(0, 1, " a")]), [])
    assert labels == ["SPEAKER_00"]


def test_boundary_word_rejoins_its_sentence():
    # "too." is timestamped into B's turn but belongs to A's sentence.
    ws = words([(0.0, 0.4, " I"), (0.4, 0.8, " like"), (0.8, 1.2, " it"), (1.2, 1.6, " too."),
                (1.8, 2.2, " Great."), (2.2, 2.6, " Thanks.")])
    turns = [Turn(0.0, 1.25, "A"), Turn(1.25, 3.0, "B")]
    labels, coverage = assign_speakers(ws, turns)
    assert labels[3] == "B"
    fixed = smooth_speakers(ws, labels, coverage)
    assert fixed == ["A", "A", "A", "A", "B", "B"]


def test_one_word_reply_is_kept():
    ws = words([(0.0, 0.5, " Really?"), (0.6, 0.9, " Yes."), (1.0, 1.5, " Why?")])
    turns = [Turn(0.0, 0.55, "A"), Turn(0.55, 0.95, "B"), Turn(0.95, 1.6, "A")]
    labels, coverage = assign_speakers(ws, turns)
    assert smooth_speakers(ws, labels, coverage) == ["A", "B", "A"]


def test_sentence_spans_split_on_punctuation_and_pauses():
    ws = words([(0, 1, " One."), (1, 2, " two"), (5, 6, " three"), (6, 7, " four?")])
    assert sentence_spans(ws) == [(0, 1), (1, 2), (2, 4)]


def test_group_utterances_by_speaker_and_long_monologue():
    ws = words([(i, i + 0.9, " word.") for i in range(100)])
    labels = ["A"] * 70 + ["B"] * 30
    groups = group_utterances(ws, labels, max_duration=30)
    assert all(len({labels[k] for k in g}) == 1 for g in groups)
    assert len(groups) >= 4  # A's 70 s split into ~30 s paragraphs, then B


def test_join_and_sentence_end_helpers():
    assert join_words(words([(0, 1, " Hello,"), (1, 2, "  world.")])) == "Hello, world."
    assert ends_sentence(' he said "stop."') and not ends_sentence(" and")
