"""Command line: batch-convert files without the window.

    python -m localscribe.cli interview.mp4 meeting.m4a -f docx,srt -s 2
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from .core import device as dev

dev.prepare_environment()

from . import i18n, paths  # noqa: E402
from .core.diarization import SpeakerCount  # noqa: E402
from .core.errors import Cancelled, UserError  # noqa: E402
from .core.pipeline import Engine, EngineSettings, JobOptions, Progress  # noqa: E402
from .export import FORMATS, write_outputs  # noqa: E402
from .export.common import ExportOptions  # noqa: E402


def parse_speakers(text: str) -> SpeakerCount:
    text = text.strip().lower()
    if text in ("", "auto"):
        return SpeakerCount()
    if "-" in text:
        lo, hi = (int(x) for x in text.split("-", 1))
        return SpeakerCount(min=lo, max=hi)
    return SpeakerCount(exact=int(text))


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):  # Chinese file names must not crash a cp1252 console
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    p = argparse.ArgumentParser(prog="localscribe", description="Offline transcription with speaker identification.")
    p.add_argument("files", nargs="+", type=Path)
    p.add_argument("-f", "--formats", default="docx,txt", help=f"comma-separated: {','.join(FORMATS)}")
    p.add_argument("-o", "--output-dir", type=Path, help="default: next to each input file")
    p.add_argument("-l", "--language", default="en", help="language code such as en, or 'auto'")
    p.add_argument("-s", "--speakers", default="auto", help="'auto', a number (exactly N), or a range such as 2-6")
    p.add_argument("--model", default="auto", help="auto, large-v3, large-v3-turbo, medium, small, base")
    p.add_argument("--device", default="auto", choices=["auto", "cuda", "cpu"])
    p.add_argument("--diarizer", default="auto", choices=["auto", "pyannote", "sherpa"])
    p.add_argument("--fast", action="store_true", help="batched decoding (faster, slightly less accurate)")
    p.add_argument("--normalize", action="store_true", help="even out loud and quiet voices")
    p.add_argument("--denoise", action="store_true", help="reduce background noise")
    p.add_argument("--no-timestamps", action="store_true")
    p.add_argument("--speaker-label", default="Speaker")
    p.add_argument("--hotwords", default="", help="names and terms to help spelling")
    p.add_argument("--models-dir", type=Path, default=None)
    p.add_argument("--headings", default="en", choices=list(i18n.LANGUAGES), help="language of headings in files")
    args = p.parse_args(argv)

    formats = [f.strip() for f in args.formats.split(",") if f.strip()]
    unknown = [f for f in formats if f not in FORMATS]
    if unknown:
        p.error(f"unknown format(s): {', '.join(unknown)}")
    i18n.set_language(args.headings)

    engine = Engine(EngineSettings(models_dir=args.models_dir or paths.default_models_dir(),
                                   extra_model_dirs=[d for d in [paths.bundled_models_dir()] if d],
                                   whisper_model=args.model, device=args.device,
                                   diarizer=args.diarizer, fast_mode=args.fast),
                    log=lambda m: print(f"\r  {m}".ljust(90)))
    opts = JobOptions(language=None if args.language == "auto" else args.language,
                      speakers=parse_speakers(args.speakers), normalize=args.normalize,
                      denoise=args.denoise, hotwords=args.hotwords, speaker_prefix=args.speaker_label)
    export_options = ExportOptions(lang=args.headings, timestamps=not args.no_timestamps)

    def show(p: Progress) -> None:
        bar = "#" * int(p.overall * 30)
        print(f"\r  [{bar:<30}] {p.overall * 100:5.1f}%  {p.stage:<10} {p.detail[:30]:<30}", end="", flush=True)

    failures = 0
    for path in args.files:
        print(f"{path}")
        started = time.monotonic()
        try:
            transcript = engine.transcribe_file(path, opts, progress=show)
            written = write_outputs(transcript, args.output_dir or path.parent, formats, export_options)
            print(f"\r  done in {time.monotonic() - started:.1f}s".ljust(90))
            for warning in transcript.warnings:
                print(f"  warning: {i18n.tr_warning(warning)}")
            for w in written:
                print(f"    {w}")
        except Cancelled:
            print("\n  stopped")
            return 130
        except UserError as exc:
            failures += 1
            print(f"\n  error: {i18n.tr(exc.key, **exc.kwargs)}")
        except Exception as exc:  # keep going with the next file
            failures += 1
            print(f"\n  error: {type(exc).__name__}: {exc}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
