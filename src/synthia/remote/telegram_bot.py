#!/usr/bin/env python3
"""
Synthia Telegram Bot - Remote access to your PC via Telegram.

Features:
- Text commands processed by local LLM
- Voice note transcription via Whisper
- System status checks
- Push notifications
"""

import os
import sys
import asyncio
import subprocess
import tempfile
import time
import logging
import re
from datetime import datetime
from pathlib import Path

# Add src to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


# Security: Input sanitization for text sent to terminal
MAX_MESSAGE_LENGTH = 2000  # Limit message length
DANGEROUS_SEQUENCES = [
    '\x1b',  # Escape sequences
    '\x00',  # Null bytes
    '\x07',  # Bell
    '\x08',  # Backspace
    '\x7f',  # Delete
]


def sanitize_terminal_input(text: str) -> str:
    """Sanitize text before sending to terminal via xdotool.

    Removes control characters and escape sequences that could be used
    to manipulate the terminal.
    """
    if not text:
        return ""

    # Truncate to max length
    text = text[:MAX_MESSAGE_LENGTH]

    # Remove dangerous control characters
    for seq in DANGEROUS_SEQUENCES:
        text = text.replace(seq, '')

    # Remove ANSI escape sequences
    text = re.sub(r'\x1b\[[0-9;]*[a-zA-Z]', '', text)

    # Remove other control characters (except newline, tab)
    text = ''.join(char for char in text if char == '\n' or char == '\t' or ord(char) >= 32)

    return text.strip()

try:
    from telegram import Update
    from telegram.ext import (
        Application,
        CommandHandler,
        MessageHandler,
        filters,
        ContextTypes,
    )
except ImportError:
    Update = None

from synthia.config import load_config
from synthia.assistant import Assistant
from synthia.transcribe import Transcriber

# Use XDG_RUNTIME_DIR for secure temp files (user-only access, not world-readable /tmp)
_RUNTIME_DIR = os.environ.get("XDG_RUNTIME_DIR", "/tmp")
REMOTE_MODE_FILE = os.path.join(_RUNTIME_DIR, "synthia-remote-mode")
WAITING_APPROVAL_FILE = os.path.join(_RUNTIME_DIR, "synthia-waiting-approval")
PLAN_APPROVED_FILE = os.path.join(_RUNTIME_DIR, "synthia-plan-approved")

# Set up logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)


class SynthiaBot:
    """Telegram bot for remote Synthia access."""

    def __init__(self, bot_token: str, allowed_users: list):
        self.bot_token = bot_token
        self.allowed_users = allowed_users
        self.app = None

        # Load config and initialize components
        self.config = load_config()

        # Initialize transcriber (Whisper)
        self.transcriber = Transcriber(
            use_local=True,
            local_model=self.config.get('local_stt_model', 'tiny')
        )

        # Initialize assistant (Qwen via Ollama)
        self.assistant = Assistant(
            use_local=True,
            local_model=self.config.get('local_llm_model', 'qwen2.5:1.5b-instruct-q4_0'),
            ollama_url=self.config.get('ollama_url', 'http://localhost:11434')
        )

        logger.info("Synthia Bot initialized")

    def is_authorized(self, user_id: int) -> bool:
        """Check if user is authorized to use the bot."""
        return user_id in self.allowed_users

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /start command."""
        if not self.is_authorized(update.effective_user.id):
            await update.message.reply_text("Unauthorized.")
            return

        # Check current mode
        mode = "Dev" if self._is_remote_mode() else "Quick"

        await update.message.reply_text(
            f"Hey! Synthia ready.\n\n"
            f"Mode: *{mode}*\n\n"
            "*Commands:*\n"
            "/dev - Dev Mode (control Claude Code remotely)\n"
            "/quick - Quick Mode (local assistant)\n"
            "/status - System status\n"
            "/disk - Disk space\n"
            "/gpu - GPU usage\n"
            "/screenshot - Take screenshot\n\n"
            "Or just send me a message or voice note!",
            parse_mode='Markdown'
        )

    async def status(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /status command - show system status."""
        if not self.is_authorized(update.effective_user.id):
            return

        try:
            # Get uptime
            uptime = subprocess.check_output(['uptime', '-p'], text=True).strip()

            # Get load average
            load = subprocess.check_output(['cat', '/proc/loadavg'], text=True).split()[:3]
            load_str = ', '.join(load)

            # Get memory
            mem = subprocess.check_output(['free', '-h'], text=True).split('\n')[1].split()
            mem_used, mem_total = mem[2], mem[1]

            # Check if Ollama is running
            ollama_status = "Running" if self._is_process_running('ollama') else "Stopped"

            # Check if Synthia main is running
            synthia_status = "Running" if self._is_process_running('synthia') else "Stopped"

            status_msg = (
                f"*System Status*\n\n"
                f"Uptime: {uptime}\n"
                f"Load: {load_str}\n"
                f"Memory: {mem_used} / {mem_total}\n\n"
                f"*Services*\n"
                f"Synthia: {synthia_status}\n"
                f"Ollama: {ollama_status}"
            )

            await update.message.reply_text(status_msg, parse_mode='Markdown')

        except Exception as e:
            await update.message.reply_text(f"Error getting status: {e}")

    async def disk(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /disk command - show disk usage."""
        if not self.is_authorized(update.effective_user.id):
            return

        try:
            df = subprocess.check_output(['df', '-h', '/'], text=True).split('\n')[1].split()
            used, total, percent = df[2], df[1], df[4]

            await update.message.reply_text(
                f"*Disk Usage*\n\n"
                f"Used: {used} / {total} ({percent})",
                parse_mode='Markdown'
            )
        except Exception as e:
            await update.message.reply_text(f"Error: {e}")

    async def gpu(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /gpu command - show GPU usage."""
        if not self.is_authorized(update.effective_user.id):
            return

        try:
            gpu_info = subprocess.check_output(
                ['nvidia-smi', '--query-gpu=name,memory.used,memory.total,utilization.gpu,temperature.gpu',
                 '--format=csv,noheader,nounits'],
                text=True
            ).strip()

            name, mem_used, mem_total, util, temp = gpu_info.split(', ')

            await update.message.reply_text(
                f"*GPU Status*\n\n"
                f"Model: {name}\n"
                f"Memory: {mem_used}MB / {mem_total}MB\n"
                f"Utilization: {util}%\n"
                f"Temperature: {temp}C",
                parse_mode='Markdown'
            )
        except Exception as e:
            await update.message.reply_text(f"Error: {e}")

    async def screenshot(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /screenshot command - take and send screenshot."""
        if not self.is_authorized(update.effective_user.id):
            return

        try:
            await update.message.reply_text("Taking screenshot...")

            # Take screenshot using gnome-screenshot or scrot
            screenshot_path = os.path.join(_RUNTIME_DIR, 'synthia_screenshot.png')

            # Try gnome-screenshot first, fall back to scrot
            try:
                subprocess.run(
                    ['gnome-screenshot', '-f', screenshot_path],
                    check=True,
                    env={**os.environ, 'DISPLAY': ':0'}
                )
            except FileNotFoundError:
                subprocess.run(
                    ['scrot', screenshot_path],
                    check=True,
                    env={**os.environ, 'DISPLAY': ':0'}
                )

            # Send the screenshot
            with open(screenshot_path, 'rb') as photo:
                await update.message.reply_photo(photo)

            # Clean up
            os.remove(screenshot_path)

        except Exception as e:
            await update.message.reply_text(f"Screenshot failed: {e}")

    async def clip_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /clip command - copy text to PC clipboard."""
        if not self.is_authorized(update.effective_user.id):
            return

        text = ' '.join(context.args) if context.args else ''
        if not text:
            await update.message.reply_text("Usage: /clip <text to copy>")
            return

        try:
            from synthia.commands import copy_to_clipboard
            success = copy_to_clipboard(text)

            if success:
                preview = text[:50] + "..." if len(text) > 50 else text
                await update.message.reply_text(f"Copied to PC clipboard:\n`{preview}`", parse_mode='Markdown')
            else:
                await update.message.reply_text("Failed to copy to clipboard")
        except Exception as e:
            await update.message.reply_text(f"Error: {e}")

    async def getclip_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /getclip command - get PC clipboard content."""
        if not self.is_authorized(update.effective_user.id):
            return

        try:
            from synthia.commands import get_clipboard
            content = get_clipboard()

            if content:
                # Truncate if too long for Telegram
                if len(content) > 4000:
                    content = content[:4000] + "\n\n... (truncated)"
                await update.message.reply_text(f"*PC Clipboard:*\n```\n{content}\n```", parse_mode='Markdown')
            else:
                await update.message.reply_text("Clipboard is empty")
        except Exception as e:
            await update.message.reply_text(f"Error: {e}")

    async def handle_document(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle document uploads - save to inbox."""
        if not self.is_authorized(update.effective_user.id):
            return

        try:
            from synthia.remote.inbox import add_inbox_item, get_files_dir

            doc = update.message.document
            file = await doc.get_file()

            # Download file
            files_dir = get_files_dir()
            # SECURITY: Sanitize filename to prevent path traversal (e.g., "../../.bashrc")
            safe_name = Path(doc.file_name).name  # Strips directory components
            if not safe_name or safe_name.startswith('.'):
                safe_name = f"upload_{int(time.time())}"
            file_path = files_dir / safe_name
            await file.download_to_drive(str(file_path))

            # Add to inbox
            add_inbox_item(
                item_type="file",
                filename=safe_name,
                path=str(file_path),
                size_bytes=doc.file_size,
                from_user=update.effective_user.first_name,
            )

            await update.message.reply_text(f"Saved to inbox: {safe_name}")
        except Exception as e:
            await update.message.reply_text(f"Error saving file: {e}")

    async def handle_photo(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle photo uploads - save largest resolution to inbox."""
        if not self.is_authorized(update.effective_user.id):
            return

        try:
            from synthia.remote.inbox import add_inbox_item, get_files_dir
            from datetime import datetime

            # Get largest photo
            photo = update.message.photo[-1]
            file = await photo.get_file()

            # Download
            files_dir = get_files_dir()
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"photo_{timestamp}.jpg"
            file_path = files_dir / filename
            await file.download_to_drive(str(file_path))

            # Add to inbox
            add_inbox_item(
                item_type="image",
                filename=filename,
                path=str(file_path),
                size_bytes=photo.file_size,
                from_user=update.effective_user.first_name,
            )

            await update.message.reply_text(f"Saved to inbox: {filename}")
        except Exception as e:
            await update.message.reply_text(f"Error saving photo: {e}")

    async def handle_text(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle text messages - route to Claude Code if in remote mode, else local LLM."""
        if not self.is_authorized(update.effective_user.id):
            return

        text = update.message.text
        logger.info(f"Received text: {text}")

        # Check for URLs and save to inbox (only if not in remote mode)
        if not self._is_remote_mode():
            url_pattern = r'https?://[^\s]+'
            urls = re.findall(url_pattern, text)
            if urls:
                from synthia.remote.inbox import add_inbox_item
                for url in urls:
                    add_inbox_item(
                        item_type="url",
                        filename=url[:60] + "..." if len(url) > 60 else url,
                        url=url,
                        from_user=update.effective_user.first_name,
                    )
                await update.message.reply_text(f"Saved {len(urls)} URL(s) to inbox")
                # If the message is just URL(s), don't process further
                text_without_urls = re.sub(url_pattern, '', text).strip()
                if not text_without_urls:
                    return

        # If in remote mode, send to Claude Code instead of local LLM
        if self._is_remote_mode():
            import random

            # Check if Claude is waiting for approval
            waiting_for_approval = os.path.exists(WAITING_APPROVAL_FILE)

            if waiting_for_approval:
                # Check if this is an approval message
                approval_words = ['yes', 'go', 'approved', 'proceed', 'do it', 'ok', 'okay', 'yep', 'yeah', 'sure', 'continue', 'execute', 'run it', 'go ahead']
                if text.lower().strip() in approval_words or text.lower().strip().rstrip('!.') in approval_words:
                    # Send approval signal
                    os.remove(WAITING_APPROVAL_FILE)
                    with open(PLAN_APPROVED_FILE, 'w') as f:
                        f.write('approved')
                    await update.message.reply_text("✅ Approved! Executing plan...")
                    # Send "proceed" to Claude Code
                    self._send_to_claude_code("proceed with the plan")
                    return
                else:
                    # New request while waiting - cancel old plan
                    os.remove(WAITING_APPROVAL_FILE)
                    await update.message.reply_text("📝 New request received, cancelling previous plan...")

            # Varied processing messages
            processing_msgs = [
                "📤 Sending to Claude Code...",
                "⏳ Processing, please wait...",
                "🚀 Sending now...",
                "📨 Forwarding to Claude...",
            ]
            await update.message.reply_text(random.choice(processing_msgs))

            success = self._send_to_claude_code(text)
            if not success:
                await update.message.reply_text("❌ Failed to send. Is WezTerm running?")
            return

        try:
            # Process with local assistant
            response = self.assistant.process(text)

            # Extract the spoken response (key is 'speech' not 'response')
            reply = response.get('speech', 'Sorry, I could not process that.')

            await update.message.reply_text(reply)

        except Exception as e:
            logger.error(f"Error processing text: {e}")
            await update.message.reply_text(f"Error: {e}")

    def _is_wayland(self) -> bool:
        """Check if running on Wayland."""
        return bool(os.environ.get("WAYLAND_DISPLAY"))

    def _get_display(self) -> str:
        """Get the active X display, trying common options."""
        for display in [':1', ':0']:
            try:
                result = subprocess.run(
                    ['wmctrl', '-l'],
                    capture_output=True, text=True,
                    env={**os.environ, 'DISPLAY': display},
                    timeout=2
                )
                if result.returncode == 0 and result.stdout.strip():
                    return display
            except Exception:
                pass
        return os.environ.get('DISPLAY', ':0')

    def _send_to_claude_code(self, message: str) -> bool:
        """Send a message to the Claude Code terminal.

        On Wayland: Uses wtype to type to the focused window.
        On X11: Uses xdotool with window targeting.

        SECURITY: Input is sanitized to prevent terminal escape sequence injection.
        """
        # Sanitize input before sending to terminal
        message = sanitize_terminal_input(message)
        if not message:
            logger.warning("Message was empty after sanitization")
            return False

        try:
            # Use Wayland-native approach if available
            if self._is_wayland():
                return self._send_wayland(message)
            else:
                return self._send_x11(message)

        except Exception as e:
            logger.error(f"Error sending to Claude Code: {e}")
            return False

    def _send_wayland(self, message: str) -> bool:
        """Send message using Wayland tools (wtype or ydotool)."""
        # Try ydotool first (works even without focus on the window)
        try:
            # Check if ydotoold is running
            result = subprocess.run(['pgrep', '-x', 'ydotoold'], capture_output=True)
            if result.returncode == 0:
                # ydotool is available and daemon is running
                subprocess.run(['ydotool', 'type', '--', message], check=True)
                subprocess.run(['ydotool', 'key', 'enter'], check=True)
                logger.info(f"Sent via ydotool: {message}")
                return True
        except FileNotFoundError:
            pass  # ydotool not installed, try wtype

        # Fallback to wtype (requires the terminal to be focused)
        try:
            # wtype types to the currently focused window
            subprocess.run(['wtype', message], check=True)
            subprocess.run(['wtype', '-k', 'Return'], check=True)
            logger.info(f"Sent via wtype: {message}")
            return True
        except FileNotFoundError:
            logger.error("No Wayland typing tool found. Install wtype or ydotool.")
            return False
        except subprocess.CalledProcessError as e:
            logger.error(f"wtype failed: {e}")
            return False

    def _send_x11(self, message: str) -> bool:
        """Send message using X11 tools (xdotool with window targeting)."""
        display = self._get_display()

        # Find terminal window - look for "Remote" tab in WezTerm
        result = subprocess.run(
            ['wmctrl', '-l'],
            capture_output=True, text=True,
            env={**os.environ, 'DISPLAY': display}
        )

        # Priority order for window matching:
        # 1. Window titled "Remote" (dedicated remote control tab)
        # 2. Window with Claude Code indicator (✳ or Claude)
        # 3. WezTerm windows (contain tab info like [1/4])
        window_id = None
        candidates = []
        for line in result.stdout.strip().split('\n'):
            parts = line.split(None, 4)
            if len(parts) >= 4:
                wid = parts[0]
                title = parts[-1] if len(parts) > 4 else ''
                # Skip empty titles and desktop/panel windows
                if not title or title.startswith('@!') or title.startswith('N/A'):
                    continue
                # Skip browser windows (Chrome, Firefox, etc)
                if any(x in title for x in ['Chrome', 'Firefox', 'Zen', 'Brave']):
                    continue
                # Highest priority - "Remote" tab
                if title == 'Remote':
                    candidates.insert(0, (wid, title))
                # High priority - Claude Code window (has ✳ indicator)
                elif '✳' in title:
                    candidates.insert(1 if candidates and candidates[0][1] == 'Remote' else 0, (wid, title))
                # Medium priority - WezTerm with tab indicator [X/Y]
                elif title.startswith('[') and '/' in title[:6]:
                    candidates.append((wid, title))

        if candidates:
            wid, title = candidates[0]
            window_id = str(int(wid, 16))
            logger.info(f"Found terminal window: {title} ({wid})")

        if not window_id:
            logger.error("No terminal window found")
            return False

        # Type the message into the terminal
        subprocess.run(
            ['xdotool', 'type', '--window', window_id, '--clearmodifiers', message],
            check=True,
            env={**os.environ, 'DISPLAY': display}
        )

        # Press Enter
        subprocess.run(
            ['xdotool', 'key', '--window', window_id, 'Return'],
            check=True,
            env={**os.environ, 'DISPLAY': display}
        )

        logger.info(f"Sent via xdotool: {message}")
        return True

    async def handle_voice(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle voice notes - transcribe and process."""
        if not self.is_authorized(update.effective_user.id):
            return

        try:
            await update.message.reply_text("🎤 Listening...")

            # Download voice file
            voice = await update.message.voice.get_file()

            # Create temp file for the voice note
            with tempfile.NamedTemporaryFile(suffix='.ogg', delete=False) as f:
                ogg_path = f.name

            await voice.download_to_drive(ogg_path)

            # Convert to WAV for Whisper
            wav_path = ogg_path.replace('.ogg', '.wav')
            subprocess.run([
                'ffmpeg', '-i', ogg_path, '-ar', '16000', '-ac', '1', wav_path, '-y'
            ], check=True, capture_output=True)

            # Read WAV and transcribe
            with open(wav_path, 'rb') as f:
                # Skip WAV header (44 bytes) and read PCM data
                f.seek(44)
                audio_data = f.read()

            transcript = self.transcriber.transcribe(audio_data)

            # Clean up temp files
            os.remove(ogg_path)
            os.remove(wav_path)

            if not transcript:
                await update.message.reply_text("Couldn't understand that. Try again?")
                return

            # If in remote mode, send to Claude Code
            if self._is_remote_mode():
                # Varied sending messages
                import random
                sending_msgs = [
                    "📤 Sending to Claude Code...",
                    "🚀 Forwarding to Claude...",
                    "📨 Sending now...",
                    "⏳ Processing, please wait...",
                ]
                await update.message.reply_text(random.choice(sending_msgs))

                success = self._send_to_claude_code(transcript)
                if not success:
                    await update.message.reply_text("❌ Failed to send. Is WezTerm running?")
                return

            # Show what was heard (only in local mode)
            await update.message.reply_text(f"Heard: _{transcript}_", parse_mode='Markdown')

            # Process with assistant
            response = self.assistant.process(transcript)
            reply = response.get('speech', 'Sorry, I could not process that.')

            await update.message.reply_text(reply)

        except Exception as e:
            logger.error(f"Error processing voice: {e}")
            await update.message.reply_text(f"Error: {e}")

    def _is_process_running(self, name: str) -> bool:
        """Check if a process is running."""
        try:
            subprocess.check_output(['pgrep', '-f', name])
            return True
        except subprocess.CalledProcessError:
            return False

    def _is_remote_mode(self) -> bool:
        """Check if remote mode is enabled."""
        return os.path.exists(REMOTE_MODE_FILE)

    def _get_remote_chat_id(self) -> int:
        """Get the chat ID for remote notifications."""
        try:
            with open(REMOTE_MODE_FILE, 'r') as f:
                return int(f.read().strip())
        except Exception:
            return None

    async def enable_dev_mode(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Enable Dev Mode - control Claude Code remotely."""
        if not self.is_authorized(update.effective_user.id):
            return

        chat_id = update.effective_chat.id

        # Save mode state with chat_id (restrictive permissions)
        with open(REMOTE_MODE_FILE, 'w') as f:
            f.write(str(chat_id))
        os.chmod(REMOTE_MODE_FILE, 0o600)

        await update.message.reply_text(
            "🟢 *Dev Mode ENABLED*\n\n"
            "You can now control Claude Code remotely.\n"
            "Use /quick when you're back at your PC.",
            parse_mode='Markdown'
        )
        logger.info(f"Dev Mode enabled for chat {chat_id}")

    async def enable_quick_mode(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Enable Quick Mode - local assistant."""
        if not self.is_authorized(update.effective_user.id):
            return

        # Remove dev mode file
        try:
            os.remove(REMOTE_MODE_FILE)
        except FileNotFoundError:
            pass

        await update.message.reply_text(
            "🟡 *Quick Mode ENABLED*\n\n"
            "Back to local assistant. Claude will speak responses.",
            parse_mode='Markdown'
        )
        logger.info("Quick Mode enabled")

    async def send_notification(self, chat_id: int, message: str):
        """Send a push notification to a user."""
        if self.app:
            await self.app.bot.send_message(chat_id=chat_id, text=f"🔔 {message}")

    def run(self):
        """Start the bot."""
        logger.info("Starting Synthia Telegram bot...")

        # Build application
        self.app = Application.builder().token(self.bot_token).build()

        # Add handlers
        self.app.add_handler(CommandHandler("start", self.start))
        self.app.add_handler(CommandHandler("status", self.status))
        self.app.add_handler(CommandHandler("disk", self.disk))
        self.app.add_handler(CommandHandler("gpu", self.gpu))
        self.app.add_handler(CommandHandler("screenshot", self.screenshot))
        self.app.add_handler(CommandHandler("dev", self.enable_dev_mode))
        self.app.add_handler(CommandHandler("quick", self.enable_quick_mode))
        # Keep old commands as aliases for backwards compatibility
        self.app.add_handler(CommandHandler("remote", self.enable_dev_mode))
        self.app.add_handler(CommandHandler("local", self.enable_quick_mode))
        # Clipboard sync commands
        self.app.add_handler(CommandHandler("clip", self.clip_command))
        self.app.add_handler(CommandHandler("getclip", self.getclip_command))
        # Message handlers
        self.app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_text))
        self.app.add_handler(MessageHandler(filters.VOICE, self.handle_voice))
        self.app.add_handler(MessageHandler(filters.Document.ALL, self.handle_document))
        self.app.add_handler(MessageHandler(filters.PHOTO, self.handle_photo))

        # Run the bot
        logger.info("Bot is ready! Listening for messages...")
        self.app.run_polling(allowed_updates=Update.ALL_TYPES)


def send_telegram_notification(message: str):
    """Send a one-off notification to all allowed users."""
    import requests

    config = load_config()
    bot_token = config.get('telegram_bot_token')
    allowed_users = config.get('telegram_allowed_users', [])

    if not bot_token or not allowed_users:
        return False

    for user_id in allowed_users:
        try:
            url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
            requests.post(url, json={
                "chat_id": user_id,
                "text": message,
                "parse_mode": "Markdown"
            }, timeout=5)
        except Exception as e:
            logger.error(f"Failed to send notification: {e}")

    return True


def main():
    """Main entry point."""
    # Check for notification mode
    if len(sys.argv) > 1 and sys.argv[1] == "--notify":
        message = " ".join(sys.argv[2:]) if len(sys.argv) > 2 else "Notification"
        send_telegram_notification(message)
        return

    config = load_config()

    bot_token = config.get('telegram_bot_token')
    allowed_users = config.get('telegram_allowed_users', [])

    if not bot_token:
        print("Error: telegram_bot_token not set in config")
        print("Add it to ~/.config/synthia/config.yaml")
        sys.exit(1)

    if not allowed_users:
        print("Error: telegram_allowed_users not set in config")
        print("Add your Telegram user ID to ~/.config/synthia/config.yaml")
        sys.exit(1)

    bot = SynthiaBot(bot_token, allowed_users)
    bot.run()


if __name__ == "__main__":
    main()
