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

        # Use LinuxVoice TTS to speak the response
        cd /home/markmiddo/Misc/linuxvoice
        source venv/bin/activate
        python -c "
from tts import TextToSpeech
from config import load_config, get_google_credentials_path
import sys

config = load_config()
tts = TextToSpeech(
    get_google_credentials_path(config),
    config['tts_voice'],
    config['tts_speed']
)
tts.speak('''$SPEAK_TEXT''')
" 2>/dev/null
    fi
fi

exit 0
