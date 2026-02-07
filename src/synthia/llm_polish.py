"""LLM-based transcription polishing for improved dictation accuracy."""

from __future__ import annotations

import logging
from typing import Optional

import requests

logger = logging.getLogger(__name__)

POLISH_PROMPT = """You are a transcription correction assistant. Your ONLY job is to fix speech recognition errors in the following transcription.

RULES:
1. Fix obvious speech recognition errors (homophones, misheard words)
2. Fix technical terms, proper nouns, and programming terminology
3. Preserve the exact meaning and intent - do NOT add, remove, or rephrase content
4. Preserve punctuation style (if no punctuation, don't add any)
5. Preserve capitalization patterns from the original
6. If the transcription looks correct, return it unchanged
7. NEVER explain your changes - output ONLY the corrected text

Common fixes needed:
- "their/there/they're" based on context
- Programming terms: "python" not "pie thon", "github" not "get hub"
- Technical words often misheard by speech recognition

Original transcription:
{transcription}

Corrected transcription (output ONLY the text, nothing else):"""


class TranscriptionPolisher:
    """Polishes transcriptions using a local LLM to fix recognition errors."""

    def __init__(
        self,
        ollama_url: str = "http://localhost:11434",
        model: str = "qwen2.5:7b-instruct-q4_0",
        timeout: float = 3.0,
        enabled: bool = True,
    ):
        self.ollama_url = ollama_url
        self.model = model
        self.timeout = timeout
        self.enabled = enabled

    def polish(self, transcription: str) -> str:
        """Polish a transcription using the LLM.

        Returns the original transcription on any error (fail-safe).
        """
        if not self.enabled or not transcription.strip():
            return transcription

        try:
            return self._call_ollama(transcription)
        except Exception as e:
            logger.debug("LLM polish error (using original): %s", e)
            return transcription

    def _call_ollama(self, transcription: str) -> str:
        """Make the Ollama API call."""
        response = requests.post(
            f"{self.ollama_url}/api/generate",
            json={
                "model": self.model,
                "prompt": POLISH_PROMPT.format(transcription=transcription),
                "stream": False,
                "options": {
                    "temperature": 0.1,
                    "num_predict": len(transcription) + 50,
                    "top_p": 0.9,
                },
            },
            timeout=self.timeout,
        )

        if response.status_code != 200:
            raise Exception(f"Ollama returned {response.status_code}")

        result = response.json()
        polished = result.get("response", "").strip()

        # Sanity check: if LLM returns something wildly different, use original
        if not polished or len(polished) > len(transcription) * 2:
            return transcription

        return str(polished)
