"""Chinese transcripts in Traditional characters (OpenCC), word by word and in the whole pipeline."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from localscribe.core import chinese
from localscribe.core.asr import AsrResult, Word
from localscribe.core.diarization import SpeakerCount
from localscribe.core.pipeline import JobOptions
from test_pipeline import FakeTranscriber, fake_models, make_engine  # noqa: F401  (fake_models is a fixture)

ROOT = Path(__file__).resolve().parent.parent


def chars(text: str, start: float = 0.0, step: float = 0.2, prob: float = 0.9) -> list[Word]:
    """One word per character, the way Whisper times Chinese."""
    return [Word(round(start + i * step, 2), round(start + (i + 1) * step, 2), c, prob) for i, c in enumerate(text)]


def joined(words: list[Word]) -> str:
    return "".join(w.text for w in words)


# ---- converting words ----------------------------------------------------------------
def test_taiwan_wording_changes_phrases_and_keeps_every_time():
    words = chars("我们用软件处理信息。")
    out = chinese.to_traditional(words, "tw_phrases")
    assert joined(out) == "我們用軟體處理資訊。"
    assert [(w.start, w.end, w.prob) for w in out] == [(w.start, w.end, w.prob) for w in words]


def test_characters_only_keeps_mainland_wording():
    assert joined(chinese.to_traditional(chars("我们用软件处理信息。"), "tw")) == "我們用軟件處理信息。"


def test_off_leaves_the_text_as_whisper_wrote_it():
    words = chars("我们用软件。")
    assert chinese.to_traditional(words, "off") == words


@pytest.mark.parametrize("style", ["tw_phrases", "tw"])
def test_tai_stays_tai_as_most_people_write_it(style):
    # OpenCC writes the formal 臺; everyday Taiwanese writing uses 台. 颱 (typhoon) is another character.
    assert joined(chinese.to_traditional(chars("台湾大学在台北，台风要来了。"), style)) == "台灣大學在台北，颱風要來了。"


def test_a_phrase_that_grows_is_spread_over_its_words():
    words = chars("这个代码。")  # 代码 becomes 程式碼: three characters from two words
    out = chinese.to_traditional(words, "tw_phrases")
    assert joined(out) == "這個程式碼。"
    assert len(out) == len(words) and all(w.text for w in out)
    assert [(w.start, w.end) for w in out] == [(w.start, w.end) for w in words]


def test_a_phrase_inside_one_word_grows_in_place():
    words = [Word(0.0, 0.5, "这个", 0.9), Word(0.5, 1.0, "代码", 0.6), Word(1.0, 1.2, "。", 0.9)]
    out = chinese.to_traditional(words, "tw_phrases")
    assert [w.text for w in out] == ["這個", "程式碼", "。"] and out[1].prob == 0.6


def test_words_in_a_word_bank_keep_their_spelling():
    # The bank says 代碼, so 代码 (Simplified) becomes 代碼, not Taiwan's 程式碼.
    out = chinese.to_traditional(chars("这个代码很长。"), "tw_phrases", keep=["代碼", "BERT"])
    assert joined(out) == "這個代碼很長。"
    already = chinese.to_traditional(chars("這個代碼很長。"), "tw_phrases", keep=["代碼"])
    assert joined(already) == "這個代碼很長。"


def test_latin_words_and_their_spaces_are_untouched():
    words = [Word(0.0, 0.3, "我们", 0.9), Word(0.3, 0.5, "用", 0.9), Word(0.5, 0.9, " BERT", 0.9),
             Word(0.9, 1.2, " 模型", 0.9), Word(1.2, 1.6, "做", 0.9), Word(1.6, 2.4, " tokenization", 0.9)]
    out = chinese.to_traditional(words, "tw_phrases")
    assert [w.text for w in out] == ["我們", "用", " BERT", " 模型", "做", " tokenization"]


def test_a_long_transcript_converts_sentence_by_sentence():
    words = chars("我们讨论数据库。" * 400)  # 3,200 words
    out = chinese.to_traditional(words, "tw_phrases")
    assert joined(out) == "我們討論資料庫。" * 400 and len(out) == len(words)


def test_unknown_styles_count_as_characters_only():
    assert chinese.normalize_style("simplified") == "tw" and chinese.normalize_style("tw_phrases") == "tw_phrases"


# ---- in the pipeline -----------------------------------------------------------------
def run(fake_models, monkeypatch, language: str, words: list[Word], **options):
    monkeypatch.setattr(FakeTranscriber, "transcribe",
                        lambda self, audio, language=None, **kw: AsrResult(language or detected, 1.0, list(words)))
    detected = language
    engine = make_engine(fake_models, device="cpu")
    return engine.transcribe_file(fake_models / "talk.wav", JobOptions(language=None, speakers=SpeakerCount(exact=1),
                                                                      **options))


def test_chinese_recordings_come_out_in_traditional_characters_by_default(fake_models, monkeypatch):
    # Only the script changes: the speaker said 软件 and 信息, so the transcript keeps those words.
    transcript = run(fake_models, monkeypatch, "zh", chars("我们用软件处理信息。"))
    assert "".join(s.text for s in transcript.segments) == "我們用軟件處理信息。"
    assert transcript.settings["chinese_script"] == "tw"


def test_the_word_bank_reaches_the_conversion(fake_models, monkeypatch):
    # Taiwan wording turns 代码 into 程式碼; the bank's 代碼 wins.
    transcript = run(fake_models, monkeypatch, "zh", chars("这个代码很长。"), chinese_script="tw_phrases",
                     keep_terms=("代碼",))
    assert "".join(s.text for s in transcript.segments) == "這個代碼很長。"


@pytest.mark.parametrize("language, text", [("ja", "学校で勉強する。"), ("en", "我们")])
def test_other_languages_are_left_alone(fake_models, monkeypatch, language, text):
    # Japanese kanji are not Chinese characters to convert; 学校 must stay 学校.
    transcript = run(fake_models, monkeypatch, language, chars(text))
    assert "".join(s.text for s in transcript.segments) == text
    assert "chinese_script" not in transcript.settings


def test_switched_off_keeps_simplified(fake_models, monkeypatch):
    transcript = run(fake_models, monkeypatch, "zh", chars("我们用软件。"), chinese_script="off")
    assert "".join(s.text for s in transcript.segments) == "我们用软件。"
    assert transcript.settings["chinese_script"] == "off"


def test_repeats_are_found_before_the_conversion_writes_one_differently(fake_models, monkeypatch):
    # OpenCC reads the first 发展 here as part of 理发 (理髮), so after the conversion only three match.
    transcript = run(fake_models, monkeypatch, "zh", chars("理发展很快" + "发展很快" * 3 + "。"))
    assert [w["key"] for w in transcript.warnings] == ["warn_repeats"]


def test_invented_chinese_credits_go_before_the_conversion(fake_models, monkeypatch):
    words = chars("请不吝点赞订阅转发打赏支持明镜与点点栏目") + chars("我们用软件处理信息。", start=10.0)
    transcript = run(fake_models, monkeypatch, "zh", words)
    assert "".join(s.text for s in transcript.segments) == "我們用軟件處理信息。"


# ---- settings and the command line ---------------------------------------------------
def test_the_setting_defaults_to_characters_only_and_survives_a_restart(tmp_path):
    from localscribe.config import Settings

    assert Settings().chinese_script == "tw" and JobOptions().chinese_script == "tw"
    s = Settings(chinese_script="tw_phrases", hotwords="王小明, NVivo")
    s.save(tmp_path / "settings.json")
    again = Settings.load(tmp_path / "settings.json")
    assert again.chinese_script == "tw_phrases"
    assert again.job_options(keep_terms=["代碼"]).chinese_script == "tw_phrases"
    assert again.job_options(keep_terms=["代碼"]).keep_terms == ("代碼",)
    (tmp_path / "bad.json").write_text(json.dumps({"chinese_script": "martian"}), encoding="utf-8")
    assert Settings.load(tmp_path / "bad.json").chinese_script == "tw"


def test_the_command_line_takes_the_chinese_style(monkeypatch, tmp_path):
    from localscribe import cli

    from localscribe.vocabulary import TokenCounter

    seen = {}

    class Engine:
        store = None

        def __init__(self, *args, **kwargs):
            pass

        def whisper_name(self):
            return "large-v3"

        def transcribe_file(self, path, opts, progress=None):
            seen["opts"] = opts
            raise cli.Cancelled()

    monkeypatch.setattr(cli, "Engine", Engine)
    monkeypatch.setattr(cli, "token_counter", lambda *args: TokenCounter(language="en"))  # no tokenizer here
    assert cli.main([str(tmp_path / "a.wav"), "--chinese", "tw_phrases", "--hotwords", "王小明"]) == 130
    assert seen["opts"].chinese_script == "tw_phrases" and seen["opts"].keep_terms == ("王小明",)
    assert cli.main([str(tmp_path / "a.wav")]) == 130
    assert seen["opts"].chinese_script == "tw"


SCRIPT = r'''
import json, sys
from pathlib import Path
from localscribe import paths
paths.user_data_dir = lambda: Path(sys.argv[1])
from PySide6.QtWidgets import QApplication
app = QApplication([])
from localscribe import i18n
from localscribe.config import Settings
from localscribe.ui.settings_dialog import SettingsDialog

i18n.set_language("zh_TW")
dialog = SettingsDialog(Settings(), [])
choices = [dialog.cmb_chinese.itemText(i) for i in range(dialog.cmb_chinese.count())]
current = dialog.cmb_chinese.currentData()
dialog.cmb_chinese.setCurrentIndex(dialog.cmb_chinese.findData("off"))
dialog.accept()
print(json.dumps({"choices": choices, "current": current, "saved": dialog.settings.chinese_script}))
'''


def test_settings_offer_the_three_choices_with_characters_only_first(tmp_path):
    env = {**os.environ, "QT_QPA_PLATFORM": "offscreen"}
    proc = subprocess.run([sys.executable, "-c", SCRIPT, str(tmp_path)], cwd=ROOT, env=env,
                          capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert proc.returncode == 0, proc.stderr
    out = json.loads(proc.stdout.strip().splitlines()[-1])
    assert out["choices"] == ["繁體中文（只轉字）", "繁體中文（台灣用語）", "不轉換（保留 Whisper 的寫法）"]
    assert out["current"] == "tw" and out["saved"] == "off"


def test_the_tip_warns_that_taiwan_wording_changes_words():
    from localscribe import i18n

    for lang in i18n.LANGUAGES:
        tip = i18n.tr_in(lang, "zh_script_tip")
        assert "檔案" in tip and "開啟" in tip, lang  # 文件 and 打开 become other words, not other characters


def test_the_bundle_takes_opencc_and_its_dictionaries():
    spec = (ROOT / "packaging" / "localscribe.spec").read_text(encoding="utf-8")
    assert 'collect_data_files("opencc", includes=["clib/share/opencc/*"])' in spec
    assert 'collect_delvewheel_libs_directory("opencc"' in spec  # its msvcp140 copy
    assert any(line.startswith("opencc==") for line in (ROOT / "requirements.txt").read_text().splitlines())
