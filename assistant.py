"""AI Assistant integration for Synthia - supports Claude API and local Ollama."""

import json
import requests
from datetime import datetime
from typing import List, Dict, Any


SYSTEM_PROMPT = """You are Synthia, a friendly voice assistant on a Linux system. Today is {date}.

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

Remote Mode (for controlling via Telegram when away):
- {{"type": "enable_remote"}} - Switch to Telegram mode
- {{"type": "disable_remote"}} - Switch back to voice mode

EXAMPLES:
- "Turn up the volume" → {{"speech": "Turning up the volume.", "actions": [{{"type": "change_volume", "delta": 10}}]}}
- "Mute" → {{"speech": "Muted.", "actions": [{{"type": "mute"}}]}}
- "Take a screenshot" → {{"speech": "Taking a screenshot.", "actions": [{{"type": "screenshot"}}]}}
- "Maximize this window" → {{"speech": "Maximizing.", "actions": [{{"type": "maximize_window"}}]}}
- "Lock the screen" → {{"speech": "Locking the screen.", "actions": [{{"type": "lock_screen"}}]}}
- "What's in my clipboard?" → {{"speech": "Let me check.", "actions": [{{"type": "get_clipboard"}}]}}
- "Remote mode" or "Enable remote" → {{"speech": "Switching to remote mode. Updates will go to Telegram.", "actions": [{{"type": "enable_remote"}}]}}
- "Local mode" or "Disable remote" → {{"speech": "Back to local mode.", "actions": [{{"type": "disable_remote"}}]}}

Be brief, friendly, conversational. One sentence is usually enough."""


class Assistant:
    """Voice assistant supporting Claude API and local Ollama."""

    def __init__(self, api_key: str = None, model: str = "claude-haiku-4-20250514",
                 memory_size: int = 10, use_local: bool = False,
                 local_model: str = "qwen2.5:7b-instruct-q4_0",
                 ollama_url: str = "http://localhost:11434"):
        self.use_local = use_local
        self.model = model if not use_local else local_model
        self.memory_size = memory_size
        self.conversation_history: List[Dict[str, str]] = []
        self.ollama_url = ollama_url
        self.client = None

        if use_local:
            print(f"Assistant initialized with local model: {self.model}")
        else:
            import anthropic
            self.client = anthropic.Anthropic(api_key=api_key)
            print(f"Assistant initialized with Claude: {model}")

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
            if self.use_local:
                return self._process_ollama(user_input)
            else:
                return self._process_claude(user_input)
        except Exception as e:
            print(f"Assistant error: {e}")
            return {"speech": f"Sorry, I encountered an error: {str(e)}", "actions": []}

    def _process_claude(self, user_input: str) -> Dict[str, Any]:
        """Process using Claude API."""
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

        response_text = response.content[0].text.strip()
        return self._parse_response(response_text)

    def _process_ollama(self, user_input: str) -> Dict[str, Any]:
        """Process using local Ollama."""
        current_datetime = datetime.now().strftime("%A, %B %d, %Y at %I:%M %p")
        system_prompt = SYSTEM_PROMPT.format(date=current_datetime)

        # Build conversation for Ollama
        messages = [{"role": "system", "content": system_prompt}]
        messages.extend(self.conversation_history)

        # Call Ollama API
        response = requests.post(
            f"{self.ollama_url}/api/chat",
            json={
                "model": self.model,
                "messages": messages,
                "stream": False,
                "options": {
                    "temperature": 0.7,
                    "num_predict": 500,
                }
            },
            timeout=30
        )

        if response.status_code != 200:
            raise Exception(f"Ollama error: {response.status_code}")

        result = response.json()
        response_text = result["message"]["content"].strip()
        return self._parse_response(response_text)

    def _parse_response(self, response_text: str) -> Dict[str, Any]:
        """Parse JSON response from LLM."""
        try:
            # Handle markdown code blocks
            if response_text.startswith("```"):
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

            # Try to extract JSON from response (handle extra chars)
            import re
            json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
            if json_match:
                response_text = json_match.group()

            result = json.loads(response_text)

            # Validate structure
            if "speech" not in result:
                result["speech"] = "I processed your request."
            if "actions" not in result:
                result["actions"] = []

        except json.JSONDecodeError as e:
            print(f"JSON parse error: {e}")
            print(f"Raw response: {response_text[:200]}")
            # If JSON parsing fails, treat the whole response as speech
            result = {"speech": response_text, "actions": []}

        # Add assistant response to history
        self._add_to_history("assistant", json.dumps(result))

        print(f"Response: {result['speech']}")
        if result['actions']:
            print(f"Actions: {result['actions']}")

        return result

    def clear_history(self):
        """Clear conversation history."""
        self.conversation_history = []
        print("Conversation history cleared")
