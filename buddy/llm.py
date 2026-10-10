"""
llm.py – Thin wrapper around the OpenAI-compatible Ollama API.

Provides a single `chat()` function with retries and clear error messages
for local Ollama setups (connection issues, model missing, timeouts).
"""

import time
from openai import OpenAI, APIError, APIConnectionError

from buddy.config import OLLAMA_BASE_URL, OLLAMA_MODEL

# Client configured for local Ollama OpenAI-compatible endpoint
_client = OpenAI(
    base_url=OLLAMA_BASE_URL,
    api_key="ollama",  # Ollama does not require auth, but OpenAI client expects a non-empty key
)


def chat(system: str, user: str, temperature: float = 0.3, max_retries: int = 2) -> str:
    """
    Send a system + user message to local Ollama and return the
    assistant's reply as a string.

    Provides friendly troubleshooting steps if Ollama is not yet running
    or the selected model has not been pulled.
    """
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]

    last_err = None
    for attempt in range(1, max_retries + 2):
        try:
            resp = _client.chat.completions.create(
                model=OLLAMA_MODEL,
                messages=messages,
                temperature=temperature,
                max_tokens=2048,
            )
            content = resp.choices[0].message.content
            return (content or "").strip()

        except APIConnectionError as e:
            raise RuntimeError(
                f"🦙 Cannot connect to Ollama at {OLLAMA_BASE_URL}.\n"
                "   Please check that Ollama is running:\n"
                "   1. Start Ollama on your machine (https://ollama.com)\n"
                f"   2. Pull the model:  ollama pull {OLLAMA_MODEL}\n"
                "   3. Verify with:     ollama list"
            ) from e

        except APIError as e:
            last_err = e
            msg = str(e).lower()
            if "model" in msg and ("not found" in msg or "try pulling" in msg):
                raise RuntimeError(
                    f"🦙 Model '{OLLAMA_MODEL}' was not found in your Ollama installation.\n"
                    f"   Run this command in your terminal to download it:\n"
                    f"   ollama pull {OLLAMA_MODEL}"
                ) from e

            if attempt <= max_retries and e.status_code and e.status_code >= 500:
                wait = 2 ** attempt
                print(f"⏳ Server error ({e.status_code}), retrying in {wait}s...")
                time.sleep(wait)
            else:
                raise RuntimeError(f"🤖 Ollama API error: {e}") from e

        except Exception as e:
            raise RuntimeError(
                f"🌐 Unexpected error calling Ollama:\n   {e}"
            ) from e

    raise RuntimeError(
        f"🚫 Ollama request failed after {max_retries + 1} attempts.\n"
        f"   Last error: {last_err}"
    )
