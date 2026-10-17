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
    speech: list[tuple[float, float]] = []

    def __init__(self, path, device, compute_type, cpu_threads=0):
        self.device, self.compute_type = device, compute_type
        FakeTranscriber.loads.append((str(path), device))

    def transcribe(self, audio, language=None, **kwargs):
        if self.device == "cuda":
            raise RuntimeError("CUDA failed with error out of memory")
        return AsrResult(language or "en", 1.0, list(FakeTranscriber.words), list(FakeTranscriber.speech))


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
    FakeTranscriber.loads, FakeTranscriber.words, FakeTranscriber.speech = [], WORDS, []
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


@pytest.mark.parametrize("fmt, args", [("m4a", ["-c:a", "aac", "-movflags", "+faststart"]),
                                       ("mp3", ["-c:a", "libmp3lame"])])
def test_a_file_cut_off_halfway_warns(tmp_path, fmt, args):
    # ffmpeg reads a truncated file without complaint (exit code 0): the length must decide.
    from test_media import ffmpeg

    full = tmp_path / f"full.{fmt}"
    ffmpeg("-f", "lavfi", "-i", "sine=frequency=300:duration=20", "-ar", "16000", *args, str(full))
    cut = tmp_path / f"cut.{fmt}"
    data = full.read_bytes()
    cut.write_bytes(data[: len(data) // 2])
    warnings: list[dict] = []
    media.load_audio(cut, warnings=warnings)
    assert [w["key"] for w in warnings] == ["warn_partial_decode"]
    assert warnings[0]["expected"] == "0:20"


def test_an_estimated_duration_is_not_trusted(tmp_path, monkeypatch):
    monkeypatch.setattr(media, "probe", lambda path: media.MediaInfo(600.0, [], duration_estimated=True))
    monkeypatch.setattr(media, "ffmpeg_exe", lambda: "ffmpeg")
    monkeypatch.setattr(media.subprocess, "Popen", FakeFfmpeg(seconds=500, code=0))
    warnings: list[dict] = []
    media.load_audio(tmp_path / "vbr.mp3", warnings=warnings)
    assert warnings == []


def test_probe_notices_an_estimated_duration(monkeypatch):
    out = (b"[mp3 @ 0000] Estimating duration from bitrate, this may be inaccurate\n"
           b"  Duration: 00:10:00.00, start: 0.000000, bitrate: 128 kb/s\n"
           b"  Stream #0:0: Audio: mp3, 44100 Hz, stereo, fltp, 128 kb/s\n")
    monkeypatch.setattr(media, "ffmpeg_exe", lambda: "ffmpeg")
    monkeypatch.setattr(media.subprocess, "run", lambda cmd, **k: types.SimpleNamespace(stderr=out, returncode=1))
    info = media.probe("vbr.mp3")
    assert info.duration == 600.0 and info.duration_estimated


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


# ---- speech the voice detector heard but Whisper didn't write ------------------------
def long_recording(monkeypatch, seconds=80):
    monkeypatch.setattr(pipeline, "load_audio", lambda path, **kw: np.zeros(16000 * seconds, np.float32))


def test_speech_without_text_warns(fake_models, monkeypatch):
    long_recording(monkeypatch)
    FakeTranscriber.speech = [(0.0, 4.0), (4.5, 32.0), (32.5, 60.0), (60.2, 75.0)]  # WORDS stop at 3.9 s
    engine = make_engine(fake_models, device="cpu")
    transcript = engine.transcribe_file(fake_models / "class.wav", JobOptions(speakers=SpeakerCount(exact=1)))
    assert transcript.warnings == [{"key": "warn_lost_speech", "times": "0:04–1:15"}]
    assert "0:04–1:15" in i18n.tr_in("en", **transcript.warnings[0])


def test_silence_after_the_text_does_not_warn(fake_models, monkeypatch):
    long_recording(monkeypatch)
    FakeTranscriber.speech = [(0.0, 4.0)]
    engine = make_engine(fake_models, device="cpu")
    transcript = engine.transcribe_file(fake_models / "class.wav", JobOptions(speakers=SpeakerCount(exact=1)))
    assert transcript.warnings == []


def test_lost_speech_hidden_by_invented_thanks_still_warns(fake_models, monkeypatch):
    # Split by the invented "Thank you.", neither half reaches 30 s of speech.
    long_recording(monkeypatch)
    FakeTranscriber.speech = [(0.0, 4.0), (4.5, 32.0), (32.5, 55.0)]
    FakeTranscriber.words = WORDS + [Word(30.0, 30.3, " Thank", 0.15), Word(30.3, 30.6, " you.", 0.99)]
    engine = make_engine(fake_models, device="cpu")
    transcript = engine.transcribe_file(fake_models / "class.wav", JobOptions(speakers=SpeakerCount(exact=1)))
    assert transcript.warnings == [{"key": "warn_lost_speech", "times": "0:04–0:55"}]



def test_gaps_reach_the_transcript_with_what_the_warning_found(fake_models, monkeypatch):
    long_recording(monkeypatch, seconds=120)
    FakeTranscriber.speech = [(0.0, 4.0), (4.5, 32.0), (32.5, 60.0), (60.2, 75.0)]  # WORDS stop at 3.9 s
    engine = make_engine(fake_models, device="cpu")
    transcript = engine.transcribe_file(fake_models / "class.wav", JobOptions(speakers=SpeakerCount(exact=1)))
    assert transcript.warnings == [{"key": "warn_lost_speech", "times": "0:04–1:15"}]
    assert [(g.start, g.end, g.speech) for g in transcript.gaps] == [(3.9, 75.0, True), (75.0, 120.0, False)]


def test_lost_speech_is_looked_for_once(fake_models, monkeypatch):
    calls = []
    monkeypatch.setattr(pipeline, "lost_speech", lambda speech, words: calls.append(1) or [])
    make_engine(fake_models, device="cpu").transcribe_file(fake_models / "a.wav",
                                                           JobOptions(speakers=SpeakerCount(exact=1)))
    assert calls == [1]  # the warning and the gap markers share one result

# ---- sign-offs Whisper invents ------------------------------------------------------
def test_invented_thank_you_is_removed(fake_models):
    FakeTranscriber.words = WORDS[:2] + [Word(1.0, 1.2, " Thank", 0.07), Word(1.2, 1.4, " you.", 0.99)] + WORDS[2:]
    engine = make_engine(fake_models, device="cpu")
    transcript = engine.transcribe_file(fake_models / "talk.wav", JobOptions(speakers=SpeakerCount(exact=1)))
    assert " ".join(s.text for s in transcript.segments) == "Hello, everyone. Thanks Sam."


def test_words_that_come_out_again_and_again_warn(fake_models, monkeypatch):
    # Whisper stuck in a loop: the text stays as it came out, and a warning says where.
    long_recording(monkeypatch)
    loop = [Word(65.0 + i * 0.4, 65.3 + i * 0.4, f" {w}", 0.9) for i, w in enumerate(("the model learns " * 4).split())]
    FakeTranscriber.words = WORDS + loop
    engine = make_engine(fake_models, device="cpu")
    transcript = engine.transcribe_file(fake_models / "class.wav", JobOptions(speakers=SpeakerCount(exact=1)))
    assert transcript.warnings == [{"key": "warn_repeats", "times": "1:05–1:10"}]
    assert "1:05–1:10" in i18n.tr_in("en", **transcript.warnings[0])
    assert " ".join(s.text for s in transcript.segments).count("learns") == 4


# ---- shared ------------------------------------------------------------------------
def test_every_warning_has_both_languages():
    for key in ("err_no_speech", "warn_partial_decode", "warn_gpu_fallback", "warn_no_turns",
                "warn_fewer_speakers", "warn_cuda_unavailable", "warn_lost_speech", "warn_repeats", "st_done_warn"):
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


# ---- "Even out volume" levels only the copy that finds quiet speech ----------------------
def test_levelling_feeds_whisper_the_original_and_finds_quiet_speech_in_a_copy(fake_models, monkeypatch):
    loads, seen = [], {}

    def load(path, normalize=False, denoise=False, **kw):
        loads.append((normalize, denoise))
        return np.full(16000 * 10, 1.0 if normalize else 0.0, np.float32)

    def transcribe(self, audio, language=None, quiet=None, **kw):
        seen["whisper"], seen["quiet"] = float(audio[0]), None if quiet is None else float(quiet[0])
        return AsrResult("en", 1.0, list(WORDS))

    def diarize(self, audio, count, cancel=None, progress=None):
        seen["diarize"] = float(audio[0])
        return list(FakePyannote.turns)

    monkeypatch.setattr(pipeline, "load_audio", load)
    monkeypatch.setattr(FakeTranscriber, "transcribe", transcribe)
    monkeypatch.setattr(FakePyannote, "diarize", diarize)
    engine = make_engine(fake_models, device="cpu")
    engine.transcribe_file(fake_models / "talk.wav", JobOptions(normalize=True))
    assert seen == {"whisper": 0.0, "quiet": 1.0, "diarize": 0.0}  # original, levelled, original
    assert loads == [(False, False), (True, False)]  # no third decode just for diarization
