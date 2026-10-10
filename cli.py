#!/usr/bin/env python3
"""
cli.py – Interactive terminal interface for Hacktoberfest Buddy.

Simple read-eval-print loop that calls core.handle_message().
"""

import sys

# Fix Windows encoding: force UTF-8 on stdout/stderr so emoji and
# special characters render correctly instead of crashing with cp1252.
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from buddy.core import handle_message

WELCOME = """
============================================================
  Hacktoberfest Buddy - CLI
  Your AI mentor for first open-source contributions.

  Tell me about yourself:
    "I know Python and a bit of React, I have 2 hours"

  Commands: more, pick N, pr, profile, reset
  Press Ctrl+C to exit.
============================================================
"""


def main():
    print(WELCOME)
    user_id = "cli"

    try:
        while True:
            try:
                text = input("\nYou: ").strip()
            except EOFError:
                break

            if not text:
                continue

            print("\n⏳ On it! Searching GitHub and consulting your mentor... (ETA: ~10-15s)\n")
            reply = handle_message(user_id, text)
            print(reply)

    except KeyboardInterrupt:
        print("\n\nGoodbye! Happy hacking!")


if __name__ == "__main__":
    main()
