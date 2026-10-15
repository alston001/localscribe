import subprocess
import wave

import numpy as np
import pytest

from localscribe.core.convert import convert_file
from localscribe.core.errors import UserError
from localscribe.core.media import (AudioStream, _channel_count, best_audio_stream, ffmpeg_exe, load_audio,
                                    probe)


@pytest.fixture
def tone(tmp_path):
    path = tmp_path / "tone.wav"
    t = np.arange(32000) / 16000
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes((np.sin(2 * np.pi * 440 * t) * 8000).astype(np.int16).tobytes())
    return path


def ffmpeg(*args):
    subprocess.run([ffmpeg_exe(), "-y", "-hide_banner", "-loglevel", "error", *args], check=True)


def spatial_qta(tone, tmp_path):
    """Imitates an iPhone 16 Pro voice memo: 4-channel 'apac' track + stereo AAC fallback."""
    path = tmp_path / "memo.qta"
    ffmpeg("-i", str(tone), "-filter_complex", "[0:a]pan=4c|c0=c0|c1=c0|c2=c0|c3=c0[q];[0:a]aformat=channel_layouts=stereo[s]",
           "-map", "[q]", "-map", "[s]", "-c:a", "aac", "-metadata", "title=Memo", "-f", "mov", str(path))
    data = bytearray(path.read_bytes())
    at = data.find(b"mp4a", data.find(b"stsd"))
    data[at:at + 4] = b"apac"
    path.write_bytes(bytes(data))
    return path


def test_channel_count():
    assert [_channel_count(x) for x in ("mono", "stereo", "4.0", "5.1(side)", "6 channels", "ambisonic 1")] \
        == [1, 2, 4, 6, 6, 4]


def test_best_stream_skips_apple_spatial_audio():
    streams = [AudioStream(0, "none (apac / 0x63617061)", 4), AudioStream(1, "aac (LC) (mp4a / 0x6134706D)", 2)]
    assert best_audio_stream(streams).index == 1
    assert best_audio_stream([AudioStream(0, "aac (LC)", 6), AudioStream(1, "aac (LC)", 2)]).index == 1
    assert best_audio_stream([]) is None


def test_spatial_qta_decodes_the_stereo_track(tone, tmp_path):
    memo = spatial_qta(tone, tmp_path)
    info = probe(memo)
    assert [s.decodable for s in info.audio] == [False, True]
    audio = load_audio(memo)
    assert abs(len(audio) / 16000 - 2.0) < 0.1


def test_convert_keeps_metadata_and_never_overwrites(tone, tmp_path):
    memo = spatial_qta(tone, tmp_path)
    out = tmp_path / "out"
    first = convert_file(memo, out, "m4a")
    second = convert_file(memo, out, "m4a")
    assert first.name == "memo.m4a" and second.name == "memo (2).m4a"
    assert not list(out.glob("*.part"))
    info = probe(first)
    assert info.audio[0].channels == 2 and abs(info.duration - 2.0) < 0.1
    tags = subprocess.run([ffmpeg_exe(), "-hide_banner", "-i", str(first)], capture_output=True).stderr
    assert b"Memo" in tags
    for fmt in ("mp3", "wav", "flac"):
        assert convert_file(memo, out, fmt).suffix == f".{fmt}"


def test_convert_rejects_files_without_audio(tmp_path):
    junk = tmp_path / "notes.txt"
    junk.write_text("not audio")
    with pytest.raises(UserError):
        convert_file(junk, tmp_path, "mp3")


def test_converting_a_cut_off_file_warns(tmp_path):
    # ffmpeg converts a truncated file "successfully": only the lengths show what is missing.
    full = tmp_path / "full.m4a"
    ffmpeg("-f", "lavfi", "-i", "sine=frequency=300:duration=20", "-ar", "16000",
           "-c:a", "aac", "-movflags", "+faststart", str(full))
    cut = tmp_path / "cut.m4a"
    data = full.read_bytes()
    cut.write_bytes(data[: len(data) // 2])
    out = tmp_path / "out"
    warnings: list[dict] = []
    converted = convert_file(cut, out, "mp3", warnings=warnings)
    assert converted.exists()  # the readable half is still worth keeping
    assert [w["key"] for w in warnings] == ["warn_partial_decode"] and warnings[0]["expected"] == "0:20"
    complete: list[dict] = []
    convert_file(full, out, "mp3", warnings=complete)
    assert complete == []
