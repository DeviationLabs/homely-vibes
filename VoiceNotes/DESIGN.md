# VoiceNotes Design Document

Local push-to-talk voice transcription for macOS Apple Silicon.
Hold ⌥ right → speak → release → text appears in `~/bin/knowledge/notes/`.

---

## 1. System Block Diagram

```
┌─────────────────────────────────────────────────────────────────────┐
│  macOS Menu Bar                                                     │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │  VoiceNotesApp (rumps, main thread)                          │   │
│  │  🎙 VoiceNotes  /  🔴 Recording...  /  ⏳  /  ✅ Saved      │   │
│  └──────┬──────────────┬───────────────────────────────────────┘   │
└─────────│──────────────│────────────────────────────────────────────┘
          │              │
    ┌─────▼──────┐  ┌────▼─────────┐
    │ Hotkey     │  │ SessionWriter │
    │ Listener   │  │ (file I/O)    │
    │ (pynput)   │  │               │
    │ daemon thd │  │ ~/notes/      │
    └─────┬──────┘  │ YYYY-MM-DD    │
          │  press  │ Thh-mm.md     │
          │  release└───────▲───────┘
          │                 │ append(text)
    ┌─────▼──────────────────┴───────────────────┐
    │          AudioRecorder                      │
    │  ┌──────────────┐    ┌──────────────────┐  │
    │  │ sounddevice  │    │  VAD thread       │  │
    │  │ InputStream  │───►│  (webrtcvad)      │  │
    │  │ (Metal audio)│    │  phrase detector  │  │
    │  │ 16kHz mono   │    │                   │  │
    │  │ 30ms blocks  │    │ speech → silence  │  │
    │  └──────────────┘    │ → emit phrase     │  │
    │    audio callback    └────────┬──────────┘  │
    │    → frame_queue              │ on_chunk    │
    └───────────────────────────────│─────────────┘
                                    │
                          ┌─────────▼──────────┐
                          │    Transcriber      │
                          │  (pywhispercpp)     │
                          │  whisper.cpp + Metal│
                          │  large-v3-turbo     │
                          │  ~400ms / phrase    │
                          └────────────────────┘
```

---

## 2. State Machine: AudioRecorder

```
                    ┌─────────────────────────────────────────────────┐
                    │                    IDLE                          │
                    │  • no audio stream open                          │
                    │  • VAD thread not running                        │
                    │  • frame_queue empty                             │
                    └──────────────────┬──────────────────────────────┘
                                       │ start_recording()
                                       │ (key_down event)
                    ┌──────────────────▼──────────────────────────────┐
                    │                  RECORDING                       │
                    │  • sounddevice stream → frame_queue (30ms/frame) │
                    │  • VAD thread running, consuming frame_queue     │
                    │                                                  │
                    │    VAD sub-loop:                                 │
                    │    ┌────────────────────────────────────────┐   │
                    │    │  frame arrives                          │   │
                    │    │       │                                 │   │
                    │    │  is_speech?                             │   │
                    │    │    YES → append to speech_frames        │   │
                    │    │         reset silence_count             │   │
                    │    │    NO  → if in_speech:                  │   │
                    │    │           append (trailing context)     │   │
                    │    │           silence_count++               │   │
                    │    │           if silence_count ≥ 13 frames  │   │
                    │    │             AND len ≥ 6 speech frames:   │   │
                    │    │             → emit chunk                 │   │
                    │    │               ↓ on_chunk(audio)          │   │
                    │    │               ↓ Transcriber.transcribe() │   │
                    │    │               ↓ SessionWriter.append()   │   │
                    │    └────────────────────────────────────────┘   │
                    └──────────────────┬──────────────────────────────┘
                                       │ stop_recording()
                                       │ (key_up event)
                    ┌──────────────────▼──────────────────────────────┐
                    │                  FLUSHING                        │
                    │  • sounddevice stream stopped                    │
                    │  • sentinel None → frame_queue                   │
                    │  • VAD thread flushes remaining speech_frames    │
                    │  • VAD thread exits                              │
                    │  • vad_thread.join(timeout=5s)                   │
                    └──────────────────┬──────────────────────────────┘
                                       │ join() returns
                                       ▼
                                     IDLE
```

---

## 3. State Machine: VoiceNotesApp (menu bar)

```
  ┌──────────────┐
  │  🎙 IDLE     │◄────────────────────────────────────────────────┐
  │              │                                                  │
  └──────┬───────┘                                          Timer fires
         │ key_down                                         after 2s
         │
         ▼ (if model not loaded yet)
  ┌──────────────┐
  │ ⏳ LOADING   │  set_title(LOADING) dispatched via Timer(0) to main runloop
  │              │  (model loads in VAD/transcriber thread on first chunk)
  └──────┬───────┘
         │ start_recording() called
         ▼
  ┌──────────────┐
  │ 🔴 RECORDING │  Audio capturing. Phrases appear in notes file in real time.
  │              │  on_chunk → transcribe → append (all in VAD thread)
  └──────┬───────┘
         │ key_up
         ▼
  ┌──────────────┐
  │  ✅ SAVED    │  stop_recording() + writer.close() + set_title(SAVED)
  │              │
  └──────────────┘
```

---

## 4. Threading Model

```
Thread              Role                                  Calls
──────────────────────────────────────────────────────────────────────
Main (rumps)        Menu bar event loop                   rumps callbacks
                    Title updates (Timer(0) dispatched)

pynput daemon       Global keyboard monitoring            _on_key_press()
                    (one thread per Listener)             _on_key_release()

sounddevice audio   Hardware audio callback               AudioRecorder._audio_callback()
                    (real-time, must be fast)             → frame_queue.put()

VAD daemon          Phrase detection + transcription      webrtcvad.is_speech()
                    (one thread per recording session)    Transcriber.transcribe()
                                                          SessionWriter.append()
```

**Key invariant**: `Transcriber.transcribe()` is called only from the VAD thread,
never concurrently — pywhispercpp/whisper.cpp is not reentrant.

**Title update safety**: All `self.title = ...` from background threads are
dispatched via `rumps.Timer(interval=0).start()` which schedules execution on
the Objective-C main runloop.

---

## 5. Sequence Diagram: Single Recording Session

```
User      pynput    VoiceNotesApp   AudioRecorder   VAD thread   Transcriber  SessionWriter   File
  │          │            │               │               │            │            │           │
  │ hold ⌥r  │            │               │               │            │            │           │
  │─────────►│            │               │               │            │            │           │
  │          │ on_press() │               │               │            │            │           │
  │          │───────────►│               │               │            │            │           │
  │          │            │ writer.open() │               │            │            │           │
  │          │            │────────────────────────────────────────────────────────►│           │
  │          │            │               │               │            │            │ create    │
  │          │            │               │               │            │            │ file      │
  │          │            │               │               │            │            │──────────►│
  │          │            │ start_rec()   │               │            │            │           │
  │          │            │──────────────►│               │            │            │           │
  │          │            │               │ start VAD thd │            │            │           │
  │          │            │               │──────────────►│            │            │           │
  │          │            │               │ open stream   │            │            │           │
  │          │            │               │               │            │            │           │
  │ speaking │            │               │               │            │            │           │
  │          │            │               │ audio frame   │            │            │           │
  │          │            │               │──────────────►│            │            │           │
  │          │            │               │ audio frame   │            │            │           │
  │          │            │               │──────────────►│ (speech)   │            │           │
  │ pause    │            │               │               │            │            │           │
  │          │            │               │ silence frame │            │            │           │
  │          │            │               │──────────────►│ silence×13 │            │           │
  │          │            │               │               │ → emit     │            │           │
  │          │            │               │               │ on_chunk() │            │           │
  │          │            │               │               │────────────────────────►│           │
  │          │            │               │               │ transcribe(audio)       │           │
  │          │            │               │               │────────────►│           │           │
  │          │            │               │               │◄────────────│  "hello"  │           │
  │          │            │               │               │ append("hello ")        │           │
  │          │            │               │               │────────────────────────►│           │
  │          │            │               │               │            │            │──────────►│
  │          │            │               │               │            │            │  "hello " │
  │          │            │               │     (more phrases...)      │            │           │
  │ release  │            │               │               │            │            │           │
  │─────────►│            │               │               │            │            │           │
  │          │ on_release │               │               │            │            │           │
  │          │───────────►│               │               │            │            │           │
  │          │            │ stop_rec()    │               │            │            │           │
  │          │            │──────────────►│               │            │            │           │
  │          │            │               │ stop stream   │            │            │           │
  │          │            │               │ put(None)────►│ flush      │            │           │
  │          │            │               │               │ final chunk│            │           │
  │          │            │               │               │────────────────────────►│──────────►│
  │          │            │               │               │ thread exit│            │           │
  │          │            │ writer.close()│               │            │            │           │
  │          │            │────────────────────────────────────────────────────────►│           │
  │          │            │               │               │            │            │ write --- │
  │          │            │               │               │            │            │──────────►│
  │          │            │ set_title(✅) │               │            │            │           │
```

---

## 6. Data Flow: Audio → Text → File

```
sounddevice InputStream
    │
    │ float32 ndarray, shape (480, 1)  [30ms at 16kHz]
    ▼
frame_queue  (thread-safe Queue)
    │
    │ float32 ndarray (same)
    ▼
VAD processing
    │ convert: float32 → int16 PCM bytes
    │ webrtcvad.Vad.is_speech(pcm_bytes, 16000) → bool
    │ accumulate speech_frames[]
    │ detect silence ≥ 400ms
    ▼
phrase audio chunk
    │ float32 ndarray, shape (N,)  [0.3s – 3s typical]
    ▼
pywhispercpp.Model.transcribe(audio)
    │ whisper.cpp C++ inference
    │ Metal GPU acceleration (Apple Silicon)
    │ ~400ms latency
    ▼
list[Segment]  →  join segment.text  →  str
    │
    │ e.g. "And this is my voice note for today"
    ▼
SessionWriter.append(text + " ")
    │ file.write(text)
    │ file.flush()    ← line-buffered; visible immediately in any viewer
    ▼
~/bin/knowledge/notes/2026-05-06T14-22.md
```

---

## 7. File Output Format

```markdown
## 2026-05-06 14:22
And this is my voice note for today. I want to
capture this idea about the architecture of the system.
The VAD approach gives me near-word-by-word output
because each phrase is transcribed within 400ms.

---
```

Each recording session → one file. The file is safe to open in any Markdown
viewer (VSCode, Obsidian, etc.) while recording is active — new text appears
as you speak.

---

## 8. Configuration Reference

```yaml
# config/default.yaml → voice_notes section
voice_notes:
  model_id: "large-v3-turbo"   # whisper.cpp model; auto-downloads to ~/.cache/pywhispercpp/
  hotkey: "right_option"       # ⌥ right — configurable to f5, f13, left_option, etc.
  notes_dir: "~/bin/knowledge/notes"
  sample_rate: 16000           # Hz (whisper.cpp requirement)
  channels: 1                  # mono
  vad_aggressiveness: 2        # 0 (least) – 3 (most aggressive silence detection)
  n_threads: 4                 # CPU threads; Metal GPU used automatically
```

**Tuning VAD aggressiveness**:
- `0` — permissive: keeps more audio, fewer missed words, more false phrases
- `2` — balanced (default): good for normal speech in quiet environment
- `3` — aggressive: cuts through noise well; may clip sentence starts in loud rooms

**Model size vs. accuracy tradeoff**:

| Model             | Size   | Latency (M2) | Notes                       |
|-------------------|--------|-------------|------------------------------|
| `large-v3-turbo`  | 1.6 GB | ~400ms      | Best accuracy; **recommended** |
| `medium`          | 1.5 GB | ~250ms      | Good balance                 |
| `small`           | 488 MB | ~100ms      | Faster, lower accuracy       |
| `base`            | 145 MB | ~50ms       | Near-real-time, basic quality |

---

## 9. Dependencies

```
pywhispercpp   — Python bindings for whisper.cpp (C/C++ Whisper inference, Metal backend)
sounddevice    — Audio capture via PortAudio (works out-of-the-box on macOS)
webrtcvad      — Google's WebRTC Voice Activity Detection (C extension, 30ms frames)
rumps          — macOS menu-bar app framework (Objective-C / PyObjC based)
pynput         — Global keyboard/mouse event listener (requires Accessibility permission)
```

Install:
```bash
uv sync --extra voice 2>&1 | tee /tmp/voice_notes_install.log
```

---

## 10. First-Run Checklist

```
□ uv sync --extra voice
□ uv run python VoiceNotes/voice_notes.py
□ Grant Accessibility:  System Settings → Privacy & Security → Accessibility → Terminal
□ Grant Microphone:     System Settings → Privacy & Security → Microphone → Terminal
□ Hold ⌥ right — menu bar shows 🔴 Recording...
□ Speak a sentence, pause — text appears in notes file within ~400ms
□ Release ⌥ right — menu bar shows ✅ Saved
□ Open ~/bin/knowledge/notes/ — file exists with transcription
```
