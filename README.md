# Synthia

**Your AI-powered voice assistant that actually respects your privacy.**

Talk to your computer. Launch apps. Control your dev environment. All running locally on your machine - no cloud required, no data leaving your system, no monthly fees.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)

---

## Why Synthia?

**Tired of cloud assistants listening to everything?** Synthia runs entirely on your hardware. Your voice never leaves your machine.

**Want an assistant that works with your workflow?** Synthia integrates directly with Claude Code, letting you control AI coding sessions with your voice - even remotely from your phone.

**Hate subscription fatigue?** Synthia is free, open source, and always will be.

---

## What Can It Do?

### Quick Mode - Your Local Assistant
Hold a key, speak, get things done:

- **"Open Chrome"** - Launch any application
- **"Set volume to 50"** - Control system audio
- **"What time is it?"** - Quick information
- **"Take a screenshot"** - Capture your screen
- **"Lock the screen"** - Security in one command

### Dev Mode - Remote AI Coding Control
Connect Synthia to Claude Code (or other AI coding tools) and:

- **Voice-control your coding sessions** - Speak commands, Claude executes
- **Work remotely via your phone** - Send voice notes, get responses back
- **Plan approval workflow** - Review AI plans before execution
- **Never touch the keyboard** - Perfect for when you're away from your desk

---

## The Tech Stack

Synthia is built on best-in-class open source AI:

| Component | Technology | Why It's Great |
|-----------|------------|----------------|
| Speech Recognition | [Faster-Whisper](https://github.com/guillaumekln/faster-whisper) | OpenAI's Whisper, but 4x faster |
| AI Brain | [Ollama](https://ollama.ai) + Qwen 2.5 | Local LLM, no API keys needed |
| Voice Output | [Piper](https://github.com/rhasspy/piper) | Natural-sounding, runs locally |

**GPU acceleration supported** - NVIDIA GPUs make everything snappier, but CPU-only works too.

---

## Quick Start

```bash
# Clone it
git clone https://github.com/markmiddo/synthia.git
cd synthia

# Set it up
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Install system dependencies
sudo apt install xdotool portaudio19-dev mpv xclip wmctrl alsa-utils

# Get the AI brain
curl -fsSL https://ollama.com/install.sh | sh
ollama pull qwen2.5:1.5b-instruct-q4_0

# Run it
python main.py
```

That's it. Hold **Right Alt**, speak, and watch the magic happen.

---

## Hotkeys

| Key | Mode | What It Does |
|-----|------|--------------|
| **Right Alt** (hold) | Quick Mode | Voice assistant - runs commands, launches apps |
| **Right Ctrl** (hold) | Dictation | Speech-to-text - types what you say |
| **Esc** | - | Quit Synthia |

---

## Remote Control (Dev Mode)

Control your AI coding sessions from anywhere:

1. **Enable Dev Mode** via Telegram bot
2. **Send voice notes or text** from your phone
3. **Synthia sends it to Claude Code** on your PC
4. **Get responses back** on your phone

Perfect for:
- Monitoring long-running AI tasks
- Quick fixes while away from your desk
- Approving AI plans before execution

---

## Claude Code Integration

Make Claude Code talk back to you:

```json
// Add to ~/.claude/settings.json
{
  "hooks": {
    "Stop": [{
      "hooks": [{
        "type": "command",
        "command": "/path/to/synthia/venv/bin/python /path/to/synthia/claude-hooks/stop-hook.py",
        "timeout": 30
      }]
    }]
  }
}
```

Now every Claude response is spoken aloud - or sent to your phone in Dev Mode.

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

Customize how Synthia sounds. Download from [Piper Voices](https://huggingface.co/rhasspy/piper-voices):

| Voice | Style |
|-------|-------|
| `en_US-amy-medium` | Female, clear |
| `en_US-ryan-high` | Male, natural |
| `en_US-lessac-high` | Female, expressive |
| `en_GB-alba-medium` | British female |

---

## Roadmap

We're just getting started. Here's what's coming:

- **Cross-platform** - macOS and Windows support
- **Native GUI** - Beautiful floating bar built in Rust
- **Mobile apps** - Android and iOS (replacing Telegram)
- **More AI platforms** - Gemini, Codex, Copilot support
- **Plugin system** - Extend Synthia with custom commands

See the full [ROADMAP.md](ROADMAP.md) for details.

---

## Contributing

We'd love your help! Whether it's:

- Reporting bugs
- Suggesting features
- Writing code
- Improving docs

Check out [CONTRIBUTING.md](CONTRIBUTING.md) to get started.

---

## Requirements

- **OS**: Linux (macOS/Windows coming soon)
- **Python**: 3.10+
- **RAM**: 4GB minimum, 8GB recommended
- **GPU**: Optional (NVIDIA for acceleration)
- **Disk**: ~2GB for models

---

## License

MIT - Use it however you want.

---

## Star History

If Synthia helps you, consider giving it a star! It helps others discover the project.

---

**Built with love for developers who value privacy and productivity.**
