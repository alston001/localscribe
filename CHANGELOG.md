# Changelog

## 0.1.1

Tested on a real 78-minute classroom recording (iPhone Voice Memos, several speakers).

- **Fewer skipped sentences.** Speech is now found with a more sensitive voice detector and split into clips of at most 28 seconds at natural pauses; Whisper decodes each clip on its own. Before, quiet remarks and some students' questions near Whisper's 30-second window edges were dropped, and one phone number came out as "9888" instead of "988". When we decoded those passages in isolation, Whisper heard them clearly, so the speech was really there.
- **pyannote verified end to end.** With the pyannote model installed, speaker identification on a GPU took about 1.5 minutes for the 78-minute recording (sherpa-onnx on the CPU: about 10 minutes).
- **Presets no longer cap speakers too tightly.** Lecture and online-meeting presets now detect any number of speakers, and group meetings allow up to 10. On the classroom recording (7 voices: two main speakers and five students), a cap of 5 made pyannote split one main speaker in two. Without the cap, pyannote and sherpa-onnx agreed on 99% of the main speakers' words.
- Quieter logs: harmless warnings from pyannote and PyTorch are no longer printed.
- `run.bat` explains what to do when the virtual environment's Python is missing, instead of failing with "No Python at …".
- README: screenshots, settings reference, troubleshooting and FAQ.

## 0.1.0

First release: offline transcription with speaker identification for Windows. It includes Whisper (GPU/CPU), pyannote and sherpa-onnx speaker identification, scenario presets, seven export formats, iPhone Voice Memos (.qta) support, an audio converter and an English/Traditional Chinese interface.
