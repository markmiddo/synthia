# Synthia

Voice dictation + AI assistant for Linux.

## Features

- **Right Ctrl** - Dictation mode (speech → text typed at cursor)
- **Right Alt** - Voice assistant (open apps, control volume, run commands)
- **Claude Code integration** - Claude speaks responses aloud

## Requirements

- Python 3.10+
- Linux with X11
- USB microphone
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
sudo apt install xdotool portaudio19-dev mpv xclip wmctrl
```

## Configuration

Create config directory and add credentials:

```bash
mkdir -p ~/.config/linuxvoice

# Add Google Cloud credentials JSON
cp your-google-credentials.json ~/.config/linuxvoice/google-credentials.json

# Add Anthropic API key
echo "your-api-key" > ~/.config/linuxvoice/anthropic-key.txt

# Copy default config
cp config.yaml.example ~/.config/linuxvoice/config.yaml
```

## Usage

```bash
# Activate venv
source venv/bin/activate

# Run main app (voice assistant)
python main.py

# Run voice daemon (for Claude Code dictation)
python voice-daemon.py
```

## Hotkeys

- **Right Ctrl** (hold) - Record voice → transcribe → type at cursor
- **Right Alt** (hold) - Record voice → AI processes → speaks response + executes actions

## Voice Commands (Right Alt)

- "Open Chrome" / "Open Slack" / "Open terminal"
- "Set volume to 50" / "Turn up the volume" / "Mute"
- "What time is it?" / "What's the date?"
- "Take a screenshot"
- "Lock the screen"

## License

MIT
