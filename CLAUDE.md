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

## Key Directories

- `src/synthia/` - Python core application
- `gui/` - Tauri desktop GUI (Rust + React)
- `docs/` - Documentation and PRDs

## Running Synthia

Use the run script from the project root. The GUI is built with Tauri and runs separately.

## Brand

Always write "Synthia" with capital S. Website is synthia-ai.com.
