# Synthia - AI Assistant Context

## Project Overview
Synthia is a voice dictation + AI assistant for Linux. It enables hands-free control of your desktop and integrates with Claude Code for spoken AI responses.

## Key Features
- **Right Ctrl** - Dictation mode (speech → text typed at cursor)
- **Right Alt** - Voice assistant (AI-powered commands)
- **Claude Code Hook** - Claude speaks responses aloud via Stop hook

## Architecture

### Current Stack (Cloud-based)
1. **Google Cloud STT** - Speech-to-text transcription
2. **Claude Haiku API** - AI brain for voice assistant
3. **Google Cloud TTS** - Text-to-speech (streaming by sentence)

### Planned Local Stack
1. **Whisper.cpp (small)** - Local speech-to-text
2. **Ollama + Qwen 2.5 7B** - Local LLM
3. **Piper TTS** - Local text-to-speech

See `docs/LINUXVOICE-HANDOVER.md` in eventflo repo for full migration plan.

## File Structure
```
├── main.py              # Main app (Right Alt assistant)
├── voice-daemon.py      # Dictation daemon (Right Ctrl for Claude Code)
├── assistant.py         # Claude/Ollama API integration
├── transcribe.py        # Google STT / Whisper.cpp
├── tts.py               # Google TTS / Piper (streaming)
├── commands.py          # Action execution (apps, volume, etc.)
├── audio.py             # Recording with sample rate conversion
├── output.py            # xdotool text injection
├── config.py            # Configuration loader
├── sounds.py            # Sound effects
├── notifications.py     # Desktop notifications
├── indicator.py         # System tray (disabled)
├── wakeword.py          # Wake word detection (disabled)
└── claude-hooks/
    └── stop-hook.py     # Makes Claude Code speak responses
```

## Configuration
- `~/.config/linuxvoice/config.yaml` - User settings
- `~/.config/linuxvoice/google-credentials.json` - Google Cloud creds
- `~/.config/linuxvoice/anthropic-key.txt` - Anthropic API key

## Autostart
- `~/.config/autostart/linuxvoice.desktop` - Main app (5sec delay)
- `~/.config/autostart/linuxvoice-daemon.desktop` - Voice daemon

## Flatpak Apps Supported
Wezterm, Zed, Chrome, Zen, Notes, Krita, Telegram, WhatsApp (ZapZap)

## Key Design Decisions

### Audio Handling
- USB mic records at 44100Hz, Google STT needs 16000Hz
- Solution: Record at native rate, resample with scipy

### TTS Streaming
- Long responses split by sentence
- Each sentence generated and played immediately
- Reduces perceived latency

### Error Handling
- Mic unavailable errors caught gracefully (doesn't crash)
- Filler words (uh, um, ah) stripped from transcription

### Config Flags for Local Migration
```yaml
use_local_stt: false   # Whisper.cpp
use_local_llm: false   # Ollama/Qwen
use_local_tts: false   # Piper
```

## Development Notes

### Running Locally
```bash
cd /home/markmiddo/Misc/linuxvoice
source venv/bin/activate
python main.py          # Voice assistant
python voice-daemon.py  # Claude Code dictation
```

### Restarting After Changes
```bash
pkill -f "python.*main.py"
pkill -f "python.*voice-daemon"
# Then start again
```

### Checking Logs
```bash
tail -f /tmp/linuxvoice.log      # Main app
tail -f /tmp/voice-daemon.log    # Daemon
tail -f /tmp/stop-hook-debug.log # Claude hook
```

## Next Steps
1. Install Ollama + Qwen 2.5 7B
2. Install Whisper.cpp + small model
3. Install Piper TTS + amy voice
4. Add config flags and local implementations
5. Test and compare latency

Target: Under 600ms response time, fully offline.
