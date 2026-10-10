"""
memory.py – Per-user JSON profile storage.

Stores a JSON file per user in the memory/ directory.
Tracks skills, level, time available, shown issue URLs,
and tried issues with their status.
"""

import json
import os
from pathlib import Path

MEMORY_DIR = Path(__file__).resolve().parent.parent / "memory"


def _ensure_dir():
    """Create the memory/ directory if it doesn't exist."""
    MEMORY_DIR.mkdir(parents=True, exist_ok=True)


def _path(user_id: str) -> Path:
    """Return the path to a user's profile JSON file."""
    # Sanitize user_id to be a safe filename
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in str(user_id))
    return MEMORY_DIR / f"{safe}.json"


def _blank_profile() -> dict:
    """Return a fresh, empty user profile."""
    return {
        "skills": [],
        "level": "",
        "time_available": "",
        "shown_urls": [],
        "tried": [],          # [{url, status}]
        "stage": "NEW",       # conversation state
    }


def load(user_id: str) -> dict:
    """Load a user's profile, returning a blank one if none exists."""
    _ensure_dir()
    p = _path(user_id)
    if p.exists():
        try:
            with open(p, "r", encoding="utf-8") as f:
                data = json.load(f)
            # Ensure all expected keys exist (forward-compat)
            blank = _blank_profile()
            for k, v in blank.items():
                data.setdefault(k, v)
            return data
        except (json.JSONDecodeError, IOError):
            return _blank_profile()
    return _blank_profile()


def save(user_id: str, profile: dict):
    """Persist a user profile to disk."""
    _ensure_dir()
    p = _path(user_id)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(profile, f, indent=2, ensure_ascii=False)


def add_shown_urls(user_id: str, urls: list[str]):
    """Add URLs to the user's shown list (avoids repeats)."""
    prof = load(user_id)
    existing = set(prof["shown_urls"])
    for u in urls:
        if u not in existing:
            prof["shown_urls"].append(u)
    save(user_id, prof)


def mark_tried(user_id: str, url: str, status: str = "picked"):
    """Record that the user picked/tried an issue."""
    prof = load(user_id)
    # Update if already exists, otherwise add
    for entry in prof["tried"]:
        if entry["url"] == url:
            entry["status"] = status
            save(user_id, prof)
            return
    prof["tried"].append({"url": url, "status": status})
    save(user_id, prof)


def reset(user_id: str):
    """Delete a user's profile entirely."""
    p = _path(user_id)
    if p.exists():
        p.unlink()
