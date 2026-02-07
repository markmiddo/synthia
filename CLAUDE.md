# Synthia Development Guide

## Voice Mode Communication

The user has voice input/output enabled. Keep responses conversational and speakable.

**Avoid in responses:**
- Long terminal commands
- Hex color codes or technical values
- File paths
- Code snippets
- Technical jargon that sounds awkward when spoken

**Instead:**
- Write code directly to files
- Summarize changes conversationally
- Keep explanations natural and brief
- Save technical details for file content, not spoken output

## Project Overview

Synthia is a voice assistant for Linux with:
- Speech-to-text (Google Cloud or local Whisper)
- Text-to-speech (Google Cloud or local Piper)
- AI assistant (Claude API or local Ollama)
- Hotkey activation (Right Ctrl for dictation, Right Alt for assistant)
- Telegram remote access
- TUI dashboard (Textual)
- Clipboard monitoring
- Memory system integration

## Key Directories

- `src/synthia/` - Python core application
- `src/synthia/remote/` - Telegram bot, inbox, remote access
- `src/synthia/hooks/` - Claude Code integration hooks
- `gui/` - Tauri desktop GUI (Rust + React)
- `tests/` - pytest test suite (298 tests)
- `docs/` - Documentation and PRDs

## Brand

Always write "Synthia" with capital S. Website is synthia-ai.com.

---

## Git Workflow

### Branches

| Branch | Purpose |
|--------|---------|
| `main` | Protected production branch |
| `development` | Active development branch |

### Branch Protection (main)

- Pull requests required (1 approving review)
- CI must pass: `lint`, `typecheck`, `test (3.12)`
- No force pushes, no branch deletion
- Owner can bypass in emergencies

### Development Flow

1. Work on `development` branch (or feature branches off it)
2. Run quality gates locally before committing
3. Push to `development`
4. Create PR from `development` to `main`
5. CI runs automatically on the PR
6. Merge after CI passes

### Commit Convention

Use conventional commits: `type: description`

Types: `feat`, `fix`, `refactor`, `docs`, `style`, `test`, `chore`, `ci`

---

## Quality Gates

Run all three before committing:

```bash
source venv/bin/activate
black --check src/ tests/       # Formatting
isort --check src/ tests/       # Import ordering
mypy src/synthia/ --ignore-missing-imports  # Type checking
pytest tests/ --tb=short -q     # Tests (298 tests)
```

## Running Tests

```bash
source venv/bin/activate
pytest tests/ -v                # Verbose output
pytest tests/ --cov=synthia     # With coverage
pytest tests/test_config.py -v  # Single module
```

## Installation

```bash
pip install -e ".[all]"     # Full install (all optional deps)
pip install -e ".[dev]"     # Development tools (pytest, black, mypy, etc.)
pip install -e "."          # Core only (no optional features)
```

### Dependency Groups

| Extra | Packages | Required For |
|-------|----------|--------------|
| `local` | faster-whisper, piper-tts, evdev | Local STT/TTS, evdev hotkeys |
| `cloud` | google-cloud-speech/texttospeech, anthropic | Cloud STT/TTS, Claude API |
| `remote` | python-telegram-bot | Telegram remote access |
| `search` | tavily-python | Web search |
| `tui` | textual | TUI dashboard |
| `dev` | pytest, black, isort, mypy, pre-commit | Development |

## Configuration

Config file: `~/.config/synthia/config.yaml`

Config is validated on load with warnings logged for:
- Invalid hotkey names, sample rates, STT models
- Out-of-range values (tts_speed, timeouts)
- Non-boolean flags, invalid URLs
- Unknown keys (catches typos)

Validation never crashes - it warns and uses defaults.

## Running Synthia

```bash
./run.sh            # Start voice assistant
synthia             # Same (if installed)
synthia-dash        # TUI dashboard
```
