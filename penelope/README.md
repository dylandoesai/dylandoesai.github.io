# Penelope — Cyber Personal AI Assistant

A standalone macOS desktop app: a pure-black, electric-cyan cyber assistant
with a 3D face built from flowing particles that literally form **Penelope
Cruz's** geometry (extracted from reference photos you supply). She speaks
with a warm Mediterranean voice, listens always, watches via webcam, and
runs on Claude Opus 4.7 via your Claude Max plan with full Claude Code
agent capabilities.

Two wake phrases:

- **"Papi's home"** → fullscreen opens, plays Drake's *Papi's Home* every
  time, 12-second cinematic particle assembly, then the full daily brief.
- **"Hey Penelope"** → fullscreen opens with a fast ~2.5-second assembly,
  no song, no brief. She just answers: *"Yes, dear?" / "Yes, daddy?" /
  "What can I do for you?"* and starts listening.

Say **"Sleep Penelope"** (or *"Good night Penelope"*) and the window
hides, the dock icon disappears, and she returns to silent background
hotword-only mode until you wake her again.

---

## Table of contents

1. [Architecture](#architecture)
2. [Folder structure](#folder-structure)
3. [Quick start](#quick-start)
4. [Detailed setup](#detailed-setup)
5. [Face geometry — turning Penelope Cruz into particles](#face-geometry)
6. [Configuring data](#configuring-data)
7. [Customizing personality](#customizing-personality)
8. [Capabilities](#capabilities)
9. [Privacy & encrypted memory](#privacy)
10. [Packaging](#packaging)
11. [Troubleshooting](#troubleshooting)

---

## Architecture

- **Electron + Three.js renderer** — pitch-black canvas, custom WebGL
  particle shader, side panels, Web Audio FFT for reactivity.
- **Python sidecar** — speaks JSON-RPC over stdio. Handles:
  - Porcupine hotword (with Whisper fallback)
  - webrtcvad + sounddevice for always-on VAD
  - faster-whisper for local STT
  - edge-tts for voice (Helena / Elvira / Jenny — auditioned at first launch)
  - `claude` CLI for the brain (Opus 4.7, full Claude Code agent mode)
  - face_recognition for "is it Dylan?"
  - mediapipe FaceMesh for extracting Penelope Cruz's 3D landmarks
  - All integrations: upload-post, Stripe, Gumroad, AdSense,
    Apple Calendar/Reminders/Mail, Spotify, Home Assistant, Slack
- **Encrypted persistent memory** via Fernet + macOS Keychain.

```
┌────────────────────────────────────────────────────────────────┐
│                        Electron renderer                       │
│   Three.js particle face  +  Side panels  +  Audio analyser    │
└─────────────▲──────────────────────────────────────▲───────────┘
              │ IPC (preload bridge)                 │ Web Audio
┌─────────────┴──────────────────────────────────────┴───────────┐
│   Electron main  →  spawns  →  python/penelope_server.py       │
└─────────────▲──────────────────────────────────────────────────┘
              │ JSON-RPC lines + server-pushed events
┌─────────────┴──────────────────────────────────────────────────┐
│  hotword → VAD → Whisper → claude CLI → Edge TTS → renderer    │
│  + webcam face-rec  + integrations  + proactive scheduler      │
└────────────────────────────────────────────────────────────────┘
```

## Folder structure

```
penelope/
├── README.md
├── package.json
├── .gitignore
├── build/
│   └── entitlements.mac.plist
│
├── electron/
│   ├── main.js
│   ├── preload.js
│   └── python-bridge.js
│
├── renderer/
│   ├── index.html
│   ├── styles.css
│   ├── app.js
│   ├── vendor/three.module.js          # populated by setup.sh
│   ├── visualizer/
│   │   ├── penelope-face.js            # the 3D particle face
│   │   ├── face-landmarks.js           # loads assets/face-mesh.json
│   │   ├── audio-analyzer.js
│   │   └── boot-sequence.js            # 12-sec cinematic
│   └── panels/
│       ├── revenue-panel.js
│       ├── analytics-panel.js
│       └── schedule-panel.js
│
├── python/
│   ├── requirements.txt
│   ├── penelope_server.py              # JSON-RPC main
│   ├── config_loader.py
│   ├── extract_face_mesh.py            # Penelope's face → mesh JSON
│   ├── hotword.py                      # Porcupine + Whisper fallback
│   ├── vad_listener.py
│   ├── stt.py
│   ├── tts.py
│   ├── brain.py                        # claude CLI integration
│   ├── face_recog.py                   # owner detection via webcam
│   ├── transcripts.py                  # Fernet + Keychain
│   ├── proactive.py                    # cal/reminder/revenue alerts
│   ├── weather.py
│   └── integrations/
│       ├── upload_post.py              # 7 ch × 5 platforms
│       ├── stripe_src.py
│       ├── gumroad_src.py
│       ├── adsense_src.py
│       ├── apple_cal.py
│       ├── apple_reminders.py
│       ├── apple_mail.py
│       ├── spotify_ctl.py
│       ├── home_assistant.py
│       └── slack_src.py
│
├── config/
│   ├── config.json                     # API keys, locale, mode rules
│   ├── system_prompt.txt               # personality
│   ├── revenue.json                    # fallback when APIs absent
│   ├── analytics.json
│   ├── schedule.json
│   ├── todos.json
│   └── channels.json
│
├── assets/
│   ├── face-mesh.json                  # generated from your photos
│   ├── reference/                      # YOU drop PC photos here
│   ├── owner_faces/                    # YOU drop photos of yourself
│   └── songs/                          # papis_home.mp3 lives here
│
└── scripts/
    ├── setup.sh                        # one-shot installer
    └── run.sh                          # npm start
```

## Quick start

```bash
cd penelope
./scripts/setup.sh
# Drop Penelope photos in assets/reference/
python python/extract_face_mesh.py assets/reference/*.jpg
# Drop papis_home.mp3 in assets/songs/
# (optional) drop YOUR photos in assets/owner_faces/
./scripts/run.sh
```

Then say **"Papi's home."**

## Detailed setup

### 1. Prerequisites (macOS only)

```bash
brew install node@20 python@3.11 portaudio ffmpeg cmake
brew install anthropic/claude/claude
claude login              # uses your Claude Max plan, no API costs
claude --version          # verify
```

### 2. Install Penelope

```bash
cd penelope
./scripts/setup.sh
```

This script:
- runs `npm install`
- creates `.venv` and installs Python deps
- vendors `three.module.js` into `renderer/vendor/`
- creates the `assets/reference`, `assets/owner_faces`, `assets/songs` dirs

### 3. macOS permissions

System Settings → Privacy & Security → enable for **Terminal** (or the
packaged Penelope.app):

- **Microphone** (always-on listening)
- **Camera** (face recognition + presence)
- **Calendars**
- **Reminders**
- **Automation → Mail, Spotify** (for AppleScript control)

### 4. (Optional) Porcupine hotword key

Without one, Whisper does the hotword via 2-sec polling — works fine but
uses more CPU. To upgrade:

1. Free key at https://console.picovoice.ai
2. Generate a `"Papi's home"` custom keyword for macOS
3. Save the `.ppn` as `assets/papis_home_mac.ppn`
4. Paste the access key into `config/config.json` → `picovoice_access_key`

## Face geometry

This is what makes the face actually look like Penelope Cruz instead of
a generic anime face.

1. Drop reference photos in `assets/reference/`. **1 photo minimum**;
   3–5 photos at varied angles produces the best 3D depth.

   Specs:
   - 1024px+ on long edge
   - even lighting, no hard shadows
   - neutral expression, mouth closed
   - face fills ≥40% of frame
   - no filters / heavy retouching

   **Shortcut:** if you don't want to gather photos manually, run

   ```bash
   ./scripts/fetch_reference.sh
   ```

   to auto-download her canonical Wikipedia photo (CC-BY-SA). One photo
   already produces a recognisable mesh; you can add 2–4 more from a
   quick Google for better depth.

2. Extract her actual 3D facial geometry:

   ```bash
   python python/extract_face_mesh.py assets/reference/*
   ```

   This runs MediaPipe FaceMesh (Google's 468-point face model) over
   every photo and averages the results into `assets/face-mesh.json`.

3. The renderer loads `face-mesh.json` at startup and uses HER 3D
   landmarks as the anchor cloud for the particle face. Skull, jawline,
   lips, eye rings, brows, cheeks are all classified by landmark index
   and reactivity flows through her actual geometry.

**Personal use only.** The extracted landmarks should not be redistributed.

## Configuring data

| File | Purpose | When used |
| --- | --- | --- |
| `config/config.json` | API keys, locale, voice, mode rules | always |
| `config/system_prompt.txt` | Penelope's persona | every Claude call |
| `config/revenue.json` | Fallback revenue numbers | if Stripe/Gumroad/AdSense keys empty |
| `config/analytics.json` | Fallback analytics | if upload-post key empty |
| `config/schedule.json` | Manual calendar fallback | if Apple Calendar permission denied |
| `config/todos.json` | Manual todo list | always shown in side panel |
| `config/channels.json` | Your 7 channels | wizard fills, integrations reference |

Edit any JSON and run `window.penelopeDev.reloadData()` in devtools, or
restart.

## Customizing personality

`config/system_prompt.txt` is the persona. The default makes her:
- adaptive across **warm / flirty / professional** based on context
  (time of day, calendar keywords, whether someone else is in frame)
- English primary with Spanish endearments
- spoken-friendly (no markdown, brief by default)
- aware of Dylan/Papi

Mode hints fed each turn: `mode: warm | flirty | professional`. You can
also say:
- "Penelope, business mode" → professional
- "Penelope, flirt mode" → flirty
- "Penelope, normal mode" → warm
- "Sleep Penelope" / "Good night Penelope" → hide window, back to
  hotword-only standby

## Capabilities

She has Claude Code's full tool belt:

| What | How |
| --- | --- |
| Read / edit any local file | `claude` agent with Read/Write/Edit |
| Run shell | `claude` agent with Bash |
| Fetch web pages | `claude` agent with WebFetch |
| Control Spotify | AppleScript via `integrations/spotify_ctl.py` |
| Control Home Assistant | REST API via `integrations/home_assistant.py` |
| Read/draft Apple Mail | AppleScript via `integrations/apple_mail.py` |
| Read/post Slack | Web API via `integrations/slack_src.py` |
| Read Calendar + Reminders | AppleScript |

Add new tools by dropping a module in `python/integrations/` and
importing it from `brain.py`.

## Privacy

- **Transcripts** are written as JSONL to
  `~/Library/Application Support/Penelope/transcripts.jsonl`
  encrypted with **Fernet (AES-128-CBC + HMAC-SHA256)**. The key lives
  in **macOS Keychain** under service "Penelope" / account
  "transcript-key" and is auto-generated on first run.
- **Audio recordings**: never saved to disk. PCM buffers exist only in
  memory while VAD is collecting an utterance.
- **Webcam frames**: never saved to disk. Used in-memory for face
  recognition only.
- **Quiet hours**: respects macOS Focus / DND for proactive alerts. The
  voice/chime is silenced but the visual pulse still shows.
- **Private mode**: when face recognition confirms you're alone and no
  other face has been seen recently, Penelope unlocks unrestricted
  language. With anyone else in frame she stays professional.

## Packaging

```bash
npm run dist
```

Produces `dist/Penelope.dmg` via electron-builder. Bundles the Python
venv inside the app under `Resources/python_venv`. Code-sign with your
Developer ID for distribution.

## Troubleshooting

| Symptom | Fix |
| --- | --- |
| Face is generic, not Penelope | You haven't run `extract_face_mesh.py` yet. Drop her photos in `assets/reference/` and run it. |
| Black screen, no particles | Open devtools (⌘⌥I). WebGL needs macOS 12.3+. |
| `claude: command not found` | `brew install anthropic/claude/claude && claude login` |
| Hotword never triggers | Check mic permission. Lower VAD aggressiveness in `vad_listener.py` from 2 → 1. |
| Reminders/Calendar empty | Grant Apple-events automation permission in System Settings. |
| upload-post returns empty | Verify API key in `config.json` and that nicknames match your dashboard. |
| Song doesn't play | Verify `assets/songs/papis_home.mp3` exists and is a valid mp3. |
| Webcam off / no face_seen events | System Settings → Privacy → Camera → enable. Set `assets/owner_faces/` if face detection should be identity-aware. |
| TTS sounds wrong/robotic | Audition voices via devtools: `await window.penelope.call('ask', {text: 'test'})` after editing `tts_voice` in config. |

---

Built for Papi. 💙
