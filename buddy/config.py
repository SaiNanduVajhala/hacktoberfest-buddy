"""
config.py – Loads environment variables and validates configuration.

Configured for local Ollama via its OpenAI-compatible endpoint.
"""

import os
from dotenv import load_dotenv

# Load .env from project root
load_dotenv()

# ── Ollama Configuration ──────────────────────────────────────────────
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen3:0.6b")

# ── Optional ──────────────────────────────────────────────────────────
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
