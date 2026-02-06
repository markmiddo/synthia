#!/bin/bash
# Voice input for Claude Code
# Records audio, transcribes it, and outputs the text
# Usage: ./voice-to-claude.sh [duration_seconds]

DURATION=${1:-5}
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SYNTHIA_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"

cd "$SYNTHIA_ROOT"
source venv/bin/activate

# Record and transcribe
python -m synthia.hooks.voice-input --duration "$DURATION"
