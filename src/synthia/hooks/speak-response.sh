#!/bin/bash
# Hook script that speaks Claude's response using LinuxVoice TTS
# This runs on the "Stop" event when Claude finishes responding

# Read JSON input from stdin
INPUT=$(cat)

# Extract the assistant's message from the transcript
# The Stop hook receives session info - we need to get the last response

# Get transcript path
TRANSCRIPT_PATH=$(echo "$INPUT" | jq -r '.transcript_path // empty')

if [ -n "$TRANSCRIPT_PATH" ] && [ -f "$TRANSCRIPT_PATH" ]; then
    # Get the last assistant message from transcript
    LAST_MESSAGE=$(jq -r '
        [.[] | select(.type == "assistant")] | last |
        if .message then
            if .message | type == "array" then
                [.message[] | select(.type == "text") | .text] | join(" ")
            else
                .message
            end
        else
            empty
        end
    ' "$TRANSCRIPT_PATH" 2>/dev/null)

    if [ -n "$LAST_MESSAGE" ] && [ "$LAST_MESSAGE" != "null" ]; then
        # Truncate very long messages for TTS (max ~500 chars)
        SPEAK_TEXT=$(echo "$LAST_MESSAGE" | head -c 500)

        # Use Synthia TTS to speak the response
        SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
        SYNTHIA_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
        source "$SYNTHIA_ROOT/venv/bin/activate"
        python -c "
from synthia.tts import TextToSpeech
from synthia.config import load_config
import sys

config = load_config()
tts = TextToSpeech(
    use_local=config.get('use_local_tts', True),
    local_voice=config.get('local_tts_voice', '')
)
tts.speak('''$SPEAK_TEXT''')
" 2>/dev/null
    fi
fi

exit 0
