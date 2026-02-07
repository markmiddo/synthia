# Changelog

All notable changes to Synthia will be documented in this file.

## [0.1.0] - 2026-02-07

### Added
- Speech-to-text via Google Cloud Speech or local Whisper
- Text-to-speech via Google Cloud TTS or local Piper
- AI assistant via Claude API or local Ollama
- Hotkey activation (Right Ctrl for dictation, Right Alt for assistant)
- Telegram remote access
- TUI dashboard (Textual)
- Clipboard monitoring with history
- Memory system integration
- Task management CLI
- System tray indicator
- Worktree management for Claude Code sessions
- Web search via Tavily

### Code Health
- 593 tests across 20 test files
- Type hints on all public functions (PEP 604 syntax)
- PEP 561 py.typed marker for downstream type checking
- CI pipeline: lint (black/isort), typecheck (mypy), test (pytest x3 Python versions)
- Pre-commit hooks for formatting
- Config validation with warnings for invalid values
- Optional dependency extras: local, cloud, remote, search, tui, all, dev
- Dashboard widget extraction for maintainability
