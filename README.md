# SYNTHIA

**Talk to your code. Manage your workflow. From anywhere.**

Free open-source Claude Code companion for Linux. Voice control, persistent memory, and a full configuration dashboard — all in one toolkit. Your data stays home.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![Rust](https://img.shields.io/badge/rust-1.70+-orange.svg)](https://www.rust-lang.org/)
[![Linux](https://img.shields.io/badge/platform-Linux-blue.svg)](https://www.linux.org/)

---

## Why SYNTHIA?

Your voice never leaves your machine. Your memories stay organized. Your Claude Code config stays in check.

- **100% Local** — Whisper runs on your hardware. No servers. No logs. Pinky promise.
- **Free Forever** — MIT licensed. No paywalls. No "premium tier" upsell.
- **Claude Code Companion** — Voice control, persistent memory, and a TUI dashboard for agents, commands, hooks, and settings.
- **Memory Layer** — Store bugs, patterns, architecture decisions, and gotchas. Never re-learn the same lesson twice.

---

## Three Modes, Infinite Possibilities

### Quick Mode — Your Desktop Butler
> **Hotkey: Right Alt (hold)**

Instant responses. No internet required. No excuses.

- "Open Chrome" "Play Spotify" "Lock screen" — done.
- Control volume, grab screenshots, launch anything
- Works offline. Like, actually offline.

### Dev Mode — Talk to Your Code
> **Hotkey: Right Ctrl (hold)**

Speak commands. Claude executes. You sip coffee.

- Full voice control of Claude Code sessions
- Claude talks back (in a good way)
- LLM Polish cleans up your transcriptions automatically
- Perfect for when typing feels like effort

### Remote Mode — Code From the Couch
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

| Component | Technology | Why It's Great |
|-----------|------------|----------------|
| Speech Recognition | [Faster-Whisper](https://github.com/guillaumekln/faster-whisper) | OpenAI's Whisper, but 4x faster |
| AI Brain | [Ollama](https://ollama.ai) + Qwen 2.5 | Local LLM, no API keys needed |
| Voice Output | [Piper](https://github.com/rhasspy/piper) | Sounds like a human, not a GPS from 2008 |
| Dashboard TUI | [Textual](https://textual.textualize.io) | Beautiful terminal UI, keyboard-first |
| Desktop GUI | [Tauri](https://tauri.app) + Rust | Native performance, tiny footprint |
| Frontend | React + TypeScript | Modern, type-safe UI |
| Web Search | [Tavily](https://tavily.com) | AI-optimized search when you need the web |

**NVIDIA GPU?** Whisper goes brrr. **No GPU?** Still works. Just vibes a little slower.

---

## Desktop GUI

SYNTHIA includes a native desktop application built with Tauri (Rust + React):

- **System tray integration** — Lives in your taskbar, always accessible
- **One-click start/stop** — No terminal required
- **Remote mode toggle** — Enable Telegram control instantly
- **Voice history** — Browse, copy, and re-send past transcriptions
- **Clipboard history** — Recent clipboard items with one-click restore
- **Usage stats** — Claude API usage tracking (today/this week)
- **Hotkey editor** — Customize dictation and assistant keys live
- **Notes browser** — Markdown editor with preview, folder navigation
- **Worktree manager** — Track git worktrees with progress bars and session linking
- **Task kanban** — Drag-and-drop task board (To Do, In Progress, Done)
- **Config editor** — Manage Synthia settings, agents, commands, hooks, and plugins

Build the GUI:
```bash
cd gui
npm install
npm run tauri build
```

---

## Hotkeys

| Key | Mode | What It Does |
|-----|------|--------------|
| **Right Alt** (hold) | Quick Mode | Voice assistant — runs commands, launches apps |
| **Right Ctrl** (hold) | Dev Mode | Voice to Claude Code — hands-free coding |
| **Esc** | — | Quit SYNTHIA |

Hotkeys work on both X11 (pynput) and Wayland (evdev). Customizable in `config.yaml` or the GUI hotkey editor.

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

## Synthia Dashboard

A full TUI for managing your entire Claude Code setup. One command, everything at your fingertips.

```bash
synthia-dash
```

### What You Can Manage

| # | Section | What It Does |
|---|---------|--------------|
| 1 | **Worktrees** | View git worktrees, track progress, resume Claude sessions, link to GitHub issues |
| 2 | **Memory** | Browse, filter, edit, and delete memory entries by category |
| 3 | **Agents** | View and edit your custom agents (model, color, prompt) |
| 4 | **Commands** | Manage slash commands with built-in editor |
| 5 | **Plugins** | Toggle plugins on/off with spacebar |
| 6 | **Hooks** | View configured hooks (UserPromptSubmit, Stop, etc.) |
| 7 | **Settings** | Quick access to Claude Code settings |

### Keyboard Navigation

- `1-7` — Jump to section
- `w` — Worktrees
- `r` — Refresh
- `e` — Edit selected item
- `n` — New item
- `d` — Delete (with confirmation)
- `g` — Open GitHub issue (worktrees)
- `o` — Open terminal at worktree
- `c` — Resume Claude session (worktrees)
- `Tab` — Cycle memory filters
- `?` — Help overlay
- `q` — Quit

---

## Worktrees Management

Track your git worktrees across repos with progress bars, issue linking, and Claude session integration.

### Setup

Create `~/.config/synthia/worktrees.yaml`:

```yaml
repos:
  - /home/user/dev/my-project
  - /home/user/dev/another-repo
```

### Features

- **Auto-discovery** — Scans configured repos for worktrees
- **Issue linking** — Extracts issue numbers from branch names (`feature/295-dark-mode`, `fix/295-auth-bug`)
- **Session tracking** — Finds matching Claude Code sessions and loads task progress
- **Progress bars** — Visual completion percentage per worktree
- **Quick actions** — Open terminal, resume Claude session, view on GitHub

---

## Tasks CLI

A lightweight task manager for tracking work across projects.

```bash
# List all tasks
synthia tasks list

# Add a new task
synthia tasks add "Fix login bug" --tags "frontend,auth" --due "2026-02-15"

# Filter by status
synthia tasks list --status in_progress

# Mark done
synthia tasks done "Fix login bug"

# Move to a different status
synthia tasks move "Fix login bug" in_progress

# Delete
synthia tasks delete "Fix login bug"
```

Tasks are stored in `~/.config/synthia/tasks.json` and visible in both the TUI dashboard and the GUI kanban board.

---

## Notes Browser

A markdown editor built into the GUI. Browse, create, edit, and preview `.md` files.

- Full markdown preview with react-markdown
- Folder navigation with breadcrumbs
- Create, rename, and delete notes

Set a custom notes directory:

```bash
export SYNTHIA_NOTES_PATH="/path/to/your/notes"
```

Default: `~/.config/synthia/notes/`

---

## Clipboard History

Background clipboard monitoring with secure storage.

- **Wayland** — Uses `wl-paste --watch` for event-based monitoring
- **X11** — Polling-based with `xclip`
- Stores up to 5 items (configurable) with deduplication
- Secure file permissions (`0o600`) — passwords and tokens are handled safely

Config options:

```yaml
clipboard_history_enabled: true
clipboard_history_max_items: 5
```

---

## LLM Polish

Whisper is great but not perfect. LLM Polish uses a local Ollama model to fix speech recognition mistakes — homophones, technical terms, proper nouns — without changing meaning.

- Runs after every transcription (dev mode and quick mode)
- Timeout-based fail-safe (defaults to original text if slow)
- Completely local — no cloud APIs

Config options:

```yaml
use_llm_polish: true
llm_polish_model: "qwen2.5:7b-instruct-q4_0"
llm_polish_timeout: 3.0
```

---

## Web Search

Voice-activated web search powered by Tavily. Just say "Search the web for..." and get concise answers read aloud.

```yaml
tavily_api_key: "tvly-your-key-here"  # Get from tavily.com
```

---

## Remote Mode

Control SYNTHIA from your phone via Telegram. Send voice notes, approve plans, and monitor your system.

### Telegram Bot Commands

| Command | What It Does |
|---------|--------------|
| `/start` | Show help and current mode |
| `/dev` | Switch to Dev Mode (Claude Code) |
| `/quick` | Switch to Quick Mode (local AI) |
| `/status` | System status — uptime, load, memory, services |
| `/disk` | Disk usage |
| `/gpu` | GPU stats (requires nvidia-smi) |
| `/screenshot` | Take and send a screenshot |
| `/clip <text>` | Copy text to your PC clipboard |
| `/getclip` | Get current PC clipboard content |

### Inbox System

Files sent via Telegram are saved to the inbox:

- Voice notes are transcribed and processed
- Photos saved as `.jpg` with timestamps
- Files stored in `~/.local/share/synthia/inbox/files/`
- Metadata tracked in `~/.local/share/synthia/inbox/inbox.json`

### Setup

```yaml
telegram_bot_token: "your-bot-token"    # Get from @BotFather
telegram_allowed_users: [123456789]     # Your Telegram user ID
```

---

## Memory System

SYNTHIA includes a persistent memory system for storing project knowledge, bugs, patterns, and gotchas. Perfect for development workflows where you need quick access to past learnings.

### Memory Categories

| Category | Fields | Use Case |
|----------|--------|----------|
| `bug` | error, cause, fix | Track bug solutions |
| `pattern` | topic, rule, why | Document coding conventions |
| `arch` | decision, why | Record architecture decisions |
| `gotcha` | area, gotcha | Capture project landmines |
| `stack` | tool, note | Tool configuration notes |

### CLI Access

```bash
# Quick recall by tags
synthia memory recall "frontend,react"

# Text search
synthia memory search "MongoDB"

# View statistics
synthia memory stats

# List all tags
synthia memory tags
```

### Voice Commands

- "What do we know about React bugs?" — Searches memory by tags
- "Search memory for MongoDB" — Full-text search

### Auto-Retrieval (Dev Mode)

Enable in `config.yaml`:
```yaml
memory_auto_retrieve: true
```

When enabled, SYNTHIA automatically injects relevant memories into your queries based on detected keywords.

---

## Configuration

```bash
mkdir -p ~/.config/synthia
cp config.example.yaml ~/.config/synthia/config.yaml
```

### Complete Reference

```yaml
# Hotkeys
dictation_key: "Key.ctrl_r"          # Dev Mode hotkey
assistant_key: "Key.alt_r"           # Quick Mode hotkey

# Speech Recognition
language: "en-US"
sample_rate: 16000

# Text-to-Speech
tts_voice: "en-US-Neural2-J"         # Google Cloud voice name
tts_speed: 1.0                       # Speech rate multiplier

# Assistant
assistant_model: "claude-sonnet-4-20250514"
conversation_memory: 10              # Exchange history length
assistant_personality: "..."         # System prompt for Quick Mode

# Credentials
google_credentials: "~/.config/synthia/google-creds.json"
anthropic_api_key: "~/.config/synthia/anthropic-key.txt"

# UI
show_notifications: true
play_sound_on_record: true

# Local Models
use_local_stt: true                  # Whisper instead of Google Cloud
use_local_llm: true                  # Ollama instead of Anthropic
use_local_tts: true                  # Piper instead of Google Cloud
local_stt_model: "tiny"              # tiny, base, small, medium, large
local_llm_model: "qwen2.5:1.5b-instruct-q4_0"
local_tts_voice: "~/.local/share/piper-voices/en_US-amy-medium.onnx"
ollama_url: "http://localhost:11434"

# Telegram Remote Access
telegram_bot_token: ""               # From @BotFather
telegram_allowed_users: []           # Telegram user IDs

# Web Search
tavily_api_key: ""                   # From tavily.com

# LLM Polish
use_llm_polish: true                 # Fix transcription errors
llm_polish_model: "qwen2.5:7b-instruct-q4_0"
llm_polish_timeout: 3.0             # Seconds before fail-safe

# Clipboard Manager
clipboard_history_enabled: true
clipboard_history_max_items: 5

# Memory System
memory_enabled: true
memory_auto_retrieve: false          # Auto-inject context in dev mode
memory_dir: "~/.claude/memory"

# Word Replacements
word_replacements:
  Cynthia: Synthia                   # Fix Whisper misrecognitions
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

## File Locations

| File | Purpose |
|------|---------|
| `~/.config/synthia/config.yaml` | Main configuration |
| `~/.config/synthia/worktrees.yaml` | Repository list for worktree scanning |
| `~/.config/synthia/tasks.json` | Task manager data |
| `~/.config/synthia/notes/` | Notes directory (or `SYNTHIA_NOTES_PATH`) |
| `~/.claude/memory/*.jsonl` | Memory system entries |
| `~/.local/share/synthia/inbox/` | Telegram file inbox |
| `$XDG_RUNTIME_DIR/synthia-clipboard.json` | Clipboard history (runtime) |
| `$XDG_RUNTIME_DIR/synthia-remote-mode` | Remote mode flag (runtime) |

---

## Requirements

- **OS**: Linux (macOS/Windows coming in v0.3)
- **Python**: 3.10+
- **Rust**: 1.70+ (for GUI)
- **RAM**: 4GB minimum and a pulse. 8GB recommended.
- **GPU**: Optional (NVIDIA for that buttery-smooth transcription)
- **Disk**: ~2GB for models

---

## Roadmap

We're just getting started:

- **v0.2** — CPU support improvements, enhanced voice commands
- **v0.3** — macOS and Windows support
- ~~**v0.4** — Native GUI (Rust-powered floating bar)~~ Done!
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

SYNTHIA runs on open source spirit and actual coffee. If it saves you time, consider:

- **Starring on GitHub** — free and helps others find us
- **Buying us a coffee** — [synthia-ai.com/#donate](https://synthia-ai.com/#donate)

---

**Built for developers who value privacy and hate typing (sometimes).**
