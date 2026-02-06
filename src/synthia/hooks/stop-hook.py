#!/usr/bin/env python3
"""
Claude Code Stop hook - speaks Claude's response when it finishes.
Reads hook JSON from stdin and extracts the response to speak.
"""

import sys
import os
import json
import time

# Add synthia to path (resolve relative to this file's location)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Use XDG_RUNTIME_DIR for temp files (not world-readable /tmp)
_RUNTIME_DIR = os.environ.get("XDG_RUNTIME_DIR", "/tmp")
LAST_MESSAGE_FILE = os.path.join(_RUNTIME_DIR, 'synthia-last-spoken-hash')
DEBUG_LOG_FILE = os.path.join(_RUNTIME_DIR, 'synthia-stop-hook-debug.log')

# Message length limits
TTS_MAX_CHARS = 500          # Max chars to speak locally
TTS_SEARCH_WINDOW = 600      # Window to search for sentence boundary
TTS_MIN_CUTOFF = 300         # Minimum chars before allowing cutoff
TELEGRAM_MAX_CHARS = 1000    # Max chars to send via Telegram
HASH_PREFIX_LEN = 500        # Chars to hash for dedup


def _debug_log(message: str):
    """Write to debug log with restrictive permissions."""
    try:
        with open(DEBUG_LOG_FILE, 'a') as f:
            f.write(message)
        os.chmod(DEBUG_LOG_FILE, 0o600)
    except Exception:
        pass


def get_last_assistant_message(transcript_path: str) -> str:
    """Extract the last assistant message from the transcript (JSONL format)."""
    try:
        # Read JSONL file (one JSON object per line)
        entries = []
        with open(transcript_path, 'r') as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        entries.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue

        # Find the last assistant message with text content
        for entry in reversed(entries):
            if entry.get('type') == 'assistant':
                message = entry.get('message', {})

                # Message is a dict with 'content' key
                if isinstance(message, dict):
                    content = message.get('content', [])
                    if isinstance(content, list):
                        texts = []
                        for block in content:
                            if isinstance(block, dict) and block.get('type') == 'text':
                                texts.append(block.get('text', ''))
                        if texts:
                            return ' '.join(texts)

        return ""
    except Exception as e:
        _debug_log(f"Error reading transcript: {e}\n")
        return ""


def main():
    _debug_log(f"Hook called at {__import__('datetime').datetime.now()}\n")

    # Read hook input from stdin
    try:
        raw_input = sys.stdin.read()
        _debug_log(f"Raw input length: {len(raw_input)}\n")
        hook_input = json.loads(raw_input)
    except json.JSONDecodeError as e:
        _debug_log(f"JSON decode error: {e}\n")
        sys.exit(0)

    _debug_log(f"Parsed input keys: {list(hook_input.keys())}\n")

    transcript_path = hook_input.get('transcript_path', '')
    _debug_log(f"Transcript path: {transcript_path}\n")
    _debug_log(f"Exists: {os.path.exists(transcript_path)}\n")

    if not transcript_path or not os.path.exists(transcript_path):
        sys.exit(0)

    # Wait for transcript to be fully written
    initial_delay = 1.5
    time.sleep(initial_delay)
    _debug_log(f"Waited {initial_delay}s for transcript to settle\n")

    # Check freshness - wait for file to be recently modified
    max_retries = 3
    retry_delay = 0.5
    for attempt in range(max_retries):
        mtime = os.path.getmtime(transcript_path)
        age = time.time() - mtime
        _debug_log(f"Attempt {attempt + 1}: File age = {age:.2f}s\n")

        if age < 5:
            break
        if attempt < max_retries - 1:
            time.sleep(retry_delay)

    # Get the last assistant message
    message = get_last_assistant_message(transcript_path)

    # Check if we already spoke this exact message (deduplication)
    if message:
        import hashlib
        msg_hash = hashlib.sha256(message[:HASH_PREFIX_LEN].encode()).hexdigest()

        try:
            if os.path.exists(LAST_MESSAGE_FILE):
                with open(LAST_MESSAGE_FILE, 'r') as f:
                    last_hash = f.read().strip()
                if last_hash == msg_hash:
                    _debug_log(f"Skipping duplicate message (hash: {msg_hash[:8]})\n")
                    sys.exit(0)
        except Exception:
            pass

        # Save this hash for next time
        try:
            with open(LAST_MESSAGE_FILE, 'w') as f:
                f.write(msg_hash)
            os.chmod(LAST_MESSAGE_FILE, 0o600)
        except Exception:
            pass

    _debug_log(f"Extracted message: {message[:200] if message else 'NONE'}...\n")

    if not message:
        sys.exit(0)

    # Clean and truncate for TTS
    message = message.strip()

    # Strip markdown formatting for cleaner speech
    import re
    message = re.sub(r'\*\*([^*]+)\*\*', r'\1', message)  # **bold**
    message = re.sub(r'\*([^*]+)\*', r'\1', message)      # *italic*
    message = re.sub(r'`([^`]+)`', r'\1', message)        # `code`
    message = re.sub(r'^\s*[-*]\s+', '', message, flags=re.MULTILINE)  # bullet points
    message = re.sub(r'^\s*\d+\.\s+', '', message, flags=re.MULTILINE)  # numbered lists
    message = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', message)  # [links](url)
    message = re.sub(r'(?<=[a-zA-Z])/(?=[a-zA-Z])', ' or ', message)  # word/word -> word or word
    message = re.sub(r'(?<!\w)/|/(?!\w)', ' ', message)  # standalone slashes
    message = message.replace('\\', '')  # remove backslashes

    # Skip if it's just code or too short
    if message.startswith('```') or len(message) < 10:
        sys.exit(0)

    # Limit message length - speak first ~500 chars (2-3 sentences)
    full_message = message  # Keep full for Telegram
    if len(message) > TTS_MAX_CHARS:
        cutoff = TTS_MAX_CHARS
        for end in ['. ', '! ', '? ']:
            pos = message[:TTS_SEARCH_WINDOW].rfind(end)
            if pos > TTS_MIN_CUTOFF:
                cutoff = pos + 1
                break
        message = message[:cutoff] + " Check the full response for more."

    # Check if we're in remote mode (use XDG_RUNTIME_DIR, consistent with telegram_bot.py)
    remote_mode_file = os.path.join(_RUNTIME_DIR, "synthia-remote-mode")
    remote_mode = os.path.exists(remote_mode_file)
    _debug_log(f"Remote mode: {remote_mode}\n")

    if remote_mode:
        # Send to Telegram instead of speaking
        try:
            from synthia.remote.send_telegram import send_telegram

            # Detect if this is a plan (contains numbered steps or "plan" keywords)
            is_plan = False
            plan_indicators = [
                '1.', '1)', 'step 1', 'first,', 'here\'s my plan', 'here is my plan',
                'i\'ll need to', 'i will need to', 'the plan is', 'my plan:',
                'approach:', 'steps:', 'to do this', 'implementation plan'
            ]
            lower_msg = full_message.lower()
            if any(indicator in lower_msg for indicator in plan_indicators):
                if re.search(r'\d\.\s+\w', full_message) or re.search(r'(?:first|then|next|finally)', lower_msg):
                    is_plan = True

            telegram_message = full_message[:TELEGRAM_MAX_CHARS]
            if len(full_message) > TELEGRAM_MAX_CHARS:
                telegram_message += "...\n\n_(truncated - check Claude Code for full response)_"

            if is_plan:
                waiting_file = os.path.join(_RUNTIME_DIR, "synthia-waiting-approval")
                with open(waiting_file, 'w') as f:
                    f.write('waiting')
                os.chmod(waiting_file, 0o600)
                send_telegram(f"📋 *Plan:*\n\n{telegram_message}\n\n---\n✋ *Reply 'yes' or 'go' to approve*", "Markdown")
                _debug_log("Sent plan to Telegram, waiting for approval\n")
            else:
                send_telegram(f"🤖 *Claude:*\n\n{telegram_message}", "Markdown")
                _debug_log("Sent to Telegram\n")
        except Exception as e:
            _debug_log(f"Telegram Error: {e}\n")
    else:
        # Speak using local Piper
        try:
            _debug_log(f"About to speak: {message[:100]}...\n")

            from synthia.tts import TextToSpeech
            from synthia.config import load_config

            config = load_config()
            tts = TextToSpeech(
                use_local=True,
                local_voice=config.get('local_tts_voice', '~/.local/share/piper-voices/en_US-lessac-high.onnx')
            )

            tts.speak(message)
            _debug_log("Spoke successfully\n")
        except Exception as e:
            _debug_log(f"TTS Error: {e}\n")


if __name__ == "__main__":
    main()
