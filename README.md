# Synthia

**Talk to your code. From anywhere.**

Free open-source voice assistant for Linux. Local speech-to-text, hands-free coding with Claude Code, and remote control via Telegram. Your data stays home — even when you can't.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![Linux](https://img.shields.io/badge/platform-Linux-blue.svg)](https://www.linux.org/)

🌐 **Website**: [synthia-ai.com](https://synthia-ai.com)

---

## Why Synthia?

Your voice never leaves your machine. No cloud. No creepy. No "we updated our privacy policy" emails.

- **100% Local** — Whisper runs on your hardware. No servers. No logs. Pinky promise.
- **Free Forever** — MIT licensed. No paywalls. No "premium tier" upsell.
- **Claude Code Integration** — Voice-control your AI coding sessions. Ship features from the couch.

---

## Three Modes, Infinite Possibilities

### ⚡ Quick Mode — Your Desktop Butler
> **Hotkey: Right Alt (hold)**

Instant responses. No internet required. No excuses.

- "Open Chrome" "Play Spotify" "Lock screen" — done.
- Control volume, grab screenshots, launch anything
- Works offline. Like, actually offline.

### 💻 Dev Mode — Talk to Your Code
> **Hotkey: Right Ctrl (hold)**

Speak commands. Claude executes. You sip coffee.

- Full voice control of Claude Code sessions
- Claude talks back (in a good way)
- Perfect for when typing feels like effort

### 📱 Remote Mode — Code From the Couch
> **Enable: Say "Remote mode" or type `/remote`**

Control Claude Code from your phone via Telegram.

- Send voice notes. Get code back. Magic.
- Approve plans before anything runs (you're still the boss)
- Ship features from the beach. We won't judge.

---

## Quick Start

```bash
# Grab the goods
git clone https://github.com/markmiddo/synthia.git
cd synthia

# Let it cook
./install.sh

# Wake her up
./run.sh
```

Hold **Right Alt**, say something, and watch the magic happen.

---

## The Tech Stack

Synthia is built on best-in-class open source AI:

| Component | Technology | Why It's Great |
|-----------|------------|----------------|
| Speech Recognition | [Faster-Whisper](https://github.com/guillaumekln/faster-whisper) | OpenAI's Whisper, but 4x faster |
| AI Brain | [Ollama](https://ollama.ai) + Qwen 2.5 | Local LLM, no API keys needed |
| Voice Output | [Piper](https://github.com/rhasspy/piper) | Sounds like a human, not a GPS from 2008 |

**NVIDIA GPU?** Whisper goes brrr. **No GPU?** Still works. Just vibes a little slower.

---

## Hotkeys

| Key | Mode | What It Does |
|-----|------|--------------|
| **Right Alt** (hold) | Quick Mode | Voice assistant — runs commands, launches apps |
| **Right Ctrl** (hold) | Dev Mode | Voice to Claude Code — hands-free coding |
| **Esc** | — | Quit Synthia |

---

## Claude Code Integration

Make Claude Code talk back to you. Add to `~/.claude/settings.json`:

```json
{
  "hooks": {
    "Stop": [{
      "hooks": [{
        "type": "command",
        "command": "/path/to/synthia/venv/bin/python /path/to/synthia/src/synthia/hooks/stop-hook.py",
        "timeout": 30
      }]
    }]
  }
}
```

Now every Claude response is spoken aloud — or sent to your phone in Remote Mode.

---

## Configuration

```bash
mkdir -p ~/.config/synthia
cp config.example.yaml ~/.config/synthia/config.yaml
```

Edit `~/.config/synthia/config.yaml`:

```yaml
# Use local AI (recommended)
use_local_stt: true
use_local_llm: true
use_local_tts: true

# Model settings
local_stt_model: "tiny"  # tiny, base, small, medium, large
local_llm_model: "qwen2.5:1.5b-instruct-q4_0"
local_tts_voice: "~/.local/share/piper-voices/en_US-amy-medium.onnx"
```

---

## Voice Options

Open `config.yaml` and swap in a different Piper voice. Amy's friendly. Ryan's chill. Lessac sounds like your cool coworker. Pick your fighter.

Download from [Piper Voices](https://huggingface.co/rhasspy/piper-voices):

| Voice | Style |
|-------|-------|
| `en_US-amy-medium` | Female, clear |
| `en_US-ryan-high` | Male, natural |
| `en_US-lessac-high` | Female, expressive |
| `en_GB-alba-medium` | British female |

---

## Requirements

- **OS**: Linux (macOS/Windows coming in v0.3)
- **Python**: 3.10+
- **RAM**: 4GB minimum and a pulse. 8GB recommended.
- **GPU**: Optional (NVIDIA for that buttery-smooth transcription)
- **Disk**: ~2GB for models

---

## Roadmap

We're just getting started:

- **v0.2** — CPU support improvements, enhanced voice commands
- **v0.3** — macOS and Windows support
- **v0.4** — Native GUI (Rust-powered floating bar)
- **v0.5** — Mobile apps (bye-bye Telegram dependency)
- **v1.0** — Plugin system, multi-AI support

See the full [ROADMAP.md](ROADMAP.md) for details.

---

## Contributing

Bug reports, feature requests, and questionable memes — we've got it all.

Whether you want to:
- Report bugs
- Suggest features
- Write code
- Improve docs

Check out [CONTRIBUTING.md](CONTRIBUTING.md) to get started.

---

## FAQ

**Is it really free?**
Yep. Free as in beer, free as in speech, free as in "wait, what's the catch?" There is no catch.

**Does my voice leave my computer?**
Absolutely not. Your voice stays on your machine like it's under house arrest.

**Does it work without a GPU?**
Totally. Like a Honda Civic. Reliable. Gets the job done. Won't win races but never lets you down.

---

## License

MIT — Fork it. Break it. Fix it. Make it weird. It's yours now.

---

## Support the Project

Synthia runs on open source spirit and actual coffee. If it saves you time, consider:

- ⭐ **Starring on GitHub** — free and helps others find us
- ☕ **Buying us a coffee** — [synthia-ai.com/#donate](https://synthia-ai.com/#donate)

---

**Built for developers who value privacy and hate typing (sometimes).**
