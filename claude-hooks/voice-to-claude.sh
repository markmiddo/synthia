#!/bin/bash
# Voice input for Claude Code
# Records audio, transcribes it, and outputs the text
# Usage: ./voice-to-claude.sh [duration_seconds]

DURATION=${1:-5}
SCRIPT_DIR="$(dirname "$(readlink -f "$0")")"
LINUXVOICE_DIR="/home/markmiddo/Misc/linuxvoice"

cd "$LINUXVOICE_DIR"
source venv/bin/activate

# Record and transcribe
python claude-hooks/voice-input.py --duration "$DURATION"
