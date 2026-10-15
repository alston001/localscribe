"""Engine.transcribe_file with fake models: failures must reach the user, not vanish."""

import io
import logging
import sys
import types

import numpy as np
import pytest

from localscribe import i18n
from localscribe.core import device as dev
from localscribe.core import media, pipeline
from localscribe.core.asr import AsrResult, Word
from localscribe.core.diarization import SpeakerCount, Turn
from localscribe.core.errors import UserError
from localscribe.core.pipeline import Engine, EngineSettings, JobOptions, _is_gpu_failure

WORDS = [Word(0.0, 0.4, " Hello,", 0.9), Word(0.5, 0.9, " everyone.", 0.9),
         Word(3.0, 3.4, " Thanks", 0.9), Word(3.5, 3.9, " Sam.", 0.9)]


class FakeTranscriber:
    """Records every load; fails on the GPU the way CTranslate2 does when VRAM runs out."""

    loads: list[tuple[str, str]] = []
    words = WORDS

    def __init__(self, path, device, compute_type, cpu_threads=0):
        self.device, self.compute_type = device, compute_type
        FakeTranscriber.loads.append((str(path), device))

    def transcribe(self, audio, language=None, **kwargs):
        if self.device == "cuda":
            raise RuntimeError("CUDA failed with error out of memory")
        return AsrResult(language or "en", 1.0, list(FakeTranscriber.words))


class FakePyannote:
    loads: list[str] = []
    turns: list[Turn] = []
    name = "pyannote"

    def __init__(self, path, device):
        FakePyannote.loads.append(device)
        if device == "cuda":
            raise RuntimeError("CUDA error: no kernel image is available for execution on the device")

    def diarize(self, audio, count, cancel=None, progress=None):
        return list(FakePyannote.turns)


@pytest.fixture
def fake_models(tmp_path, monkeypatch):
    """A GPU machine (24 GB) with Whisper and pyannote installed, all faked."""
    FakeTranscriber.loads, FakeTranscriber.words = [], WORDS
    FakePyannote.loads, FakePyannote.turns = [], [Turn(0.0, 2.0, "A"), Turn(2.5, 4.0, "B")]
    monkeypatch.setattr(pipeline, "load_audio", lambda path, **kw: np.zeros(16000 * 10, np.float32))
    monkeypatch.setattr(dev, "detect", lambda: dev.DeviceInfo(True, "Fake GPU", 24.0, "Fake CPU", 8))
    monkeypatch.setattr(dev, "compute_type", lambda device: "int8" if device == "cpu" else "float16")
    monkeypatch.setattr("localscribe.core.asr.Transcriber", FakeTranscriber)
    backend = types.ModuleType("localscribe.core.diarization.pyannote_backend")
    backend.PyannoteDiarizer = FakePyannote
    monkeypatch.setitem(sys.modules, backend.__name__, backend)
    monkeypatch.setattr(pipeline.ModelStore, "whisper_path", lambda self, name: tmp_path / name)
    monkeypatch.setattr(pipeline.ModelStore, "pyannote_path", lambda self: tmp_path / "pyannote")
    return tmp_path


def make_engine(tmp_path, **settings) -> Engine:
    settings.setdefault("diarizer", "pyannote")
    return Engine(EngineSettings(models_dir=tmp_path, **settings))


def keys(transcript) -> list[str]:
    return [w["key"] for w in transcript.warnings]


def gpu_works(monkeypatch):
    monkeypatch.setattr(FakeTranscriber, "transcribe",
                        lambda self, audio, language=None, **kw: AsrResult("en", 1.0, list(WORDS)))


# ---- A1: no speech ---------------------------------------------------------------
def test_no_speech_is_an_error_not_an_empty_transcript(fake_models):
    FakeTranscriber.words = []
    engine = make_engine(fake_models, device="cpu")
    with pytest.raises(UserError) as caught:
        engine.transcribe_file(fake_models / "silence.wav", JobOptions(speakers=SpeakerCount(exact=1)))
    assert caught.value.key == "err_no_speech"


# ---- A2: partial decode ----------------------------------------------------------
class FakeFfmpeg:
    """ffmpeg that writes `seconds` of audio, then exits with `code`."""

    def __init__(self, seconds: float, code: int):
        self.data = np.zeros(int(16000 * seconds), np.float32).tobytes()
        self.code = code

    def __call__(self, cmd, **kwargs):
        proc = types.SimpleNamespace(stdout=io.BytesIO(self.data),
                                     stderr=io.BytesIO(b"Invalid data found when processing input\n"),
                                     returncode=self.code, kill=lambda: None)
        proc.wait = lambda: self.code
        return proc


def test_decode_that_stops_early_warns(tmp_path, monkeypatch):
    monkeypatch.setattr(media, "probe", lambda path: media.MediaInfo(600.0, []))
    monkeypatch.setattr(media, "ffmpeg_exe", lambda: "ffmpeg")
    monkeypatch.setattr(media.subprocess, "Popen", FakeFfmpeg(seconds=60, code=1))
    warnings: list[dict] = []
    audio = media.load_audio(tmp_path / "cut.m4a", warnings=warnings)
    assert len(audio) == 16000 * 60
    assert [w["key"] for w in warnings] == ["warn_partial_decode"]
    assert warnings[0]["decoded"] == "1:00" and warnings[0]["expected"] == "10:00"


def test_minor_decode_errors_on_complete_audio_stay_quiet(tmp_path, monkeypatch):
    monkeypatch.setattr(media, "probe", lambda path: media.MediaInfo(600.0, []))
    monkeypatch.setattr(media, "ffmpeg_exe", lambda: "ffmpeg")
    monkeypatch.setattr(media.subprocess, "Popen", FakeFfmpeg(seconds=599.5, code=1))
    warnings: list[dict] = []
    media.load_audio(tmp_path / "glitch.m4a", warnings=warnings)
    assert warnings == []


def test_partial_decode_warning_reaches_the_transcript(fake_models, monkeypatch):
    def cut_short(path, warnings=None, **kw):
        warnings.append({"key": "warn_partial_decode", "decoded": "0:10", "expected": "5:00"})
        return np.zeros(16000 * 10, np.float32)

    monkeypatch.setattr(pipeline, "load_audio", cut_short)
    engine = make_engine(fake_models, device="cpu")
    transcript = engine.transcribe_file(fake_models / "cut.m4a", JobOptions(speakers=SpeakerCount(exact=1)))
    assert keys(transcript) == ["warn_partial_decode"]


# ---- A3: GPU -> CPU fallback -------------------------------------------------------
def test_gpu_failure_falls_back_with_a_warning_and_keeps_the_model(fake_models):
    engine = make_engine(fake_models)  # device "auto" resolves to the (faked) GPU
    transcript = engine.transcribe_file(fake_models / "talk.wav", JobOptions(speakers=SpeakerCount(exact=1)))
    assert [device for _, device in FakeTranscriber.loads] == ["cuda", "cpu"]
    assert {name.rsplit("\\", 1)[-1].rsplit("/", 1)[-1] for name, _ in FakeTranscriber.loads} == {"large-v3"}
    assert transcript.settings["whisper_model"] == "large-v3" and transcript.settings["device"] == "cpu"
    assert "warn_gpu_fallback" in keys(transcript)


def test_later_files_still_say_they_ran_on_cpu(fake_models):
    engine = make_engine(fake_models)
    opts = JobOptions(speakers=SpeakerCount(exact=1))
    engine.transcribe_file(fake_models / "one.wav", opts)
    second = engine.transcribe_file(fake_models / "two.wav", opts)
    assert "warn_gpu_fallback" in keys(second)


def test_explicit_cuda_choice_does_not_fall_back(fake_models):
    engine = make_engine(fake_models, device="cuda")
    with pytest.raises(RuntimeError):
        engine.transcribe_file(fake_models / "talk.wav", JobOptions(speakers=SpeakerCount(exact=1)))


def test_gpu_failure_detection_is_narrow():
    assert _is_gpu_failure(RuntimeError("CUDA failed with error out of memory"))
    assert _is_gpu_failure(RuntimeError("cuBLAS failed with status CUBLAS_STATUS_NOT_SUPPORTED"))
    assert _is_gpu_failure(OSError("Could not load library cudnn_ops_infer64_8.dll"))
    assert not _is_gpu_failure(ValueError("bad value in gpu_settings.json"))
    assert not _is_gpu_failure(KeyError("gpu"))


# ---- A4: diarization fallback ------------------------------------------------------
def test_pyannote_cuda_load_failure_falls_back_to_cpu(fake_models, monkeypatch):
    gpu_works(monkeypatch)
    engine = make_engine(fake_models)
    transcript = engine.transcribe_file(fake_models / "talk.wav", JobOptions())
    assert FakePyannote.loads == ["cuda", "cpu"]
    assert engine.device() == "cpu"  # later files skip the broken GPU
    assert "warn_gpu_fallback" in keys(transcript)
    assert len(transcript.speakers) == 2


# ---- A5: speaker count warnings ----------------------------------------------------
def test_no_turns_warns(fake_models):
    FakePyannote.turns = []
    engine = make_engine(fake_models, device="cpu")
    transcript = engine.transcribe_file(fake_models / "talk.wav", JobOptions())
    assert keys(transcript) == ["warn_no_turns"]


@pytest.mark.parametrize("count", [SpeakerCount(exact=3), SpeakerCount(min=3, max=5)])
def test_fewer_speakers_than_requested_warns(fake_models, count):
    engine = make_engine(fake_models, device="cpu")
    transcript = engine.transcribe_file(fake_models / "talk.wav", JobOptions(speakers=count))
    assert transcript.warnings == [{"key": "warn_fewer_speakers", "found": 2, "requested": 3}]


def test_expected_speaker_count_has_no_warnings(fake_models):
    engine = make_engine(fake_models, device="cpu")
    transcript = engine.transcribe_file(fake_models / "talk.wav", JobOptions(speakers=SpeakerCount(exact=2)))
    assert transcript.warnings == []


# ---- A6: device probe --------------------------------------------------------------
def test_explicit_cuda_without_a_gpu_warns(fake_models, monkeypatch):
    monkeypatch.setattr(dev, "detect", lambda: dev.DeviceInfo(False, "", 0.0, "Fake CPU", 8))
    engine = make_engine(fake_models, device="cuda")
    transcript = engine.transcribe_file(fake_models / "talk.wav", JobOptions(speakers=SpeakerCount(exact=1)))
    assert keys(transcript) == ["warn_cuda_unavailable"]


def test_detect_logs_what_it_swallows(monkeypatch, caplog):
    broken = types.ModuleType("ctranslate2")

    def no_driver():
        raise RuntimeError("driver too old")

    broken.get_cuda_device_count = no_driver
    monkeypatch.setitem(sys.modules, "ctranslate2", broken)
    monkeypatch.setattr(dev, "load_cuda_libraries", lambda: True)
    dev.detect.cache_clear()
    try:
        with caplog.at_level(logging.WARNING, logger="localscribe"):
            info = dev.detect()
    finally:
        dev.detect.cache_clear()
    assert info.cuda is False
    assert "driver too old" in caplog.text


def test_device_probe_failure_still_reports_hardware(monkeypatch):
    from localscribe.ui.threads import DeviceProbe

    def boom():
        raise OSError("add_dll_directory failed")

    monkeypatch.setattr(dev, "detect", boom)
    received = []
    probe = DeviceProbe()
    probe.ready.connect(received.append)
    probe.run()
    assert len(received) == 1 and received[0] is not None and received[0].cuda is False


# ---- shared ------------------------------------------------------------------------
def test_every_warning_has_both_languages():
    for key in ("err_no_speech", "warn_partial_decode", "warn_gpu_fallback", "warn_no_turns",
                "warn_fewer_speakers", "warn_cuda_unavailable", "st_done_warn"):
        assert key in i18n.STRINGS and all(i18n.STRINGS[key]), key


def test_warnings_survive_a_save_and_load(tmp_path):
    from localscribe.core.transcript import Transcript

    t = Transcript(source="a.wav", duration=1.0, language="en", created="", app_version="t",
                   settings={}, speakers={}, segments=[],
                   warnings=[{"key": "warn_no_turns"}])
    t.save(tmp_path / "a_transcript.json")
    assert Transcript.load(tmp_path / "a_transcript.json").warnings == [{"key": "warn_no_turns"}]


def test_finished_job_row_shows_its_warnings():
    from localscribe.ui.jobs import Job

    job = Job(1, __import__("pathlib").Path("a.wav"), status="done", warnings=["GPU failed; ran on CPU"])
    assert job.status_text() == i18n.tr("st_done_warn", n=1)


def test_detect_survives_a_broken_cuda_setup(monkeypatch):
    def broken_dlls():
        raise OSError("add_dll_directory failed")

    monkeypatch.setattr(dev, "load_cuda_libraries", broken_dlls)
    monkeypatch.setitem(sys.modules, "ctranslate2", types.SimpleNamespace(get_cuda_device_count=lambda: 0))
    dev.detect.cache_clear()
    try:
        assert dev.detect().cuda is False
    finally:
        dev.detect.cache_clear()


# ---- B4: the English punctuation prompt ------------------------------------------
@pytest.mark.parametrize("language, prompted", [("en", True), (None, False), ("zh", False)])
def test_punctuation_prompt_only_for_english(fake_models, monkeypatch, language, prompted):
    prompts = []

    def record(self, audio, language=None, initial_prompt=None, **kw):
        prompts.append(initial_prompt)
        return AsrResult(language or "en", 1.0, list(WORDS))

    monkeypatch.setattr(FakeTranscriber, "transcribe", record)
    engine = make_engine(fake_models, fast_mode=True)  # batched on the GPU: where the prompt is used
    engine.transcribe_file(fake_models / "talk.wav", JobOptions(language=language, speakers=SpeakerCount(exact=1)))
    assert (prompts[0] is not None) == prompted
