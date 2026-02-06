#!/usr/bin/env python3
"""
Send a message to Telegram when in remote mode.
Called by Claude Code hooks to notify user of updates.

Usage: python send_telegram.py "Your message here"
"""

import logging
import os
import sys

import requests

logger = logging.getLogger(__name__)

# Add synthia src to path (resolve relative to this file)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from synthia.config import load_config

# Use XDG_RUNTIME_DIR for secure temp files (not world-readable /tmp)
REMOTE_MODE_FILE = os.path.join(
    os.environ.get("XDG_RUNTIME_DIR", "/tmp"), "synthia-remote-mode"
)


def is_remote_mode():
    """Check if remote mode is enabled."""
    return os.path.exists(REMOTE_MODE_FILE)


def get_chat_id():
    """Get the chat ID for remote notifications."""
    try:
        with open(REMOTE_MODE_FILE, 'r') as f:
            return int(f.read().strip())
    except (IOError, ValueError) as e:
        logger.debug("Could not read remote mode file: %s", e)
        return None


def send_telegram(message: str, parse_mode: str = None):
    """Send a message via Telegram bot."""
    if not is_remote_mode():
        return False

    chat_id = get_chat_id()
    if not chat_id:
        return False

    config = load_config()
    bot_token = config.get('telegram_bot_token')

    if not bot_token:
        return False

    try:
        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        data = {
            "chat_id": chat_id,
            "text": message,
        }
        if parse_mode:
            data["parse_mode"] = parse_mode

        response = requests.post(url, json=data, timeout=10)
        return response.status_code == 200
    except Exception as e:
        logger.error("Telegram send error: %s", e)
        return False


def main():
    if len(sys.argv) < 2:
        print("Usage: python send_telegram.py 'message'")
        sys.exit(1)

    message = sys.argv[1]

    # Check for parse_mode argument
    parse_mode = None
    if len(sys.argv) > 2 and sys.argv[2] in ['Markdown', 'HTML']:
        parse_mode = sys.argv[2]

    if is_remote_mode():
        success = send_telegram(message, parse_mode)
        if success:
            print("Sent to Telegram")
        else:
            print("Failed to send to Telegram")
    else:
        print("Not in remote mode")


if __name__ == "__main__":
    main()
