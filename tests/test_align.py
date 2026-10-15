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


def test_late_change_moves_back_to_the_sentence_start():
    # B's turn starts after "Give", which Whisper also stretched back to "here.": B holds
    # less than 70 % of the sentence, so it used to come out as "Give / me an example."
    ws = words([(0.0, 0.2, " We"), (0.2, 0.45, " start"), (0.45, 0.6, " here."), (0.6, 1.1, " Give"),
                (1.1, 1.3, " me"), (1.3, 1.45, " an"), (1.45, 2.0, " example.")])
    turns = [Turn(0.0, 1.05, "A"), Turn(1.05, 2.5, "B")]
    labels, coverage = assign_speakers(ws, turns)
    assert labels == ["A"] * 4 + ["B"] * 3
    assert smooth_speakers(ws, labels, coverage) == ["A"] * 3 + ["B"] * 4


def test_late_change_moves_back_to_a_pause():
    # No full stop after "here", only a pause; A's turn runs on over "give me".
    ws = words([(0.0, 0.2, " we"), (0.2, 0.5, " start"), (0.5, 0.8, " here"), (1.4, 1.7, " give"),
                (1.7, 1.9, " me"), (1.9, 2.05, " an"), (2.05, 2.6, " example.")])
    turns = [Turn(0.0, 1.95, "A"), Turn(1.95, 3.0, "B")]
    labels, coverage = assign_speakers(ws, turns)
    assert labels == ["A"] * 5 + ["B"] * 2
    assert smooth_speakers(ws, labels, coverage) == ["A"] * 3 + ["B"] * 4


def test_early_change_moves_forward_to_the_sentence_end():
    # B's turn starts too early, taking "lemonize it?": "So how do we / lemonize it?"
    ws = words([(0.0, 0.2, " So"), (0.2, 0.4, " how"), (0.4, 0.5, " do"), (0.5, 0.65, " we"),
                (0.65, 1.15, " lemonize"), (1.15, 1.35, " it?"),
                (1.35, 1.55, " With"), (1.55, 1.65, " a"), (1.65, 2.2, " function.")])
    turns = [Turn(0.0, 0.7, "A"), Turn(0.7, 2.5, "B")]
    labels, coverage = assign_speakers(ws, turns)
    assert labels == ["A"] * 4 + ["B"] * 5
    assert smooth_speakers(ws, labels, coverage) == ["A"] * 6 + ["B"] * 3


def test_early_change_moves_forward_to_a_pause():
    # No question mark after "it", only a pause.
    ws = words([(0.0, 0.2, " so"), (0.2, 0.4, " how"), (0.4, 0.5, " do"), (0.5, 0.65, " we"),
                (0.65, 1.15, " lemonize"), (1.15, 1.35, " it"),
                (1.95, 2.15, " with"), (2.15, 2.25, " a"), (2.25, 2.8, " function.")])
    turns = [Turn(0.0, 0.7, "A"), Turn(0.7, 3.0, "B")]
    labels, coverage = assign_speakers(ws, turns)
    assert labels == ["A"] * 4 + ["B"] * 5
    assert smooth_speakers(ws, labels, coverage) == ["A"] * 6 + ["B"] * 3


def test_words_stretched_over_a_lost_interjection_rejoin_their_sentence():
    # From the synthetic interview in fast mode: Whisper dropped B's "Right." and stretched
    # A's next words over it, so the transcript read "We also / had a few people".
    ws = words([(0.94, 1.26, " winter."), (1.46, 1.88, " We"), (1.88, 2.64, " also"),
                (2.64, 3.06, " had"), (3.06, 3.14, " a"), (3.14, 3.32, " few"),
                (3.32, 3.64, " people"), (3.64, 3.9, " drop"), (3.9, 4.2, " out.")])
    turns = [Turn(0.0, 1.57, "A"), Turn(1.73, 2.30, "B"), Turn(2.30, 5.0, "A")]
    labels, coverage = assign_speakers(ws, turns)
    assert labels == ["A", "B", "B"] + ["A"] * 6
    assert smooth_speakers(ws, labels, coverage) == ["A"] * 9


def test_short_sentence_split_goes_to_the_part_with_more_time():
    # B's turn starts inside "agree."; A holds more of "I agree.", so "agree." follows.
    ws = words([(0.0, 0.3, " I"), (0.3, 0.6, " agree."), (1.0, 1.3, " Good.")])
    turns = [Turn(0.0, 0.42, "A"), Turn(0.42, 1.5, "B")]
    labels, coverage = assign_speakers(ws, turns)
    assert labels == ["A", "B", "B"]
    assert smooth_speakers(ws, labels, coverage) == ["A", "A", "B"]


def test_reply_after_a_silence_is_kept_without_punctuation():
    # Whisper left out the "?", but "Yes." starts after a gap: a real reply.
    ws = words([(0.0, 0.3, " Is"), (0.3, 0.6, " that"), (0.6, 0.9, " right"), (1.0, 1.4, " Yes.")])
    turns = [Turn(0.0, 0.95, "A"), Turn(0.95, 1.6, "B")]
    labels, coverage = assign_speakers(ws, turns)
    assert smooth_speakers(ws, labels, coverage) == ["A", "A", "A", "B"]


def test_reply_after_a_comma_is_kept():
    ws = words([(0.0, 0.3, " you"), (0.3, 0.6, " know,"), (0.6, 1.1, " Right.")])
    turns = [Turn(0.0, 0.6, "A"), Turn(0.6, 1.5, "B")]
    labels, coverage = assign_speakers(ws, turns)
    assert smooth_speakers(ws, labels, coverage) == ["A", "A", "B"]


def test_short_part_that_holds_clearly_more_time_stays():
    # A's slow "Right" holds twice as long as B's quick "so I think.".
    ws = words([(0.0, 0.8, " Right"), (0.8, 0.97, " so"), (0.97, 1.05, " I"), (1.05, 1.2, " think.")])
    turns = [Turn(0.0, 0.8, "A"), Turn(0.8, 1.5, "B")]
    labels, coverage = assign_speakers(ws, turns)
    assert smooth_speakers(ws, labels, coverage) == ["A", "B", "B", "B"]


def test_three_speaker_runs_in_one_sentence_are_left_alone():
    ws = words([(0.0, 0.3, " so"), (0.3, 0.6, " yes"), (0.6, 0.9, " fine.")])
    turns = [Turn(0.0, 0.3, "A"), Turn(0.3, 0.6, "B"), Turn(0.6, 1.0, "A")]
    labels, coverage = assign_speakers(ws, turns)
    assert smooth_speakers(ws, labels, coverage) == ["A", "B", "A"]


def test_mid_sentence_change_with_strong_evidence_stays():
    # Both sides sit in their own speaker's turn for over a second: not boundary jitter.
    ws = words([(0.0, 0.6, " Well"), (0.6, 1.2, " actually"), (1.2, 1.5, " we"), (1.5, 1.8, " can"),
                (1.8, 2.4, " not.")])
    turns = [Turn(0.0, 1.2, "A"), Turn(1.2, 2.5, "B")]
    labels, coverage = assign_speakers(ws, turns)
    assert smooth_speakers(ws, labels, coverage) == ["A", "A", "B", "B", "B"]


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
