#!/usr/bin/env python3
"""
telegram_bot.py – Telegram interface for Hacktoberfest Buddy.

Uses python-telegram-bot v20+ (async).
Handlers: /start, /help, /profile, /reset, and generic text → core.handle_message().
"""

import html
import logging
import re
from telegram import Update
from telegram.constants import ChatAction, ParseMode
from telegram.request import HTTPXRequest
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
)

from buddy.config import TELEGRAM_BOT_TOKEN
from buddy.core import handle_message

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Max Telegram message length
MAX_MSG_LEN = 4000

HELP_TEXT = (
    "🎃 **Hacktoberfest Buddy** – Your AI open-source mentor\n\n"
    "Tell me your skills and I'll find great first issues for you!\n\n"
    "**Commands:**\n"
    "• Just type your skills: _'I know Python, 2 hours free'_\n"
    "• `more` – see more issues\n"
    "• `pick 1` / `pick 2` / `pick 3` – dive into an issue\n"
    "• Paste a GitHub issue URL – explore any issue\n"
    "• `pr` – draft a PR description\n"
    "• /profile – see your saved skills\n"
    "• /reset – start over\n"
    "• /help – show this message"
)


def _md_to_html(text: str) -> str:
    """Convert light markdown to clean, safe Telegram HTML."""
    # 1. Escape HTML special characters
    escaped = html.escape(text)

    # 2. Code blocks ```lang\ncode\n```
    def repl_block(m):
        code_content = m.group(1).strip()
        return f"<pre><code>{code_content}</code></pre>"
    escaped = re.sub(r"```(?:[a-zA-Z0-9_\-]+)?\n?(.*?)```", repl_block, escaped, flags=re.DOTALL)

    # 3. Inline code `code`
    escaped = re.sub(r"`([^`\n]+)`", r"<code>\1</code>", escaped)

    # 4. Markdown headers #, ##, ###
    escaped = re.sub(r"^(?:#{1,6})\s+(.+)$", r"<b>\1</b>", escaped, flags=re.MULTILINE)

    # 5. Bold **text**
    escaped = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", escaped)

    # 6. Italic _text_
    escaped = re.sub(r"(?:^|(?<=\s))_([^_]+)_(?=\s|$|[.,:;!?])", r"<i>\1</i>", escaped)

    # 7. Unordered list markers - or * at start of line -> bullet
    escaped = re.sub(r"^[ \t]*[-*][ \t]+", "• ", escaped, flags=re.MULTILINE)

    return escaped


async def _send_long(update: Update, text: str):
    """Send a reply with rich HTML formatting, splitting if it exceeds Telegram's limit."""
    formatted = _md_to_html(text)
    while formatted:
        chunk = formatted[:MAX_MSG_LEN]
        formatted = formatted[MAX_MSG_LEN:]
        try:
            await update.message.reply_text(
                chunk,
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
            )
        except Exception as e:
            logger.warning(f"HTML parse failed ({e}), falling back to plain text")
            plain_chunk = text[:MAX_MSG_LEN]
            text = text[MAX_MSG_LEN:]
            await update.message.reply_text(plain_chunk, disable_web_page_preview=True)


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start."""
    start_text = (
        "👋 Welcome to **Hacktoberfest Buddy**!\n\n"
        "I'm your AI mentor for making your first open-source contribution.\n\n"
        "Tell me about yourself — your skills, experience level, and how much time you have. "
        "For example:\n\n"
        "• _\"I know Python and a bit of React, I have 2 hours\"_\n"
        "• _\"Beginner in JavaScript, looking for an easy issue\"_"
    )
    await _send_long(update, start_text)


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /help."""
    await _send_long(update, HELP_TEXT)


async def cmd_profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /profile."""
    user_id = str(update.effective_user.id)
    reply = handle_message(user_id, "profile")
    await _send_long(update, reply)


async def cmd_reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /reset."""
    user_id = str(update.effective_user.id)
    reply = handle_message(user_id, "reset")
    await _send_long(update, reply)


async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle any text message → route through core."""
    user_id = str(update.effective_user.id)
    text = update.message.text.strip()

    if not text:
        return

    # Immediately send ETA notification to the user
    eta_msg = await update.message.reply_text(
        "⏳ On it! Searching GitHub and consulting your mentor... (ETA: ~10-15 seconds)"
    )

    # Show "typing" indicator in background
    await update.message.chat.send_action(ChatAction.TYPING)

    try:
        reply = handle_message(user_id, text)
    except Exception as e:
        logger.exception("Error handling message")
        reply = f"😅 Something went wrong: {e}\nPlease try again or /reset to start over."

    # Remove the ETA placeholder and deliver final response
    try:
        await eta_msg.delete()
    except Exception:
        pass

    await _send_long(update, reply)


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE):
    """Log errors and notify user."""
    logger.error("Exception while handling update:", exc_info=context.error)
    if isinstance(update, Update) and update.message:
        await update.message.reply_text(
            "😅 An unexpected error occurred. Please try again or /reset."
        )


def main():
    if not TELEGRAM_BOT_TOKEN:
        print(
            "❌ TELEGRAM_BOT_TOKEN is not set.\n"
            "   1. Talk to @BotFather on Telegram to create a bot.\n"
            "   2. Add the token to your .env file.\n"
        )
        return

    request = HTTPXRequest(connect_timeout=20.0, read_timeout=30.0)
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).request(request).build()

    # Register handlers
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("profile", cmd_profile))
    app.add_handler(CommandHandler("reset", cmd_reset))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    app.add_error_handler(on_error)

    print("🤖 Telegram bot is running! Press Ctrl+C to stop.")
    app.run_polling()


if __name__ == "__main__":
    main()
