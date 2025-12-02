# Synthia Roadmap

This document outlines the planned features and direction for Synthia. We welcome community input and contributions!

---

## Current State (v0.1 - Alpha)

**What's Working:**
- Voice dictation (speech-to-text typed at cursor)
- Voice assistant with local LLM (Qwen 2.5)
- App launching, volume control, system commands
- Local TTS with Piper voices
- GPU-accelerated Whisper transcription
- Claude Code integration (voice responses)
- Telegram remote control (Dev Mode)
- Quick Mode (local assistant) / Dev Mode (AI coding assistant)

---

## Phase 1: Core Improvements (v0.2)

### CPU Support
- [ ] Auto-detect GPU availability
- [ ] Fallback to CPU inference for Whisper
- [ ] CPU-optimized model recommendations
- [ ] Performance benchmarks for different hardware

### Enhanced Commands
- [ ] Calendar integration (Google Calendar, Outlook)
- [ ] Email commands ("Read my latest emails", "Send email to...")
- [ ] Music control (Spotify, local players)
- [ ] Smart home integration (Home Assistant)
- [x] Web search and summarization (Tavily integration)
- [ ] Note-taking and reminders
- [ ] File operations ("Find files named...", "Open recent documents")

### Improved Dev Mode
- [ ] Easy terminal session selection for remote control
- [ ] Support for multiple AI coding platforms:
  - [ ] Claude Code
  - [ ] GitHub Copilot
  - [ ] Google Gemini
  - [ ] OpenAI Codex
  - [ ] Cursor
- [ ] Session history and replay
- [ ] Plan approval workflow (send plan, wait for approval, execute)

---

## Phase 2: Cross-Platform (v0.3)

### macOS Support
- [ ] CoreAudio integration
- [ ] Native hotkey handling
- [ ] macOS notifications
- [ ] Menu bar indicator
- [ ] Homebrew installation

### Windows Support
- [ ] Windows Audio API integration
- [ ] System tray indicator
- [ ] Native hotkey handling (no X11)
- [ ] Windows notifications
- [ ] MSI/winget installer

### Linux Improvements
- [x] Wayland support (wtype for input, clipboard with wl-copy/wl-paste)
- [ ] PipeWire audio support
- [ ] Flatpak/Snap packaging
- [ ] AppImage distribution

---

## Phase 3: Native GUI (v0.4)

### Rust GUI Application
Building a lightweight, fast GUI in Rust using egui or iced:

- [ ] Floating bar interface
  - Appears on hotkey press
  - Shows listening/processing state
  - Minimal, non-intrusive design
- [ ] Voice history panel
  - Recent transcriptions
  - Copy to clipboard
  - Re-send to assistant
- [ ] Settings panel
  - Hotkey configuration
  - Voice selection
  - Mode switching (Quick/Dev)
  - Model selection
- [ ] System tray integration
  - Quick access menu
  - Status indicator
  - Enable/disable modes

### GUI Features
- [ ] Real-time waveform visualization
- [ ] Transcription confidence indicator
- [ ] Dark/light theme support
- [ ] Custom accent colors
- [ ] Compact/expanded view modes

---

## Phase 4: Mobile Apps (v0.5)

### Android App
Replacing Telegram bot with native experience:

- [ ] Native Android app (Kotlin/Jetpack Compose)
- [ ] Voice recording and streaming
- [ ] Push notifications for responses
- [ ] Offline transcription (on-device Whisper)
- [ ] Widget for quick access
- [ ] Wear OS companion app

### iOS App
- [ ] Native iOS app (Swift/SwiftUI)
- [ ] Siri Shortcuts integration
- [ ] Apple Watch companion app
- [ ] iCloud sync for settings

### Mobile Features
- [ ] Remote PC control (like current Telegram)
- [ ] View Claude Code responses
- [ ] Approve/reject plans remotely
- [ ] Screenshot viewing
- [ ] System status monitoring

---

## Phase 5: Advanced Features (v1.0)

### Voice & Audio
- [ ] Custom wake word ("Hey Synthia")
- [ ] Speaker diarization (multi-person transcription)
- [ ] Voice cloning for TTS
- [ ] Noise cancellation improvements
- [ ] Multi-language support

### Intelligence
- [ ] Conversation memory (remember context)
- [ ] User preferences learning
- [ ] Custom command creation (no code)
- [ ] Plugin/extension system
- [ ] Workflow automation (chains of commands)

### Integration
- [ ] Browser extension
- [ ] VS Code extension
- [ ] JetBrains plugin
- [ ] Obsidian plugin
- [ ] Raycast extension (macOS)

---

## Community Wishlist

Have an idea? Open an issue with the `enhancement` label or add it here via PR:

- [ ] *Your feature here*

---

## Contributing to the Roadmap

We'd love your input! Here's how to contribute:

1. **Vote on features** - Add a thumbs up to issues you want prioritized
2. **Propose features** - Open an issue describing your idea
3. **Discuss direction** - Join discussions on implementation approaches
4. **Build features** - Pick an item and submit a PR

See [CONTRIBUTING.md](CONTRIBUTING.md) for development setup and guidelines.

---

## Version History

| Version | Status | Focus |
|---------|--------|-------|
| v0.1 | Current | Core functionality, Linux support |
| v0.2 | Planned | CPU support, enhanced commands |
| v0.3 | Planned | Cross-platform (macOS, Windows) |
| v0.4 | Planned | Native Rust GUI |
| v0.5 | Planned | Mobile apps |
| v1.0 | Planned | Advanced features, stability |
