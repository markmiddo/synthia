"""Claude AI Assistant integration for LinuxVoice."""

import json
from datetime import datetime
import anthropic
from typing import List, Dict, Any, Optional


SYSTEM_PROMPT = """You are LinuxVoice, a friendly voice assistant on a Linux system. Today is {date}.

CRITICAL RULES:
1. You KNOW the current date/time (shown above) - just tell the user directly!
2. For general knowledge, math, explanations - answer directly in speech
3. ONLY use run_command for system-specific info you can't know
4. When you DO run a command, your speech should say "Let me check" - the output will be spoken automatically

Response format - ALWAYS valid JSON only:
{{"speech": "Your response here.", "actions": []}}

AVAILABLE ACTIONS:

Apps & URLs:
- {{"type": "open_app", "app": "firefox"}}
- {{"type": "close_app", "app": "firefox"}}
- {{"type": "open_url", "url": "github.com"}}  (uses Chrome by default)

Volume Control:
- {{"type": "set_volume", "level": 50}} (0-100)
- {{"type": "change_volume", "delta": 10}} (positive=up, negative=down)
- {{"type": "mute"}}
- {{"type": "unmute"}}
- {{"type": "toggle_mute"}}

Window Management:
- {{"type": "maximize_window"}}
- {{"type": "minimize_window"}}
- {{"type": "close_window"}}
- {{"type": "switch_workspace", "number": 2}}
- {{"type": "move_to_workspace", "number": 2}}

Clipboard:
- {{"type": "copy_to_clipboard", "text": "..."}}
- {{"type": "get_clipboard"}}
- {{"type": "paste"}}

Screenshot:
- {{"type": "screenshot"}} (full screen)
- {{"type": "screenshot", "region": "window"}}
- {{"type": "screenshot", "region": "selection"}}

System:
- {{"type": "lock_screen"}}
- {{"type": "suspend"}}
- {{"type": "type_text", "text": "..."}}
- {{"type": "run_command", "command": "..."}}

EXAMPLES:
- "Turn up the volume" → {{"speech": "Turning up the volume.", "actions": [{{"type": "change_volume", "delta": 10}}]}}
- "Mute" → {{"speech": "Muted.", "actions": [{{"type": "mute"}}]}}
- "Take a screenshot" → {{"speech": "Taking a screenshot.", "actions": [{{"type": "screenshot"}}]}}
- "Maximize this window" → {{"speech": "Maximizing.", "actions": [{{"type": "maximize_window"}}]}}
- "Lock the screen" → {{"speech": "Locking the screen.", "actions": [{{"type": "lock_screen"}}]}}
- "What's in my clipboard?" → {{"speech": "Let me check.", "actions": [{{"type": "get_clipboard"}}]}}

Be brief, friendly, conversational. One sentence is usually enough."""


class Assistant:
    """Claude-powered voice assistant."""

    def __init__(self, api_key: str, model: str = "claude-haiku-4-20250514", memory_size: int = 10):
        self.client = anthropic.Anthropic(api_key=api_key)
        self.model = model
        self.memory_size = memory_size
        self.conversation_history: List[Dict[str, str]] = []

        print(f"🤖 Assistant initialized with model: {model}")

    def _add_to_history(self, role: str, content: str):
        """Add a message to conversation history, maintaining memory limit."""
        self.conversation_history.append({"role": role, "content": content})

        # Trim history if it exceeds memory size (keep pairs)
        while len(self.conversation_history) > self.memory_size * 2:
            self.conversation_history.pop(0)

    def process(self, user_input: str) -> Dict[str, Any]:
        """Process user input and return response with actions."""
        if not user_input.strip():
            return {"speech": "I didn't catch that. Could you repeat?", "actions": []}

        # Add user message to history
        self._add_to_history("user", user_input)

        try:
            # Get current date/time for the prompt
            current_datetime = datetime.now().strftime("%A, %B %d, %Y at %I:%M %p")
            system_prompt = SYSTEM_PROMPT.format(date=current_datetime)

            # Call Claude API
            response = self.client.messages.create(
                model=self.model,
                max_tokens=1500,
                system=system_prompt,
                messages=self.conversation_history,
            )

            # Extract response text
            response_text = response.content[0].text.strip()

            # Parse JSON response
            try:
                # Try to extract JSON from response (handle potential markdown wrapping)
                if response_text.startswith("```"):
                    # Extract JSON from markdown code block
                    lines = response_text.split("\n")
                    json_lines = []
                    in_json = False
                    for line in lines:
                        if line.startswith("```") and not in_json:
                            in_json = True
                            continue
                        elif line.startswith("```") and in_json:
                            break
                        elif in_json:
                            json_lines.append(line)
                    response_text = "\n".join(json_lines)

                result = json.loads(response_text)

                # Validate structure
                if "speech" not in result:
                    result["speech"] = "I processed your request."
                if "actions" not in result:
                    result["actions"] = []

            except json.JSONDecodeError:
                # If JSON parsing fails, treat the whole response as speech
                result = {"speech": response_text, "actions": []}

            # Add assistant response to history
            self._add_to_history("assistant", json.dumps(result))

            print(f"🤖 Response: {result['speech']}")
            if result['actions']:
                print(f"📋 Actions: {result['actions']}")

            return result

        except Exception as e:
            print(f"❌ Assistant error: {e}")
            return {"speech": f"Sorry, I encountered an error: {str(e)}", "actions": []}

    def clear_history(self):
        """Clear conversation history."""
        self.conversation_history = []
        print("🧹 Conversation history cleared")
