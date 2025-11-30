# Synthia

Voice dictation + AI assistant for Linux. Runs fully local or with cloud services.

## Features

- **Right Ctrl** - Dictation mode (speech to text typed at cursor)
- **Right Alt** - Voice assistant (open apps, control volume, run commands)
- **Claude Code integration** - Claude speaks responses aloud
- **Fully local mode** - No cloud required using Whisper, Ollama, and Piper

## Local vs Cloud

Synthia supports both local and cloud-based speech processing:

| Component | Local | Cloud |
|-----------|-------|-------|
| Speech-to-Text | Whisper (faster-whisper) | Google Cloud STT |
| LLM | Ollama (Qwen 2.5) | Claude API |
| Text-to-Speech | Piper | Google Cloud TTS |

Local mode is faster (no network latency) and free. Cloud mode has higher quality voices.

## Requirements

- Python 3.10+
- Linux with X11
- USB microphone

### For Local Mode
- Ollama installed (`curl -fsSL https://ollama.com/install.sh | sh`)
- ~2GB disk space for models

### For Cloud Mode
- Google Cloud account (for STT/TTS)
- Anthropic API key (for assistant)

## Installation

```bash
# Clone
git clone https://github.com/markmiddo/synthia.git
cd synthia

# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Install system dependencies
sudo apt install xdotool portaudio19-dev mpv xclip wmctrl alsa-utils
```

### Local Mode Setup

```bash
# Install Ollama
curl -fsSL https://ollama.com/install.sh | sh

# Pull Qwen model (1.5B is good balance of speed/quality)
ollama pull qwen2.5:1.5b-instruct-q4_0

# Install local TTS dependencies
pip install faster-whisper piper-tts

# Download Piper voice
mkdir -p ~/.local/share/piper-voices
cd ~/.local/share/piper-voices
wget https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/ryan/high/en_US-ryan-high.onnx
wget https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/ryan/high/en_US-ryan-high.onnx.json
```

## Configuration

Create config directory:

```bash
mkdir -p ~/.config/linuxvoice
cp config.example.yaml ~/.config/linuxvoice/config.yaml
```

### Enable Local Mode

Edit `~/.config/linuxvoice/config.yaml`:

```yaml
# Local models (set to true for local, false for cloud)
use_local_stt: true       # Whisper instead of Google STT
use_local_llm: true       # Ollama instead of Claude API
use_local_tts: true       # Piper instead of Google TTS

# Local model settings
local_stt_model: "tiny"   # tiny, base, small, medium, large
local_llm_model: "qwen2.5:1.5b-instruct-q4_0"
local_tts_voice: "~/.local/share/piper-voices/en_US-ryan-high.onnx"
```

### Cloud Mode Setup

```bash
# Add Google Cloud credentials JSON
cp your-google-credentials.json ~/.config/linuxvoice/google-creds.json

# Add Anthropic API key
echo "your-api-key" > ~/.config/linuxvoice/anthropic-key.txt
```

Set in config.yaml:
```yaml
use_local_stt: false
use_local_llm: false
use_local_tts: false
```

## Usage

```bash
source venv/bin/activate
python main.py
```

## Hotkeys

- **Right Ctrl** (hold) - Record voice, transcribe, type at cursor
- **Right Alt** (hold) - Record voice, AI processes, speaks response + executes actions
- **Esc** - Quit

## Voice Commands (Right Alt)

- "Open Chrome" / "Open Telegram" / "Open terminal"
- "Set volume to 50" / "Turn up the volume" / "Mute"
- "What time is it?" / "What's the date?"
- "Take a screenshot"
- "Lock the screen"
- "Maximize this window" / "Close window"

## Claude Code Integration

To have Claude Code speak responses, add a stop hook in `~/.claude/settings.json`:

```json
{
  "hooks": {
    "Stop": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "/path/to/synthia/venv/bin/python /path/to/synthia/claude-hooks/stop-hook.py",
            "timeout": 30
          }
        ]
      }
    ]
  }
}
```

## Piper Voice Options

Download different voices from [Piper Voices](https://huggingface.co/rhasspy/piper-voices):

- `en_US-ryan-high` - Male, natural (recommended)
- `en_US-amy-medium` - Female
- `en_US-lessac-high` - Female, expressive
- `en_GB-alba-medium` - British female

## License

MIT
