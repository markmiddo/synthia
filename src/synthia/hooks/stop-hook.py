#!/usr/bin/env python3
"""
Claude Code Stop hook - speaks Claude's response when it finishes.
Reads hook JSON from stdin and extracts the response to speak.
"""

import sys
import os
import json
import time

# Add synthia to path
sys.path.insert(0, '/home/markmiddo/dev/misc/synthia/src')

# Track last spoken message to avoid repeats
LAST_MESSAGE_FILE = '/tmp/synthia-last-spoken-hash'


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
        with open('/tmp/stop-hook-debug.log', 'a') as f:
            f.write(f"Error reading transcript: {e}\n")
        return ""


def main():
    # Log that hook was called
    with open('/tmp/stop-hook-debug.log', 'a') as f:
        f.write(f"Hook called at {__import__('datetime').datetime.now()}\n")

    # Read hook input from stdin
    try:
        raw_input = sys.stdin.read()
        with open('/tmp/stop-hook-debug.log', 'a') as f:
            f.write(f"Raw input: {raw_input}\n")
        hook_input = json.loads(raw_input)
    except json.JSONDecodeError as e:
        with open('/tmp/stop-hook-debug.log', 'a') as f:
            f.write(f"JSON decode error: {e}\n")
        sys.exit(0)

    with open('/tmp/stop-hook-debug.log', 'a') as f:
        f.write(f"Parsed input keys: {hook_input.keys()}\n")

    transcript_path = hook_input.get('transcript_path', '')

    with open('/tmp/stop-hook-debug.log', 'a') as f:
        f.write(f"Transcript path: {transcript_path}\n")
        f.write(f"Exists: {os.path.exists(transcript_path)}\n")

    if not transcript_path or not os.path.exists(transcript_path):
        sys.exit(0)

    # Wait for transcript to be fully written
    # The hook fires before Claude finishes writing, so we need to wait
    initial_delay = 1.5  # seconds
    time.sleep(initial_delay)

    with open('/tmp/stop-hook-debug.log', 'a') as f:
        f.write(f"Waited {initial_delay}s for transcript to settle\n")

    # Check freshness - wait for file to be recently modified
    max_retries = 3
    retry_delay = 0.5
    for attempt in range(max_retries):
        mtime = os.path.getmtime(transcript_path)
        age = time.time() - mtime

        with open('/tmp/stop-hook-debug.log', 'a') as f:
            f.write(f"Attempt {attempt + 1}: File age = {age:.2f}s\n")

        # If file was modified in last 5 seconds, it's probably fresh enough
        if age < 5:
            break

        # File seems stale, wait and retry
        if attempt < max_retries - 1:
            time.sleep(retry_delay)

    # Get the last assistant message
    message = get_last_assistant_message(transcript_path)

    # Check if we already spoke this exact message (deduplication)
    if message:
        import hashlib
        msg_hash = hashlib.md5(message[:500].encode()).hexdigest()

        try:
            if os.path.exists(LAST_MESSAGE_FILE):
                with open(LAST_MESSAGE_FILE, 'r') as f:
                    last_hash = f.read().strip()
                if last_hash == msg_hash:
                    with open('/tmp/stop-hook-debug.log', 'a') as f:
                        f.write(f"Skipping duplicate message (hash: {msg_hash[:8]})\n")
                    sys.exit(0)
        except Exception:
            pass

        # Save this hash for next time
        try:
            with open(LAST_MESSAGE_FILE, 'w') as f:
                f.write(msg_hash)
        except Exception:
            pass

    with open('/tmp/stop-hook-debug.log', 'a') as f:
        f.write(f"Extracted message: {message[:200] if message else 'NONE'}...\n")

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
    if len(message) > 500:
        # Find a good cutoff point (end of sentence)
        cutoff = 500
        for end in ['. ', '! ', '? ']:
            pos = message[:600].rfind(end)
            if pos > 300:
                cutoff = pos + 1
                break
        message = message[:cutoff] + " Check the full response for more."

    # Check if we're in remote mode
    remote_mode = os.path.exists('/tmp/synthia-remote-mode')

    with open('/tmp/stop-hook-debug.log', 'a') as f:
        f.write(f"Remote mode: {remote_mode}\n")

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
                # Check if it looks like a plan (has multiple numbered items)
                if re.search(r'\d\.\s+\w', full_message) or re.search(r'(?:first|then|next|finally)', lower_msg):
                    is_plan = True

            # Send longer message to Telegram (up to 1000 chars)
            telegram_message = full_message[:1000]
            if len(full_message) > 1000:
                telegram_message += "...\n\n_(truncated - check Claude Code for full response)_"

            if is_plan:
                # This is a plan - ask for approval
                with open('/tmp/synthia-waiting-approval', 'w') as f:
                    f.write('waiting')
                send_telegram(f"📋 *Plan:*\n\n{telegram_message}\n\n---\n✋ *Reply 'yes' or 'go' to approve*", "Markdown")
                with open('/tmp/stop-hook-debug.log', 'a') as f:
                    f.write(f"Sent plan to Telegram, waiting for approval\n")
            else:
                send_telegram(f"🤖 *Claude:*\n\n{telegram_message}", "Markdown")
                with open('/tmp/stop-hook-debug.log', 'a') as f:
                    f.write(f"Sent to Telegram\n")
        except Exception as e:
            with open('/tmp/stop-hook-debug.log', 'a') as f:
                f.write(f"Telegram Error: {e}\n")
    else:
        # Speak using local Piper
        try:
            with open('/tmp/stop-hook-debug.log', 'a') as f:
                f.write(f"About to speak: {message[:100]}...\n")

            from synthia.tts import TextToSpeech
            from synthia.config import load_config

            config = load_config()
            tts = TextToSpeech(
                use_local=True,
                local_voice=config.get('local_tts_voice', '~/.local/share/piper-voices/en_US-lessac-high.onnx')
            )

            tts.speak(message)

            with open('/tmp/stop-hook-debug.log', 'a') as f:
                f.write(f"Spoke successfully\n")
        except Exception as e:
            with open('/tmp/stop-hook-debug.log', 'a') as f:
                f.write(f"TTS Error: {e}\n")


if __name__ == "__main__":
    main()
