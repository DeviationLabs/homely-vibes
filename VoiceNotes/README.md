# VoiceNotes — Local Push-to-Talk Voice Transcription

A Wispr Flow-style voice-to-Markdown tool for macOS Apple Silicon. Hold **⌥ right**, speak, release — phrases are transcribed and streamed to a per-session Markdown file in real time.

**Fully local.** No cloud. Uses [whisper.cpp](https://github.com/ggerganov/whisper.cpp) with Metal GPU acceleration via [pywhispercpp](https://github.com/abdeladim-s/pywhispercpp).

## Features

- **Push-to-talk** — hold a key, speak, release. Configurable hotkey (default: ⌥ right)
- **Phrase-level streaming** — webrtcvad detects speech boundaries; each phrase is transcribed and written within ~400ms of the pause that ends it
- **Per-session files** — `~/bin/knowledge/notes/YYYY-MM-DDThh-mm.md`, one file per recording, line-buffered for live `tail -f`
- **Menu-bar UI** — 🎙 idle / 🔴 recording / ✅ saved
- **Apple Silicon optimized** — Metal GPU + unified memory; large-v3-turbo runs at ~2.7× real-time on M2 8GB
- **No mocks in tests** — `stream_factory` and `vad_factory` constructor params keep tests free of monkey-patching

## Architecture

```
Hold ⌥right → HotkeyListener → AudioRecorder ─┐
                                  (sounddevice) │
                                                ├─→ VAD thread (webrtcvad)
                                                │      │
                                                │   on phrase end
                                                │      ▼
                                                │   Transcriber (pywhispercpp + Metal)
                                                │      │
                                                │      ▼
                                                │   SessionWriter → ~/bin/knowledge/notes/*.md
                                                │
Release ⌥right → stop_recording → flush final phrase → close file
```

See [DESIGN.md](DESIGN.md) for full block diagrams, state machines, threading model, and sequence diagrams.

## Setup

### Install voice dependencies

```bash
uv sync --extra voice 2>&1 | tee /tmp/voice_notes_install.log
```

This installs:
- `pywhispercpp` (whisper.cpp Python bindings, Metal-accelerated)
- `sounddevice` (audio capture via PortAudio)
- `webrtcvad-wheels` (Google's WebRTC Voice Activity Detection)
- `rumps` (macOS menu-bar app framework)
- `pynput` (global hotkey listener)

### Grant macOS permissions

First-run requires two permissions in **System Settings → Privacy & Security**:

1. **Accessibility** → add Terminal (or your terminal app) — required for the global hotkey
2. **Microphone** → add Terminal — required for audio capture

### Run

```bash
uv run python VoiceNotes/voice_notes.py 2>&1 | tee /tmp/voice_notes.log
```

A 🎙 icon appears in your menu bar. Hold ⌥ right and start talking.

> **First run downloads a 1.5 GB whisper.cpp model** (`large-v3-turbo`) from Hugging Face to `~/Library/Application Support/pywhispercpp/models/`. Subsequent runs load it from disk in ~2s.

## Usage

| Action | Behavior |
|--------|----------|
| Hold ⌥ right | Menu bar shows 🔴 Recording... — audio is being captured |
| Speak, pause, speak | Each phrase is transcribed and appended to the session file as soon as VAD detects the pause |
| Release ⌥ right | Final phrase flushed, session file closed with `---` separator, menu bar shows ✅ Saved |
| Menu → **Open notes folder** | Opens `~/bin/knowledge/notes/` in Finder |
| Menu → **Show last session** | Opens the most recent `.md` in your default editor |

### Watch transcription live

```bash
tail -f ~/bin/knowledge/notes/$(ls -t ~/bin/knowledge/notes/ | head -1)
```

The file is line-buffered (`buffering=1`), so VSCode / Obsidian / `tail -f` see each phrase the moment it's written.

## Configuration

Defaults live in [`config/default.yaml`](../config/default.yaml). Override in `config/local.yaml`:

```yaml
voice_notes:
  model_id: "large-v3-turbo"          # whisper.cpp model name
  hotkey: "right_option"               # right_option | left_option | f5 | f13 | ...
  notes_dir: "~/bin/knowledge/notes"
  sample_rate: 16000                   # Hz (whisper.cpp requirement)
  channels: 1                          # mono
  vad_aggressiveness: 2                # 0 (least) – 3 (most aggressive silence detection)
  n_threads: 4                         # CPU threads; Metal GPU used automatically
```

### Tuning the model

| Model              | Size   | Latency (M2) | Notes                               |
|--------------------|--------|-------------|-------------------------------------|
| `large-v3-turbo`   | 1.6 GB | ~400ms      | **Recommended** — best accuracy     |
| `medium`           | 1.5 GB | ~250ms      | Good balance                        |
| `small`            | 488 MB | ~100ms      | Faster, lower accuracy              |
| `base`             | 145 MB | ~50ms       | Near-real-time, basic quality       |

### Tuning VAD aggressiveness

- `0` — permissive: keeps more audio, fewer missed words, more false phrases
- `2` — balanced (default): good for normal speech in quiet environments
- `3` — aggressive: cuts through noise; may clip sentence starts in loud rooms

## Output Format

```markdown
## 2026-05-07 00:32
Hello world, this is a voice notes test. The architecture uses Whisper CPP, with metal acceleration on Apple Silicon. 

---
```

One file per recording session. Filename = ISO-ish timestamp from when you pressed the key.

## Troubleshooting

**"This process is not trusted! Input event monitoring will not be possible..."**
Cosmetic warning from pynput at startup. If hotkey events still fire, ignore it. If they don't fire at all, re-grant Accessibility permission.

**App quits immediately after pressing the key (clean exit, no traceback)**
Was a real bug — fixed in PR #162. If you still see it, you're on stale code; `git pull` and `uv sync --extra voice` again.

**Hotkey doesn't respond**
Verify Accessibility for Terminal. After granting, fully quit and relaunch your terminal — pynput won't pick up newly-granted permissions in an already-running process.

**Microphone access denied or no audio captured**
Verify Microphone permission. macOS will silently terminate the process if it tries to capture without permission.

**Slow first transcription**
Expected — first key press triggers the 1.5 GB model download (`large-v3-turbo`). Watch download progress in the terminal.

## Files

| File | Role |
|------|------|
| `voice_notes.py` | rumps menu-bar `App` — orchestrates all components |
| `hotkey.py` | pynput global listener for the configured push-to-talk key |
| `recorder.py` | sounddevice capture + webrtcvad phrase segmentation |
| `transcriber.py` | pywhispercpp wrapper with lazy model load |
| `writer.py` | per-session Markdown writer with line-buffered append |
| `test_voice_notes.py` | Unit tests using DI — 20 tests, no real hardware needed |
| `DESIGN.md` | Full design document with diagrams |

## Development

```bash
# Run unit tests (no audio hardware required)
uv run python -m pytest VoiceNotes/ -v

# Lint
make lint
```

## See Also

- [DESIGN.md](DESIGN.md) — block diagrams, state machines, sequence diagrams
- [whisper.cpp](https://github.com/ggerganov/whisper.cpp) — the C++ inference engine
- [pywhispercpp](https://github.com/abdeladim-s/pywhispercpp) — the Python bindings
- [rumps](https://github.com/jaredks/rumps) — macOS menu-bar app framework
