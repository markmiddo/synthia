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

Synthia is a voice assistant + dev workstation companion for Linux with:
- Speech-to-text (Google Cloud or local Whisper)
- Text-to-speech (Google Cloud or local Piper)
- AI assistant (Claude API or local Ollama)
- Hotkey activation (Right Ctrl for dictation, Right Alt for assistant)
- Telegram remote access
- TUI dashboard (Textual)
- Tauri desktop GUI (sidebar: agents/worktrees/knowledge/security/voice/memory/github/config)
- Clipboard monitoring
- Memory system integration
- AI Security AI security layer (intercepts risky tool calls from local AI agents)

## Key Directories

- `src/synthia/` - Python core application
- `src/synthia/remote/` - Telegram bot, inbox, remote access
- `src/synthia/hooks/` - Claude Code integration hooks (incl. `security_gate.py`)
- `gui/` - Tauri desktop GUI (Rust + React)
  - `gui/src-tauri/src/lib.rs` - thin orchestrator (~470 lines)
  - `gui/src-tauri/src/commands/*.rs` - IPC handlers grouped by domain (15 modules)
  - `gui/src-tauri/src/error.rs` - typed `AppError` (manual Serialize preserves React wire format)
  - `gui/src-tauri/src/state.rs` - Tauri-managed `AppState`
  - `gui/src-tauri/src/paths.rs` - canonicalize-checked filesystem helpers
  - `gui/src-tauri/src/security.rs` + `egress.rs` - AI Security rules + egress filter
  - `gui/src-tauri/src/yaml_writer.rs` - comment-preserving config writers
- `tests/` - pytest test suite (593 tests)
- `docs/` - Documentation, specs, plans

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

### Python (always)

```bash
source venv/bin/activate
black --check src/ tests/       # Formatting
isort --check src/ tests/       # Import ordering
mypy src/synthia/ --ignore-missing-imports  # Type checking
pytest tests/ --tb=short -q     # Tests (593 tests)
```

### Rust GUI backend (when touching `gui/src-tauri/`)

```bash
cd gui/src-tauri
cargo build --release
cargo clippy --all-targets -- -D warnings   # zero warnings policy
cargo test --lib                            # 35 tests
```

The Rust side maintains a strict clippy gate. New code should not introduce warnings.

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
