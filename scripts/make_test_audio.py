"""Build synthetic interview recordings with known speaker turns (Windows TTS voices).

Usage:  python scripts/make_test_audio.py [out_dir]
Writes  interview_2spk.wav / .mp4 / _truth.json,  panel_3spk.wav / _truth.json,
        voice_memo_single.qta and voice_memo_spatial.qta (iPhone Voice Memos imitations)
"""

from __future__ import annotations

import json
import random
import subprocess
import sys
import tempfile
import wave
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from localscribe.core.media import ffmpeg_exe  # noqa: E402

ZIRA, DAVID, HANHAN = "Microsoft Zira Desktop", "Microsoft David Desktop", "Microsoft Hanhan Desktop"

INTERVIEW = [
    (ZIRA, "Thank you for joining me today. Could you start by telling me a little about your role in the lab?"),
    (DAVID, "Sure. I'm a third year doctoral student, and most of my work focuses on how older adults use voice assistants at home."),
    (ZIRA, "That sounds fascinating. How did you get interested in that topic?"),
    (DAVID, "Honestly, it started with my grandmother. She bought a smart speaker and kept asking it about the weather, but it never understood her accent."),
    (ZIRA, "Really?"),
    (DAVID, "Yes."),
    (ZIRA, "So that experience shaped your research questions."),
    (DAVID, "Exactly. I wanted to understand why these systems work so well for some people and so poorly for others."),
    (ZIRA, "What methods are you using to study it?"),
    (DAVID, "Mostly semi structured interviews, plus a two week diary study. Participants record short notes every time the assistant fails."),
    (ZIRA, "How many participants have you recruited so far?"),
    (DAVID, "Twenty four. We were aiming for thirty, but recruitment slowed down during the winter."),
    (ZIRA, "Right."),
    (DAVID, "We also had a few people drop out after the first week, which was disappointing."),
    (ZIRA, "Did you notice any patterns in why they dropped out?"),
    (DAVID, "A couple of them said the diary felt like homework. Others simply lost interest once the novelty wore off."),
    (ZIRA, "That makes sense. Let's talk about your findings. What surprised you the most?"),
    (DAVID, "I expected frustration, but I did not expect people to blame themselves. Many participants said things like, I must be speaking wrong."),
    (ZIRA, "Hmm. That is a powerful observation."),
    (DAVID, "It really changed how I think about design. The burden should be on the system, not on the person."),
    (ZIRA, "Before we wrap up, is there anything you would like to add?"),
    (DAVID, "Only that I'm grateful to everyone who took part. Their stories made this project meaningful."),
    (ZIRA, "Thank you so much for your time."),
    (DAVID, "Thank you for having me."),
]

PANEL = [
    (ZIRA, "Welcome everyone. Today we are discussing the new library opening hours."),
    (DAVID, "I think extending the evening hours would help students who work during the day."),
    (HANHAN, "I agree. Many of my classmates study late at night."),
    (ZIRA, "What about weekends?"),
    (DAVID, "Weekends are less important in my opinion. Most people stay home."),
    (HANHAN, "I disagree. Saturday mornings are very busy at the library."),
    (ZIRA, "Interesting. Do we have any data on that?"),
    (HANHAN, "Yes. Last semester the visitor count on Saturday was almost as high as on Monday."),
    (DAVID, "Okay, that is a good point. Maybe we should keep weekends as they are."),
    (ZIRA, "Let's summarize. Longer evenings, and no change to the weekend schedule."),
    (HANHAN, "Sounds good to me."),
    (DAVID, "Agreed."),
]

LABELS = {ZIRA: "Zira", DAVID: "David", HANHAN: "Hanhan"}


def synthesize(lines, workdir: Path) -> list[Path]:
    script = workdir / "tts.ps1"
    manifest = workdir / "lines.json"
    manifest.write_text(json.dumps([{"voice": v, "text": t} for v, t in lines]), encoding="utf-8")
    script.write_text(
        "Add-Type -AssemblyName System.Speech\n"
        "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer\n"
        f"$lines = Get-Content -Raw -Encoding UTF8 '{manifest}' | ConvertFrom-Json\n"
        "$fmt = New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo(16000, "
        "[System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen, [System.Speech.AudioFormat.AudioChannel]::Mono)\n"
        "$i = 0\n"
        "foreach ($l in $lines) {\n"
        "  $s.SelectVoice($l.voice)\n"
        f"  $s.SetOutputToWaveFile(('{workdir}\\line_{{0:D3}}.wav' -f $i), $fmt)\n"
        "  $s.Speak($l.text)\n"
        "  $i++\n"
        "}\n"
        "$s.SetOutputToNull()\n"
        "$s.Dispose()\n",
        encoding="utf-8-sig")
    subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script)], check=True)
    return [workdir / f"line_{i:03d}.wav" for i in range(len(lines))]


def read_wav(path: Path) -> np.ndarray:
    with wave.open(str(path)) as w:
        return np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768


def trim(x: np.ndarray, threshold: float = 0.003) -> np.ndarray:
    idx = np.flatnonzero(np.abs(x) > threshold)
    return x[max(idx[0] - 160, 0): idx[-1] + 160] if len(idx) else x


def build(name: str, lines, out: Path, seed: int) -> Path:
    rng = random.Random(seed)
    with tempfile.TemporaryDirectory() as tmp:
        clips = [trim(read_wav(p)) for p in synthesize(lines, Path(tmp))]
    sr = 16000
    pieces, truth, t = [np.zeros(int(0.8 * sr), np.float32)], [], 0.8
    for (voice, text), clip in zip(lines, clips):
        truth.append({"start": round(t, 3), "end": round(t + len(clip) / sr, 3),
                      "speaker": LABELS[voice], "text": text})
        pieces.append(clip)
        t += len(clip) / sr
        gap = rng.choice([0.15, 0.3, 0.45, 0.6, 0.9])
        pieces.append(np.zeros(int(gap * sr), np.float32))
        t += gap
    audio = np.concatenate(pieces)
    audio += np.random.default_rng(seed).normal(0, 0.002, len(audio)).astype(np.float32)  # faint room noise
    wav = out / f"{name}.wav"
    with wave.open(str(wav), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes((np.clip(audio, -1, 1) * 32767).astype(np.int16).tobytes())
    (out / f"{name}_truth.json").write_text(json.dumps(truth, indent=1), encoding="utf-8")
    print(f"{wav.name}: {len(audio) / sr:.1f}s, {len(truth)} turns")
    return wav


def main() -> None:
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "tests" / "data"
    out.mkdir(parents=True, exist_ok=True)
    wav = build("interview_2spk", INTERVIEW, out, seed=7)
    build("panel_3spk", PANEL, out, seed=11)
    # Same interview as a video file, to exercise the video path.
    subprocess.run([ffmpeg_exe(), "-y", "-hide_banner", "-loglevel", "error",
                    "-f", "lavfi", "-i", "color=c=0x223344:s=320x240:r=5", "-i", str(wav),
                    "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "96k",
                    str(out / "interview_2spk.mp4")], check=True)
    print("interview_2spk.mp4 written")
    make_voice_memos(out / "panel_3spk.wav", out)


def make_voice_memos(source: Path, out: Path) -> None:
    """iOS 18.2+ Voice Memos may save .qta files: QuickTime audio with an Apple Positional Audio
    track (which ffmpeg cannot decode) plus a stereo AAC fallback. Imitate both layouts."""
    ff = [ffmpeg_exe(), "-y", "-hide_banner", "-loglevel", "error", "-i", str(source)]
    subprocess.run(ff + ["-ac", "2", "-c:a", "aac", "-b:a", "128k", "-metadata", "title=Library hours",
                         "-f", "mov", str(out / "voice_memo_single.qta")], check=True)
    spatial = out / "voice_memo_spatial.qta"
    subprocess.run(ff + ["-filter_complex",
                         "[0:a]pan=4c|c0=c0|c1=0.5*c0|c2=0.2*c0|c3=0.1*c0[q];[0:a]aformat=channel_layouts=stereo[s]",
                         "-map", "[q]", "-map", "[s]", "-c:a", "aac", "-b:a", "128k",
                         "-metadata", "title=Library hours", "-f", "mov", str(spatial)], check=True)
    data = bytearray(spatial.read_bytes())
    at = data.find(b"mp4a", data.find(b"stsd"))  # first track's sample entry
    data[at:at + 4] = b"apac"
    spatial.write_bytes(bytes(data))
    print("voice_memo_single.qta and voice_memo_spatial.qta written")


if __name__ == "__main__":
    main()
