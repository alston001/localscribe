"""Word banks: storage, term lists, the Whisper prompt limit and the check before a run.

Every term here is made up. Never copy a real word bank into the repo.
"""

import json
import logging
import pathlib
import types

import pytest

from localscribe import paths
from localscribe.vocabulary import (PROMPT_LIMIT, TokenCounter, Vocabulary, fit_terms, join_terms,
                                    load_vocabularies, parse_terms, save_vocabularies, token_counter)
from test_pipeline import WORDS, FakeTranscriber, fake_models, make_engine  # noqa: F401 (fake_models: fixture)

NLP = Vocabulary("Zorblax seminar", ["Quuxian parsing", "Vexley drift", "glimmerform"])
LAB = Vocabulary("Lab meeting", ["Dr. Fennimore", "Plonk assay"])


class CharTokenizer:
    """One token per character; remembers what it was asked to encode."""

    def __init__(self):
        self.seen = []

    def encode(self, text, add_special_tokens=True):
        self.seen.append((text, add_special_tokens))
        return types.SimpleNamespace(ids=list(range(len(text))))


class FourPerTerm:
    """An exact tokenizer stand-in: every ", "-separated term takes 4 tokens."""

    def encode(self, text, add_special_tokens=True):
        return types.SimpleNamespace(ids=[0] * (4 * len(text.split(", "))))


def made_up_terms(n: int) -> list[str]:
    return [f"Zorblax{i}" for i in range(n)]


def write_tokenizer(folder):
    """A tiny but real tokenizers file: one token per word or punctuation mark."""
    from tokenizers import Tokenizer
    from tokenizers.models import WordLevel
    from tokenizers.pre_tokenizers import Whitespace

    folder.mkdir(parents=True)
    tokenizer = Tokenizer(WordLevel({"[UNK]": 0, "Zorblax": 1}, unk_token="[UNK]"))
    tokenizer.pre_tokenizer = Whitespace()
    tokenizer.save(str(folder / "tokenizer.json"))
    (folder / "model.bin").write_bytes(b"")


# ---- storage ------------------------------------------------------------------------
def test_word_banks_survive_a_save_and_load(tmp_path):
    path = tmp_path / "vocabularies.json"
    save_vocabularies([NLP, LAB], path)
    assert load_vocabularies(path) == [NLP, LAB]
    assert json.loads(path.read_text(encoding="utf-8"))["format_version"] == 1


def test_word_banks_live_in_the_user_data_folder(monkeypatch, tmp_path):
    monkeypatch.setattr(paths, "user_data_dir", lambda: tmp_path)
    save_vocabularies([NLP])
    assert (tmp_path / "vocabularies.json").is_file()
    assert load_vocabularies() == [NLP]


def test_missing_file_means_no_word_banks_yet(tmp_path):
    assert load_vocabularies(tmp_path / "vocabularies.json") == []
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("content", ["[1, 2]", "{not json", '"text"', '{"vocabularies": 5}'])
def test_corrupt_file_is_backed_up_and_logged(tmp_path, caplog, content):
    path = tmp_path / "vocabularies.json"
    path.write_text(content, encoding="utf-8")
    with caplog.at_level(logging.WARNING, logger="localscribe"):
        assert load_vocabularies(path) == []
    assert (tmp_path / "vocabularies.json.bad").read_text(encoding="utf-8") == content
    assert "vocabularies.json" in caplog.text


@pytest.mark.parametrize("encoding", ["utf-16", "cp950"])
def test_a_file_in_another_encoding_is_backed_up_instead_of_stopping_the_app(tmp_path, caplog, encoding):
    # Notepad's "Unicode" and PowerShell's > write UTF-16; older Traditional Chinese tools write cp950.
    path = tmp_path / "vocabularies.json"
    raw = json.dumps({"format_version": 1, "vocabularies": [{"name": "佐布拉克", "terms": ["庫西安"]}]},
                     ensure_ascii=False).encode(encoding)
    path.write_bytes(raw)
    with caplog.at_level(logging.WARNING, logger="localscribe"):
        assert load_vocabularies(path) == []
    assert (tmp_path / "vocabularies.json.bad").read_bytes() == raw
    assert "vocabularies.json" in caplog.text


def test_a_byte_order_mark_is_fine(tmp_path):
    path = tmp_path / "vocabularies.json"
    data = {"format_version": 1, "vocabularies": [{"name": NLP.name, "terms": NLP.terms}]}
    path.write_bytes(b"\xef\xbb\xbf" + json.dumps(data).encode())  # Notepad's "UTF-8 with BOM"
    assert load_vocabularies(path) == [NLP]
    assert not (tmp_path / "vocabularies.json.bad").exists()


def test_broken_entries_are_dropped_and_the_original_is_kept(tmp_path, caplog):
    path = tmp_path / "vocabularies.json"
    content = json.dumps({"format_version": 1, "vocabularies": [
        {"name": "Zorblax seminar", "terms": ["Quuxian parsing", 7, None, "Vexley drift", "glimmerform"]},
        {"name": 5, "terms": ["lost"]},
        "not a bank",
        {"name": "  ", "terms": ["no name"]},
        {"name": "zorblax SEMINAR", "terms": ["same name twice"]},
        {"name": "Lab meeting", "terms": "Dr. Fennimore, Plonk assay"},  # hand-edited as one string
    ]})
    path.write_text(content, encoding="utf-8")
    with caplog.at_level(logging.WARNING, logger="localscribe"):
        assert load_vocabularies(path) == [NLP, LAB]
    # Saving drops the broken entries for good, so keep a copy of what was there.
    assert (tmp_path / "vocabularies.json.bad").read_text(encoding="utf-8") == content
    assert "vocabularies.json" in caplog.text


@pytest.mark.parametrize("bank", [
    {"name": "Zorblax seminar", "terms": {"Quuxian parsing": 1}},  # the wrong shape
    {"name": "Zorblax seminar", "words": ["Quuxian parsing"]},     # misspelled by hand
    {"name": "Zorblax seminar", "terms": [], "language": "en"},    # a field from a newer version
])
def test_parts_this_version_cannot_keep_are_backed_up(tmp_path, bank):
    path = tmp_path / "vocabularies.json"
    content = json.dumps({"format_version": 1, "vocabularies": [bank]})
    path.write_text(content, encoding="utf-8")
    assert load_vocabularies(path) == [Vocabulary("Zorblax seminar", [])]
    assert (tmp_path / "vocabularies.json.bad").read_text(encoding="utf-8") == content


@pytest.mark.parametrize("data", [
    {"format_version": 2, "vocabularies": [{"name": "Zorblax seminar", "terms": NLP.terms}]},
    {"format_version": 1, "vocabularies": [{"name": "Zorblax seminar", "terms": NLP.terms}], "shared": True},
])
def test_a_file_from_a_newer_version_is_copied_before_this_one_overwrites_it(tmp_path, data):
    # The released app and a source checkout share %LOCALAPPDATA%\LocalScribe.
    path = tmp_path / "vocabularies.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    assert load_vocabularies(path) == [NLP]  # what this version understands
    assert (tmp_path / "vocabularies.json.bad").read_text(encoding="utf-8") == json.dumps(data)


def test_tidying_terms_needs_no_backup(tmp_path):
    path = tmp_path / "vocabularies.json"
    path.write_text(json.dumps({"format_version": 1, "vocabularies": [
        {"name": " Zorblax seminar ", "terms": ["Quuxian  parsing", "quuxian parsing", "", "Vexley drift",
                                                "glimmerform"]}]}), encoding="utf-8")
    assert load_vocabularies(path) == [NLP]
    assert sorted(p.name for p in tmp_path.iterdir()) == ["vocabularies.json"]


def test_a_file_that_cannot_be_read_is_an_error_not_an_empty_list(tmp_path, monkeypatch):
    # Taken as "no word banks yet", the next save would overwrite it.
    path = tmp_path / "vocabularies.json"
    save_vocabularies([NLP], path)

    def locked(self):
        raise PermissionError(13, "The process cannot access the file", str(self))

    monkeypatch.setattr(pathlib.Path, "read_bytes", locked)
    with pytest.raises(OSError):
        load_vocabularies(path)


def test_a_failed_save_keeps_the_previous_file(tmp_path, monkeypatch):
    from localscribe import vocabulary

    path = tmp_path / "vocabularies.json"
    save_vocabularies([NLP], path)

    def disk_full(src, dst):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(vocabulary.os, "replace", disk_full)
    with pytest.raises(OSError):
        save_vocabularies([NLP, LAB], path)
    assert load_vocabularies(path) == [NLP]
    assert sorted(p.name for p in tmp_path.iterdir()) == ["vocabularies.json"]


def test_the_chosen_word_bank_is_remembered_in_settings(tmp_path):
    from localscribe.config import Settings

    path = tmp_path / "settings.json"
    Settings(vocabulary="Zorblax seminar").save(path)
    assert Settings.load(path).vocabulary == "Zorblax seminar"
    assert Settings().vocabulary == ""  # none until the user picks one


def test_replacing_a_word_bank_keeps_its_place():
    from localscribe.vocabulary import replace_vocabulary

    glimmer = Vocabulary("Glimmer studies", ["glimmerform"])
    renamed = Vocabulary("Lab meeting", ["Plonk assay"])  # also the name of a bank made elsewhere
    assert replace_vocabulary([NLP, glimmer, LAB], "Glimmer studies", renamed) == [NLP, renamed]
    assert replace_vocabulary([NLP], "", LAB) == [NLP, LAB]  # a new one goes last
    assert replace_vocabulary([NLP, LAB], "zorblax SEMINAR", None) == [LAB]  # None deletes
    assert replace_vocabulary([LAB], "Gone", NLP) == [LAB, NLP]  # deleted elsewhere while being edited


# ---- term lists ---------------------------------------------------------------------
def test_terms_go_one_per_line_and_pasted_commas_split_them():
    text = "Quuxian parsing\nVexley drift, glimmerform\n\n   Plonk assay  \n,\n"
    assert parse_terms(text) == ["Quuxian parsing", "Vexley drift", "glimmerform", "Plonk assay"]


def test_duplicates_ignore_case_and_keep_the_first_spelling():
    assert parse_terms("QuuxNet\nquuxnet\nQUUXNET, Vexley\nvexley") == ["QuuxNet", "Vexley"]


def test_full_width_commas_and_tabs_split_terms_too():
    assert parse_terms("佐布拉克，庫西安、Vexley\tglimmerform") == ["佐布拉克", "庫西安", "Vexley", "glimmerform"]


def test_runs_of_spaces_inside_a_term_are_tidied():
    assert parse_terms("Quuxian    parsing\nquuxian parsing") == ["Quuxian parsing"]


# ---- token counting -----------------------------------------------------------------
def test_counts_the_exact_text_faster_whisper_encodes():
    tokenizer = CharTokenizer()
    counter = TokenCounter(tokenizer)
    assert counter.exact
    # faster-whisper's get_prompt encodes " " + hotwords.strip(), without special tokens.
    assert counter.count(["Quuxian parsing", "Vexley drift"]) == len(" Quuxian parsing, Vexley drift")
    assert tokenizer.seen == [(" Quuxian parsing, Vexley drift", False)]


def test_no_terms_take_no_tokens():
    assert TokenCounter(CharTokenizer()).count([]) == 0
    assert TokenCounter().count([]) == 0


def test_without_a_tokenizer_four_tokens_per_term_are_estimated():
    counter = TokenCounter()
    assert not counter.exact
    assert counter.count(made_up_terms(3)) == 12


def test_chinese_terms_are_estimated_by_character():
    # large-v3 and small: about 1.5 tokens per Chinese character, plus one for the comma.
    counter = TokenCounter()
    assert counter.count(["佐布拉克"]) == 7
    assert counter.count(["庫西"]) == 4  # never below a Latin term's 4
    assert counter.count(["佐布拉克", "Zorblax"]) == 11


def test_the_chosen_models_own_tokenizer_is_used(tmp_path):
    from localscribe.core.models import ModelStore

    write_tokenizer(tmp_path / "whisper" / "small")
    counter = token_counter(ModelStore(tmp_path), "small")
    assert counter.exact and counter.count(["Zorblax one", "Quuxian"]) == 4  # Zorblax, one, ",", Quuxian


def test_other_models_tokenizers_are_not_borrowed(tmp_path):
    # Models count differently: "small"'s tokenizer.json splits " tokenization" into more pieces
    # than large-v3's, so only the model that will run gives the real number.
    from localscribe.core.models import ModelStore

    write_tokenizer(tmp_path / "whisper" / "small")
    assert not token_counter(ModelStore(tmp_path), "large-v3").exact


def test_an_unreadable_tokenizer_falls_back_to_the_estimate(tmp_path, caplog):
    from localscribe.core.models import ModelStore

    folder = tmp_path / "whisper" / "small"
    folder.mkdir(parents=True)
    (folder / "model.bin").write_bytes(b"")
    (folder / "tokenizer.json").write_text("{not json", encoding="utf-8")
    with caplog.at_level(logging.WARNING, logger="localscribe"):
        assert not token_counter(ModelStore(tmp_path), "small").exact
    assert "tokenizer.json" in caplog.text


# ---- the prompt limit ---------------------------------------------------------------
@pytest.mark.parametrize("encoded, sent", [(222, 222), (223, 223), (224, 223), (400, 223)])
def test_faster_whisper_keeps_223_tokens_of_hotwords(encoded, sent):
    # faster-whisper's own get_prompt with a stand-in tokenizer, so no model is needed.
    from faster_whisper.transcribe import WhisperModel

    tokenizer = types.SimpleNamespace(encode=lambda text: list(range(encoded)), sot_prev=-1, sot_sequence=[-2])
    prompt = WhisperModel.get_prompt(types.SimpleNamespace(max_length=448), tokenizer, [], hotwords="x")
    assert prompt[1:-1] == list(range(sent)) and sent == min(encoded, PROMPT_LIMIT)


def test_the_terms_reach_whisper_unchanged(fake_models, monkeypatch):
    # The count assumes the pipeline passes JobOptions.hotwords on as it is.
    from localscribe.core.asr import AsrResult
    from localscribe.core.diarization import SpeakerCount
    from localscribe.core.pipeline import JobOptions

    seen = []

    def record(self, audio, language=None, hotwords=None, **kw):
        seen.append(hotwords)
        return AsrResult(language or "en", 1.0, list(WORDS))

    monkeypatch.setattr(FakeTranscriber, "transcribe", record)
    make_engine(fake_models).transcribe_file(
        fake_models / "week1.wav", JobOptions(hotwords="Quuxian parsing, Vexley drift", speakers=SpeakerCount(exact=1)))
    assert seen == ["Quuxian parsing, Vexley drift"]


def test_terms_past_the_limit_are_reported_in_order():
    terms = made_up_terms(60)
    kept, dropped = fit_terms(terms, TokenCounter(FourPerTerm()))  # 55 fit in 223
    assert kept == terms[:55] and dropped == terms[55:]


def test_nothing_is_dropped_under_the_limit():
    terms = made_up_terms(55)
    assert fit_terms(terms, TokenCounter(FourPerTerm())) == (terms, [])


def test_a_term_cut_in_half_counts_as_dropped():
    # " abcd, efgh" is 11 characters: with room for 10, "efgh" would reach Whisper as "efg".
    kept, dropped = fit_terms(["abcd", "efgh", "ij"], TokenCounter(CharTokenizer()), limit=10)
    assert kept == ["abcd"] and dropped == ["efgh", "ij"]


def test_one_huge_term_is_dropped_whole():
    kept, dropped = fit_terms(["x" * 300], TokenCounter(CharTokenizer()))
    assert kept == [] and dropped == ["x" * 300]


def installed_tokenizers():
    folder = paths.default_models_dir() / "whisper"
    return sorted(folder.glob("*/tokenizer.json")) if folder.is_dir() else []


@pytest.mark.skipif(not installed_tokenizers(), reason="no Whisper model downloaded")
@pytest.mark.parametrize("file", installed_tokenizers(), ids=lambda f: f.parent.name)
def test_counts_match_what_faster_whisper_sends(file):
    import tokenizers
    from faster_whisper.tokenizer import Tokenizer
    from faster_whisper.transcribe import WhisperModel

    hf = tokenizers.Tokenizer.from_file(str(file))
    whisper = Tokenizer(hf, multilingual=True, task="transcribe", language="en")

    def sent(terms):  # the hotword tokens get_prompt puts between <|startofprev|> and <|startoftranscript|>
        prompt = WhisperModel.get_prompt(types.SimpleNamespace(max_length=448), whisper, [],
                                         hotwords=join_terms(terms))
        return prompt[1:prompt.index(whisper.sot)]

    terms = [f"Zorblax{i} tokenization" for i in range(70)] + ["佐布拉克", "Dr. Fennimore"] * 5  # far over
    counter = TokenCounter(hf)
    kept, dropped = fit_terms(terms, counter)
    assert dropped and counter.count(kept) <= PROMPT_LIMIT < counter.count(kept + dropped[:1])
    assert len(sent(kept)) == counter.count(kept)          # under the limit: nothing cut
    assert len(sent(terms)) == PROMPT_LIMIT                # over it: cut to 223 tokens
    assert sent(terms)[:len(sent(kept))] == sent(kept)     # the kept terms are what survived whole


# ---- the terms Whisper gets ---------------------------------------------------------
def test_bank_terms_come_first_then_the_names_and_terms_field():
    from localscribe.vocabulary import prompt_terms

    terms = prompt_terms(NLP, "vexley DRIFT, Dr. Fennimore")
    assert join_terms(terms) == "Quuxian parsing, Vexley drift, glimmerform, Dr. Fennimore"


def test_without_a_word_bank_the_field_is_used_alone():
    from localscribe.vocabulary import prompt_terms

    assert join_terms(prompt_terms(None, " Dr. Fennimore ,Plonk assay")) == "Dr. Fennimore, Plonk assay"
    assert prompt_terms(None, "") == []


def test_word_banks_are_found_by_name_in_any_letter_case():
    from localscribe.vocabulary import find_vocabulary

    assert find_vocabulary([NLP, LAB], "lab MEETING") is LAB
    assert find_vocabulary([NLP, LAB], "") is None
    assert find_vocabulary([NLP], "Gone") is None


def test_job_options_carry_the_combined_terms():
    from localscribe.config import Settings

    s = Settings(hotwords="Dr. Fennimore")
    assert s.job_options().hotwords == "Dr. Fennimore"
    assert s.job_options(hotwords="glimmerform, Dr. Fennimore").hotwords == "glimmerform, Dr. Fennimore"


# ---- the check before a run ---------------------------------------------------------
def fake_window(vocabularies, settings, answer=True, counter=None):
    """What MainWindow._terms_for_run uses; records what it asked about and whether the count was exact."""
    from localscribe.ui.main_window import MainWindow

    window = types.SimpleNamespace(vocabularies=vocabularies, settings=settings, asked=[],
                                   _token_counter=lambda: counter or TokenCounter(FourPerTerm()))
    window._confirm_dropped_terms = lambda dropped, exact: window.asked.append((dropped, exact)) or answer
    window._terms_for_run = lambda ask: MainWindow._terms_for_run(window, ask)
    return window


def over_the_limit(answer, counter=None):
    """A 50-term bank plus 10 typed terms: with 4 tokens each, 55 fit and 5 don't."""
    from localscribe.config import Settings

    bank = Vocabulary("Zorblax seminar", made_up_terms(50))
    typed = ["Dr. Fennimore"] + [f"Plonk{i}" for i in range(9)]
    settings = Settings(vocabulary="Zorblax seminar", hotwords=", ".join(typed))
    return fake_window([bank], settings, answer, counter), bank, typed


def test_start_lists_the_terms_that_would_be_dropped():
    from localscribe.ui.main_window import MainWindow

    window, bank, typed = over_the_limit(answer=False)
    assert MainWindow._terms_for_run(window, ask=True) is None  # back to shorten the list
    assert window.asked == [(typed[5:], True)]


def test_start_anyway_sends_only_the_terms_that_fit():
    from localscribe.ui.main_window import MainWindow

    window, bank, typed = over_the_limit(answer=True)
    assert MainWindow._terms_for_run(window, ask=True) == (join_terms(bank.terms + typed[:5]), "Zorblax seminar")


def test_an_estimate_asks_but_lets_whisper_keep_what_really_fits():
    # An estimate can be off either way (Chinese terms cost more, acronyms less): remove nothing on a guess.
    from localscribe.ui.main_window import MainWindow

    window, bank, typed = over_the_limit(answer=True, counter=TokenCounter())
    assert MainWindow._terms_for_run(window, ask=True) == (join_terms(bank.terms + typed), "Zorblax seminar")
    assert window.asked == [(typed[5:], False)]


def test_no_question_when_everything_fits():
    from localscribe.config import Settings
    from localscribe.ui.main_window import MainWindow

    window = fake_window([NLP], Settings(vocabulary="zorblax seminar", hotwords="Dr. Fennimore"))
    assert MainWindow._terms_for_run(window, ask=True) == (
        "Quuxian parsing, Vexley drift, glimmerform, Dr. Fennimore", "Zorblax seminar")
    assert window.asked == []


def test_a_deleted_word_bank_is_not_used():
    from localscribe.config import Settings
    from localscribe.ui.main_window import MainWindow

    window = fake_window([LAB], Settings(vocabulary="Gone", hotwords=""))
    assert MainWindow._terms_for_run(window, ask=True) == ("", "")


def test_files_added_during_a_run_are_not_asked_about_again():
    from localscribe.ui.main_window import MainWindow

    window, bank, typed = over_the_limit(answer=False)
    hotwords, name = MainWindow._terms_for_run(window, ask=False)
    assert window.asked == [] and hotwords.endswith("Plonk3") and name == "Zorblax seminar"


def test_the_count_waits_for_the_gpu_check_when_the_model_is_automatic():
    from localscribe.config import Settings
    from localscribe.ui.main_window import MainWindow

    def not_yet():
        raise AssertionError("would detect the GPU on the window's thread")

    window = types.SimpleNamespace(settings=Settings(whisper_model="auto"), device_info=None,
                                   engine=types.SimpleNamespace(whisper_name=not_yet))
    assert not MainWindow._token_counter(window).exact


def test_the_count_uses_the_model_that_will_run(tmp_path):
    from localscribe.config import Settings
    from localscribe.core.models import ModelStore
    from localscribe.ui.main_window import MainWindow

    write_tokenizer(tmp_path / "whisper" / "small")
    engine = types.SimpleNamespace(store=ModelStore(tmp_path), whisper_name=lambda: "small")
    window = types.SimpleNamespace(settings=Settings(whisper_model="auto"), device_info=object(), engine=engine)
    assert MainWindow._token_counter(window).exact


class FakeWorker:
    """ProcessThread stand-in: keeps the queued tasks instead of running them."""

    def __init__(self, engine, parent=None):
        self.tasks, self.started = [], False
        for name in ("job_started", "job_progress", "job_finished", "job_failed", "job_stopped", "finished"):
            setattr(self, name, types.SimpleNamespace(connect=lambda slot: None))

    def add(self, task):
        self.tasks.append(task)

    def start(self):
        self.started = True


def start_window(monkeypatch, tmp_path, answer):
    from pathlib import Path

    from localscribe.ui import main_window
    from localscribe.ui.jobs import Job

    monkeypatch.setattr(main_window, "ProcessThread", FakeWorker)
    window, bank, typed = over_the_limit(answer)
    jobs = [Job(1, Path(tmp_path / "week1.wav")), Job(2, Path(tmp_path / "week2.wav"))]
    window.calls = []
    window.worker, window.run_template, window.run_results = None, None, {}
    window.model = types.SimpleNamespace(jobs=jobs, refresh=lambda job_id: None)
    window.engine = types.SimpleNamespace(update_settings=lambda settings: window.calls.append("settings"))
    window._token_counter = lambda: window.calls.append("count") or TokenCounter(FourPerTerm())
    window._enqueue = lambda job: main_window.MainWindow._enqueue(window, job)
    window._set_running = lambda running: None
    for name in ("_on_job_started", "_on_job_progress", "_on_job_finished", "_on_job_failed",
                 "_on_job_stopped", "_on_worker_done"):
        setattr(window, name, lambda *args: None)
    main_window.MainWindow.start(window)
    return window, bank, typed


def test_going_back_to_shorten_the_list_starts_nothing(monkeypatch, tmp_path):
    window, _, _ = start_window(monkeypatch, tmp_path, answer=False)
    assert window.worker is None and window.run_template is None
    assert [j.status for j in window.model.jobs] == ["waiting", "waiting"]


def test_every_queued_file_gets_the_word_bank(monkeypatch, tmp_path):
    window, bank, typed = start_window(monkeypatch, tmp_path, answer=True)
    assert window.calls == ["settings", "count"]  # the model that will run is known before counting
    assert window.worker.started and len(window.worker.tasks) == 2
    for task in window.worker.tasks:
        assert task.options.hotwords == join_terms(bank.terms + typed[:5])
        assert task.vocabulary == "Zorblax seminar"


# ---- the transcript says which word bank was used ------------------------------------
def run_one(monkeypatch, tmp_path, vocabulary):
    from localscribe.export.common import ExportOptions
    from localscribe.ui import threads
    from test_export import make_transcript

    written = []
    transcript = make_transcript()
    engine = types.SimpleNamespace(transcribe_file=lambda path, options, **kw: transcript)
    monkeypatch.setattr(threads, "write_outputs", lambda t, folder, formats, options: written.append(t) or [])
    worker = threads.ProcessThread(engine)
    worker._run(threads.Task(1, tmp_path / "week1.wav", None, ["txt"], ExportOptions(), None, vocabulary))
    assert written == [transcript]
    return transcript


def test_the_transcript_records_the_word_bank(monkeypatch, tmp_path):
    assert run_one(monkeypatch, tmp_path, "Zorblax seminar").settings["vocabulary"] == "Zorblax seminar"


def test_no_word_bank_leaves_no_entry(monkeypatch, tmp_path):
    assert "vocabulary" not in run_one(monkeypatch, tmp_path, "").settings


# ---- strings ------------------------------------------------------------------------
def word_bank_keys():
    from localscribe import i18n

    return {k for k in i18n.STRINGS if k.startswith("vocab")}


def test_every_word_bank_string_has_both_languages():
    import string

    from localscribe import i18n

    def fields(text):
        return {name for _, name, _, _ in string.Formatter().parse(text) if name}

    assert len(word_bank_keys()) > 20
    for key in word_bank_keys():
        zh, en = i18n.STRINGS[key]
        assert zh and en and fields(zh) == fields(en), key


def test_word_bank_strings_are_all_used_and_all_exist():
    import re

    root = pathlib.Path(__file__).resolve().parent.parent / "localscribe"
    source = "\n".join(p.read_text(encoding="utf-8") for p in root.rglob("*.py") if p.name != "i18n.py")
    unused = {k for k in word_bank_keys() if f'"{k}"' not in source and f"'{k}'" not in source}
    assert unused == set()
    assert set(re.findall(r"""tr\(["'](vocab\w*)["']""", source)) <= word_bank_keys()


# ---- managing word banks in the main window ------------------------------------------
def manager(monkeypatch, tmp_path, on_disk, chosen="", confirm=True):
    """What MainWindow's word bank handlers use, with the file in tmp_path; records what the picker shows."""
    from localscribe.config import Settings
    from localscribe.ui.main_window import MainWindow

    monkeypatch.setattr(paths, "user_data_dir", lambda: tmp_path)
    save_vocabularies(on_disk)
    window = types.SimpleNamespace(vocabularies=load_vocabularies(), settings=Settings(vocabulary=chosen),
                                   settings_saved=0, shown=None)
    window._change_vocabularies = lambda old, new: MainWindow._change_vocabularies(window, old, new)
    window._save_settings = lambda: setattr(window, "settings_saved", window.settings_saved + 1)
    window.cmb_vocabulary = types.SimpleNamespace(
        set_vocabularies=lambda vocabularies, current: setattr(window, "shown", ([v.name for v in vocabularies], current)))
    window._confirm_delete = lambda name: confirm
    return window


def test_a_new_word_bank_is_saved_and_chosen(monkeypatch, tmp_path):
    from localscribe.ui.main_window import MainWindow

    window = manager(monkeypatch, tmp_path, [LAB])
    MainWindow._save_vocabulary(window, None, NLP)
    assert load_vocabularies() == window.vocabularies == [LAB, NLP]
    assert window.settings.vocabulary == "Zorblax seminar" and window.settings_saved
    assert window.shown == (["Lab meeting", "Zorblax seminar"], "Zorblax seminar")


def test_renaming_the_chosen_word_bank_keeps_it_chosen(monkeypatch, tmp_path):
    from localscribe.ui.main_window import MainWindow

    window = manager(monkeypatch, tmp_path, [NLP, LAB], chosen="zorblax seminar")
    renamed = Vocabulary("Zorblax seminar II", NLP.terms + ["Plonk assay"])
    MainWindow._save_vocabulary(window, window.vocabularies[0], renamed)
    assert load_vocabularies() == [renamed, LAB] and window.settings.vocabulary == "Zorblax seminar II"


def test_editing_another_word_bank_keeps_the_choice(monkeypatch, tmp_path):
    from localscribe.ui.main_window import MainWindow

    window = manager(monkeypatch, tmp_path, [NLP, LAB], chosen="Zorblax seminar")
    MainWindow._save_vocabulary(window, window.vocabularies[1], Vocabulary("Lab meetings", LAB.terms))
    assert window.settings.vocabulary == "Zorblax seminar"


def test_deleting_the_chosen_word_bank_switches_to_none(monkeypatch, tmp_path):
    from localscribe.ui.main_window import MainWindow

    window = manager(monkeypatch, tmp_path, [NLP, LAB], chosen="Zorblax seminar")
    MainWindow._delete_vocabulary(window, "zorblax SEMINAR")
    assert load_vocabularies() == window.vocabularies == [LAB] and window.settings.vocabulary == ""
    assert window.shown == (["Lab meeting"], "")


def test_deleting_asks_first(monkeypatch, tmp_path):
    from localscribe.ui.main_window import MainWindow

    window = manager(monkeypatch, tmp_path, [NLP, LAB], chosen="Zorblax seminar", confirm=False)
    MainWindow._delete_vocabulary(window, "Zorblax seminar")
    assert load_vocabularies() == [NLP, LAB] and window.settings.vocabulary == "Zorblax seminar"


def test_word_banks_saved_by_another_window_survive_changes_here(monkeypatch, tmp_path):
    # "Open with…" starts a second LocalScribe window; each must not erase the other's banks.
    from localscribe.ui.main_window import MainWindow

    window = manager(monkeypatch, tmp_path, [NLP])
    glimmer = Vocabulary("Glimmer studies", ["glimmerform"])
    save_vocabularies([NLP, LAB])  # the other window adds a bank
    MainWindow._save_vocabulary(window, None, glimmer)
    assert load_vocabularies() == window.vocabularies == [NLP, LAB, glimmer]
    save_vocabularies([NLP, LAB, glimmer, Vocabulary("Plonk", ["Plonk assay"])])  # and another
    MainWindow._delete_vocabulary(window, "Zorblax seminar")
    assert [v.name for v in load_vocabularies()] == ["Lab meeting", "Glimmer studies", "Plonk"]


def test_a_failed_save_is_reported_and_changes_nothing(monkeypatch, tmp_path):
    from PySide6.QtWidgets import QMessageBox

    from localscribe.ui import main_window

    def disk_full(vocabularies):
        raise OSError(28, "No space left on device")

    window = manager(monkeypatch, tmp_path, [LAB])
    told = []
    monkeypatch.setattr(main_window, "save_vocabularies", disk_full)
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: told.append(a[2]))
    main_window.MainWindow._save_vocabulary(window, None, NLP)
    assert len(told) == 1 and "No space left" in told[0]
    assert load_vocabularies() == window.vocabularies == [LAB]
    assert window.settings.vocabulary == "" and window.shown is None


def test_a_file_that_cannot_be_read_is_not_overwritten(monkeypatch, tmp_path):
    from PySide6.QtWidgets import QMessageBox

    from localscribe.ui import main_window

    def locked():
        raise PermissionError(13, "The process cannot access the file")

    window = manager(monkeypatch, tmp_path, [LAB])
    told, saved = [], []
    monkeypatch.setattr(main_window, "load_vocabularies", locked)
    monkeypatch.setattr(main_window, "save_vocabularies", saved.append)
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: told.append(a[2]))
    main_window.MainWindow._save_vocabulary(window, None, NLP)
    assert saved == [] and len(told) == 1 and window.vocabularies == [LAB]


# ---- command line -------------------------------------------------------------------
class FakeEngine:
    """Engine stand-in for cli.main: records the options and returns a small transcript."""

    runs: list = []

    def __init__(self, settings, log=None):
        from localscribe.core.models import ModelStore

        self.settings = settings
        self.store = ModelStore(settings.models_dir, settings.extra_model_dirs)

    def whisper_name(self):
        return "large-v3"

    def transcribe_file(self, path, opts, progress=None):
        from test_export import make_transcript

        FakeEngine.runs.append(opts)
        return make_transcript()


def run_cli(monkeypatch, tmp_path, *args):
    from localscribe import cli

    monkeypatch.setattr(paths, "user_data_dir", lambda: tmp_path)
    monkeypatch.setattr(cli, "Engine", FakeEngine)
    written = []
    monkeypatch.setattr(cli, "write_outputs", lambda t, folder, formats, options: written.append(t) or [])
    FakeEngine.runs = []
    code = cli.main([str(tmp_path / "week1.wav"), "--models-dir", str(tmp_path / "models"), *args])
    return code, written


def test_cli_word_bank_terms_come_before_hotwords(monkeypatch, tmp_path):
    save_vocabularies([NLP], tmp_path / "vocabularies.json")
    code, written = run_cli(monkeypatch, tmp_path, "--vocabulary", "zorblax SEMINAR",
                            "--hotwords", "Dr. Fennimore, glimmerform")
    assert code == 0
    assert FakeEngine.runs[0].hotwords == "Quuxian parsing, Vexley drift, glimmerform, Dr. Fennimore"
    assert written[0].settings["vocabulary"] == "Zorblax seminar"


def test_cli_hotwords_alone_still_work(monkeypatch, tmp_path):
    code, written = run_cli(monkeypatch, tmp_path, "--hotwords", "Dr. Fennimore,glimmerform")
    assert code == 0 and FakeEngine.runs[0].hotwords == "Dr. Fennimore, glimmerform"
    assert "vocabulary" not in written[0].settings


def test_cli_unknown_word_bank_is_a_usage_error(monkeypatch, tmp_path, capsys):
    save_vocabularies([NLP, LAB], tmp_path / "vocabularies.json")
    with pytest.raises(SystemExit) as caught:
        run_cli(monkeypatch, tmp_path, "--vocabulary", "Gone")
    err = capsys.readouterr().err
    assert caught.value.code == 2 and "Gone" in err and "Zorblax seminar" in err and "Lab meeting" in err
    assert FakeEngine.runs == []


def test_cli_unreadable_word_banks_are_a_usage_error(monkeypatch, tmp_path, capsys):
    from localscribe import cli

    def locked():
        raise PermissionError(13, "The process cannot access the file")

    monkeypatch.setattr(cli, "load_vocabularies", locked)
    with pytest.raises(SystemExit) as caught:
        run_cli(monkeypatch, tmp_path, "--vocabulary", "Zorblax seminar")
    assert caught.value.code == 2 and "cannot access" in capsys.readouterr().err


def test_cli_says_which_terms_are_left_out(monkeypatch, tmp_path, capsys):
    # One token per word and comma: 112 one-word terms take 223 tokens.
    write_tokenizer(tmp_path / "models" / "whisper" / "large-v3")
    save_vocabularies([Vocabulary("Zorblax seminar", made_up_terms(120))], tmp_path / "vocabularies.json")
    code, _ = run_cli(monkeypatch, tmp_path, "--vocabulary", "Zorblax seminar")
    warning = next(line for line in capsys.readouterr().out.splitlines() if "left out" in line)
    assert code == 0 and "8 term(s)" in warning and warning.endswith(join_terms(made_up_terms(120)[112:]))
    assert FakeEngine.runs[0].hotwords == join_terms(made_up_terms(112))


def test_cli_estimate_warns_but_keeps_every_term(monkeypatch, tmp_path, capsys):
    save_vocabularies([Vocabulary("Zorblax seminar", made_up_terms(60))], tmp_path / "vocabularies.json")
    code, _ = run_cli(monkeypatch, tmp_path, "--vocabulary", "Zorblax seminar")
    warning = next(line for line in capsys.readouterr().out.splitlines() if "estimate" in line)
    assert code == 0 and "may" in warning and warning.endswith(join_terms(made_up_terms(60)[55:]))
    assert FakeEngine.runs[0].hotwords == join_terms(made_up_terms(60))


# ---- the picker and the editor, in a real (offscreen) Qt ----------------------------
PICKER_SCRIPT = r'''
import json
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
app = QApplication([])
from localscribe import i18n
i18n.set_language("en")
from localscribe.vocabulary import TokenCounter, Vocabulary
from localscribe.ui.vocabulary_picker import VocabularyEditor, VocabularyPicker

out, events = {}, []
picker = VocabularyPicker()
for name in ("picked", "new_requested", "edit_requested", "delete_requested"):
    getattr(picker, name).connect(lambda value, name=name: events.append([name, value]))
picker.set_vocabularies([Vocabulary("Zorblax seminar", ["a", "b"]), Vocabulary("Lab meeting", ["c"])], "lab MEETING")
picker.resize(240, 32)
picker.show()
out["shown"] = picker.currentText()

def popup():
    picker.showPopup()
    app.processEvents()
    return picker._popup

def row(p, name):
    return p.list.visualRect(p.list.model().index(p.visible_names().index(name), 0))

p = popup()
out["rows"] = p.visible_names()
QTest.keyClicks(p.search, "zor")
out["filtered"] = p.visible_names()
QTest.keyClick(p.search, Qt.Key_Return)
app.processEvents()
out["after_enter"] = [picker.currentText(), picker._popup is None]

p = popup()
QTest.keyClick(p.search, Qt.Key_Up)  # from Zorblax seminar (the choice) up to Lab meeting
QTest.keyClick(p.search, Qt.Key_Up)  # and on to None
QTest.keyClick(p.search, Qt.Key_Return)
app.processEvents()
out["after_keys"] = picker.currentText()

p = popup()
QTest.keyClicks(p.search, "Glimmer studies")
out["no_match"] = [p.visible_names(), p.lbl_empty.isVisible()]
p.btn_new.click()
app.processEvents()

p = popup()
QTest.mouseClick(p.list.viewport(), Qt.LeftButton, Qt.NoModifier,
                 p.delegate.button_rects(row(p, "Lab meeting"))["edit"].center())
app.processEvents()
p = popup()
QTest.mouseClick(p.list.viewport(), Qt.LeftButton, Qt.NoModifier,
                 p.delegate.button_rects(row(p, "Zorblax seminar"))["delete"].center())
app.processEvents()
p = popup()
rect = row(p, "Lab meeting")
QTest.mouseClick(p.list.viewport(), Qt.LeftButton, Qt.NoModifier, QPoint(rect.left() + 20, rect.center().y()))
app.processEvents()
out["events"] = list(events)
out["final"] = picker.currentText()

p = popup()
QTest.keyClick(p.search, Qt.Key_Escape)
app.processEvents()
out["esc_closes"] = picker._popup is None
p = popup()
picker.hidePopup()
app.processEvents()
out["hide_closes"] = picker._popup is None
p = popup()
rect = row(p, "Lab meeting")
buttons = p.delegate.button_rects(rect)
out["hits"] = [p.delegate.hit(rect, buttons["edit"].center()), p.delegate.hit(rect, buttons["delete"].center()),
               p.delegate.hit(rect, QPoint(rect.left() + 20, rect.center().y()))]
out["reopened"] = p.isVisible()
p.close()
app.processEvents()
out["quiet"] = events == out["events"]  # closing without a choice changes nothing

editor = VocabularyEditor(None, ["Lab meeting"], TokenCounter(), hotwords="Dr. Fennimore", name_hint="Glimmer studies")
out["name_hint"] = editor.txt_name.text()
editor.txt_terms.setPlainText("Quuxian\nquuxian, Vexley drift\n\n")
out["count"] = editor.lbl_count.text()
out["combined"] = [editor.lbl_combined.text(), not editor.lbl_combined.isHidden()]
editor.txt_name.setText("lab meeting")
editor.accept()
out["taken"] = [editor.result(), editor.lbl_error.text()]
editor.txt_name.setText("   ")
editor.accept()
out["missing"] = editor.lbl_error.text()
editor.txt_name.setText("  Glimmer   studies ")
editor.accept()
v = editor.vocabulary()
out["saved"] = [editor.result(), v.name, v.terms]
editor.txt_terms.setPlainText("\n".join(f"Zorblax{i}" for i in range(60)))
out["over"] = [editor.lbl_count.text(), editor.lbl_count.styleSheet()]

edit = VocabularyEditor(Vocabulary("Lab meeting", ["Plonk assay"]), ["Zorblax seminar"], TokenCounter())
out["edit"] = [edit.windowTitle(), edit.txt_name.text(), edit.txt_terms.toPlainText(), edit.lbl_combined.isHidden()]
print(json.dumps(out))
'''


def test_picker_and_editor():
    # Real Qt widgets, offscreen, in their own process so no QApplication leaks into other tests.
    import os
    import subprocess
    import sys

    env = {**os.environ, "QT_QPA_PLATFORM": "offscreen"}
    proc = subprocess.run([sys.executable, "-c", PICKER_SCRIPT], cwd=pathlib.Path(__file__).resolve().parent.parent,
                          env=env, capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr
    out = json.loads(proc.stdout.strip().splitlines()[-1])
    assert out["shown"] == "Lab meeting"
    assert out["rows"] == ["", "Lab meeting", "Zorblax seminar"]  # None first, then by name
    assert out["filtered"] == ["Zorblax seminar"]
    assert out["after_enter"] == ["Zorblax seminar", True]
    assert out["after_keys"] == "None"
    assert out["no_match"] == [[], True]
    assert out["events"] == [["picked", "Zorblax seminar"], ["picked", ""], ["new_requested", "Glimmer studies"],
                             ["edit_requested", "Lab meeting"], ["delete_requested", "Zorblax seminar"],
                             ["picked", "Lab meeting"]]
    assert out["final"] == "Lab meeting"
    assert out["esc_closes"] and out["hide_closes"] and out["reopened"] and out["quiet"]
    assert out["hits"] == ["edit", "delete", None]
    assert out["name_hint"] == "Glimmer studies"
    assert out["count"] == "2 term(s), about 8 / 223 tokens (estimate)"
    assert out["combined"] == ["With Names and terms from Settings: 12 / 223 tokens", True]
    assert out["taken"][0] == 0 and "Lab meeting" in out["taken"][1]
    assert out["missing"] == "Enter a name for the word bank."
    assert out["saved"] == [1, "Glimmer studies", ["Quuxian", "Vexley drift"]]
    assert out["over"][0].startswith("60 term(s), about 240 / 223 tokens (estimate)")
    assert "#DC2626" in out["over"][1]
    assert out["edit"] == ["Edit word bank", "Lab meeting", "Plonk assay", True]
