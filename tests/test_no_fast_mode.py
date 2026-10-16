"""Fast mode (batched decoding) was removed: in tests it dropped whole sentences without a
warning and couldn't use the word-bank checks, while normal decoding is fast enough on a GPU
and fast mode did nothing on a CPU. Nothing of it may linger."""

import dataclasses
import inspect
import json

import pytest


def test_settings_no_longer_have_fast_mode(tmp_path):
    from localscribe.config import Settings

    assert "fast_mode" not in {f.name for f in dataclasses.fields(Settings)}
    path = tmp_path / "settings.json"  # a file saved by 0.1.1 with fast mode on still loads
    path.write_text(json.dumps({"fast_mode": True, "preset": "custom", "language": "en", "speakers_exact": 3}), encoding="utf-8")
    s = Settings.load(path)
    assert s.language == "en" and s.speakers_exact == 3


def test_engine_has_no_fast_mode_or_batches():
    from localscribe.core import asr, device, pipeline

    assert "fast_mode" not in {f.name for f in dataclasses.fields(pipeline.EngineSettings)}
    assert "batch_size" not in inspect.signature(asr.Transcriber.transcribe).parameters
    assert not hasattr(device, "auto_batch_size")
    assert not hasattr(pipeline, "_PUNCTUATION_PROMPT")
    assert "BatchedInferencePipeline" not in inspect.getsource(asr)


def test_transcripts_no_longer_record_fast_mode():
    from localscribe.core import pipeline

    assert '"fast_mode"' not in inspect.getsource(pipeline)


def test_the_command_line_rejects_fast(capsys):
    from localscribe import cli

    with pytest.raises(SystemExit) as caught:
        cli.main(["talk.wav", "--fast"])
    assert caught.value.code == 2 and "--fast" in capsys.readouterr().err


def test_no_fast_mode_strings_or_controls_remain():
    from localscribe import i18n
    from localscribe.ui import settings_dialog

    assert not {"fast_mode", "fast_mode_tip"} & set(i18n.STRINGS)
    assert "chk_fast" not in inspect.getsource(settings_dialog)
