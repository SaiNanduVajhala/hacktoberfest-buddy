"""
core.py – Conversation logic (state machine), independent of any UI.

The main entry point is `handle_message(user_id, text) -> str`.
It manages the user's stage and dispatches to the right handler.
No fallbacks — every LLM call must produce valid output or be retried.
"""

import json
import re

from buddy import llm, memory, prompts
from buddy.github_api import search_issues, repo_brief, GitHubRateLimitError, GitHubAPIError

# How many times to retry the LLM when it returns unparseable JSON
_LLM_PARSE_RETRIES = 2


# ── Helpers ───────────────────────────────────────────────────────────

def _parse_json(text: str) -> list | dict | None:
    """
    Try to parse JSON from an LLM response.
    Strips markdown code fences if present, then attempts json.loads.
    Returns None on failure.
    """
    # Remove ```json ... ``` or ``` ... ```
    cleaned = re.sub(r"^```(?:json)?\s*\n?", "", text.strip(), flags=re.MULTILINE)
    cleaned = re.sub(r"\n?```\s*$", "", cleaned.strip(), flags=re.MULTILINE)
    try:
        return json.loads(cleaned)
    except (json.JSONDecodeError, ValueError):
        return None


def _llm_json(system: str, user_prompt: str, expect_type: type, temperature: float = 0.3) -> dict | list:
    """
    Call the LLM and parse the response as JSON. Retry up to
    _LLM_PARSE_RETRIES times if parsing fails. Raises RuntimeError
    if all attempts fail — no silent fallback.
    """
    last_raw = ""
    for attempt in range(1, _LLM_PARSE_RETRIES + 1):
        raw = llm.chat(system, user_prompt, temperature=temperature)
        last_raw = raw
        parsed = _parse_json(raw)
        if isinstance(parsed, expect_type):
            return parsed
        # On retry, lower temperature to encourage stricter output
        temperature = max(0.1, temperature - 0.1)
    raise RuntimeError(
        f"🤖 The LLM did not return valid JSON after {_LLM_PARSE_RETRIES} attempts.\n"
        f"   Last response (first 300 chars): {last_raw[:300]}"
    )


def _format_issue_list(ranked: list[dict]) -> str:
    """Format ranked issues into a readable numbered list."""
    lines = []
    for i, item in enumerate(ranked, 1):
        reason = item.get("reason", "")
        url = item.get("url", "")
        title = item.get("title", "")
        line = f"**{i}. {title}**\n🔗 {url}"
        if reason:
            line += f"\n💡 _{reason}_"
        lines.append(line)
    return "\n\n".join(lines)


def _format_issues_for_llm(issues: list[dict]) -> str:
    """Format raw issue dicts into a text block for the ranking prompt."""
    lines = []
    for i, iss in enumerate(issues, 1):
        lines.append(
            f"{i}. [{iss['repo']}] {iss['title']}\n"
            f"   URL: {iss['url']}\n"
            f"   Labels: {', '.join(iss['labels'])}\n"
            f"   Comments: {iss['comments']} | Updated: {iss['updated']}\n"
            f"   Snippet: {iss['body_snippet'][:200]}"
        )
    return "\n\n".join(lines)


def _detect_intent(text: str) -> tuple[str, str]:
    """
    Detect the user's intent from their message.
    Returns (intent, argument).

    Intents: "more", "pick", "pr", "profile", "reset", "freetext"
    """
    t = text.strip().lower()

    if t in ("/more", "more", "show more", "next"):
        return "more", ""

    if t in ("/profile", "profile", "show profile"):
        return "profile", ""

    if t in ("/reset", "reset", "start over"):
        return "reset", ""

    if t in ("/pr", "pr", "draft pr"):
        return "pr", ""

    # "commands" or "setup"
    if t in ("/commands", "commands", "/setup", "setup", "git commands", "how to clone"):
        return "commands", ""

    # "details 2", "detail #2", "describe 1", "explain 2"
    m = re.match(r"(?:/)?(?:details?|describe|explain|info)\s*#?(\d+)?", t)
    if m:
        return "details", m.group(1) or ""

    # Natural language: "tell me more about 2", "more details on #1"
    m = re.search(r"(?:details?|describe|explain|tell me more|more info).*(?:#|number\s*)?(\d+)", t)
    if m:
        return "details", m.group(1)

    # "pick 2" or "pick #2"
    m = re.match(r"(?:/)?pick\s*#?(\d+)", t)
    if m:
        return "pick", m.group(1)

    # Pasted GitHub issue URL
    m = re.search(r"(https://github\.com/[\w\-\.]+/[\w\-\.]+/issues/\d+)", text)
    if m:
        return "pick_url", m.group(1)

    return "freetext", text


# ── Main handler ──────────────────────────────────────────────────────

def handle_message(user_id: str, text: str) -> str:
    """
    Process a user message and return the bot's reply.
    This is the single entry point called by both CLI and Telegram.
    """
    prof = memory.load(user_id)
    intent, arg = _detect_intent(text)

    try:
        # ── Global commands (work in any stage) ───────────────────
        if intent == "profile":
            return _show_profile(prof)

        if intent == "reset":
            memory.reset(user_id)
            return "🔄 Profile cleared! Tell me about yourself to start fresh."

        # ── Stage-based routing ───────────────────────────────────
        stage = prof.get("stage", "NEW")

        if stage == "NEW":
            return _handle_new_user(user_id, prof, text)

        if intent == "more":
            return _handle_more(user_id, prof)

        if intent in ("details", "commands"):
            return _handle_details(user_id, prof, arg)

        if intent in ("pick", "pick_url"):
            return _handle_pick(user_id, prof, intent, arg)

        if intent == "pr":
            if stage == "PR_DRAFT":
                return _handle_pr_summary(user_id, prof, text)
            # Transition to PR_DRAFT stage
            prof["stage"] = "PR_DRAFT"
            memory.save(user_id, prof)
            return (
                "📝 Tell me what you changed (a short summary or paste your diff), "
                "and I'll draft a PR description for you."
            )

        if stage == "PR_DRAFT":
            return _handle_pr_summary(user_id, prof, text)

        # Profiled user sending free text → re-profile with updated info
        if stage in ("PROFILED", "SHOWN_OPTIONS", "ISSUE_CHOSEN"):
            if prof.get("skills") and intent == "freetext":
                # User is saying something new – might be updating skills
                # or just chatting. Re-extract and search.
                return _handle_new_user(user_id, prof, text)
            return _handle_more(user_id, prof)

        return _handle_new_user(user_id, prof, text)

    except GitHubRateLimitError as e:
        return str(e)
    except GitHubAPIError as e:
        return f"⚠️ GitHub error: {e}"
    except RuntimeError as e:
        return str(e)
    except Exception as e:
        return f"❌ Something went wrong: {e}\nPlease try again."


# ── Stage handlers ────────────────────────────────────────────────────

def _handle_new_user(user_id: str, prof: dict, text: str) -> str:
    """Extract profile from intro message, then search and rank issues."""
    # Ask the LLM to extract skills – retry if it doesn't return valid JSON
    prompt = prompts.EXTRACT_PROFILE.format(message=text)
    parsed = _llm_json(prompts.SYSTEM, prompt, expect_type=dict)

    prof["skills"] = parsed.get("skills", [])
    prof["level"] = parsed.get("level", "beginner")
    prof["time_available"] = parsed.get("time_available", "")

    if not prof["skills"]:
        raise RuntimeError(
            "🤔 I couldn't identify any programming skills from your message.\n"
            "   Try something like: \"I know Python and JavaScript, I have 2 hours\""
        )

    prof["stage"] = "PROFILED"
    memory.save(user_id, prof)

    # Now search and rank
    return _search_and_rank(user_id, prof)


def _search_and_rank(user_id: str, prof: dict) -> str:
    """Search GitHub for issues and ask the LLM to rank the top 3."""
    languages = prof.get("skills", [])
    if not languages:
        raise RuntimeError(
            "🤔 No skills on your profile. Tell me what languages you know!"
        )

    exclude = set(prof.get("shown_urls", []))
    issues = search_issues(languages, limit=10, exclude_urls=exclude)

    if not issues:
        return (
            "🔍 No open issues found matching your skills right now.\n"
            "Try broadening your languages (e.g. add JavaScript, TypeScript, Go) "
            "or check back later!"
        )

    # Ask the LLM to rank – retry if it doesn't return valid JSON list
    issues_text = _format_issues_for_llm(issues)
    prompt = prompts.RANK_ISSUES.format(
        skills=", ".join(prof.get("skills", [])),
        level=prof.get("level", "beginner"),
        time=prof.get("time_available", "unknown"),
        issues_text=issues_text,
    )
    ranked = _llm_json(prompts.SYSTEM, prompt, expect_type=list, temperature=0.3)

    if len(ranked) == 0:
        raise RuntimeError(
            "🤖 The LLM returned an empty ranking. This shouldn't happen.\n"
            "   Please try again."
        )

    # Enrich with titles from search results
    url_to_title = {iss["url"]: iss["title"] for iss in issues}
    for item in ranked:
        if "title" not in item or not item["title"]:
            item["title"] = url_to_title.get(item.get("url", ""), "")

    # Save to memory – store ranked issues for "pick N"
    new_urls = [item["url"] for item in ranked if item.get("url")]
    memory.add_shown_urls(user_id, new_urls)

    prof = memory.load(user_id)
    prof["stage"] = "SHOWN_OPTIONS"
    prof["_last_ranked"] = ranked  # ephemeral, for "pick N"
    memory.save(user_id, prof)

    header = (
        f"🎯 Based on your skills ({', '.join(prof.get('skills', []))}) "
        f"here are the best issues for you:\n\n"
    )
    return header + _format_issue_list(ranked) + (
        "\n\n💡 **What now?** Reply with:\n"
        "- `pick 1`, `pick 2`, or `pick 3` to get step-by-step guidance & copy-paste git commands\n"
        "- `details 1`, `details 2`, or `details 3` for a deep architectural description\n"
        "- A GitHub issue URL to explore any specific issue\n"
        "- `more` for more suggestions\n"
        "- `profile` to see your saved skills"
    )


def _handle_more(user_id: str, prof: dict) -> str:
    """Show the next batch of issues."""
    return _search_and_rank(user_id, prof)


def _handle_details(user_id: str, prof: dict, arg: str) -> str:
    """Provide an in-depth technical description and tailored Git setup."""
    issue_url = None

    if arg and arg.isdigit():
        idx = int(arg) - 1
        last_ranked = prof.get("_last_ranked", [])
        if 0 <= idx < len(last_ranked):
            issue_url = last_ranked[idx].get("url", "")
        else:
            return f"❌ Choose an issue number between 1 and {len(last_ranked)}."
    elif prof.get("_current_issue"):
        issue_url = prof.get("_current_issue")
    elif prof.get("_last_ranked"):
        issue_url = prof["_last_ranked"][0].get("url", "")

    if not issue_url:
        return "❌ Which issue would you like detailed info on? Try `details 1`, `details 2`, or paste a GitHub URL."

    # Mark as tried
    memory.mark_tried(user_id, issue_url)

    # Fetch full repo context
    context = repo_brief(issue_url)

    # Ask the LLM for deep technical breakdown
    prompt = prompts.DETAILED_DESCRIPTION.format(context=context)
    reply = llm.chat(prompts.SYSTEM, prompt, temperature=0.3)

    prof = memory.load(user_id)
    prof["stage"] = "ISSUE_CHOSEN"
    prof["_current_issue"] = issue_url
    memory.save(user_id, prof)

    footer = (
        "\n\n---\n"
        "💡 **Next steps:**\n"
        "- `pick` to see concise checklist & claim comment\n"
        "- `pr` when you are ready to draft your Pull Request\n"
        "- `more` to explore other open issues"
    )
    return reply + footer


def _handle_pick(user_id: str, prof: dict, intent: str, arg: str) -> str:
    """User picked an issue by number or URL."""
    issue_url = None

    if intent == "pick_url":
        issue_url = arg
    elif intent == "pick":
        idx = int(arg) - 1
        last_ranked = prof.get("_last_ranked", [])
        if 0 <= idx < len(last_ranked):
            issue_url = last_ranked[idx].get("url", "")
        else:
            return f"❌ Pick a number between 1 and {len(last_ranked)}."

    if not issue_url:
        return "❌ Couldn't determine which issue you want. Paste the GitHub URL or use `pick 1/2/3`."

    # Mark as tried
    memory.mark_tried(user_id, issue_url)

    # Fetch repo context
    context = repo_brief(issue_url)

    # Ask the LLM to explain
    prompt = prompts.EXPLAIN_ISSUE.format(context=context)
    reply = llm.chat(prompts.SYSTEM, prompt, temperature=0.4)

    prof = memory.load(user_id)
    prof["stage"] = "ISSUE_CHOSEN"
    prof["_current_issue"] = issue_url
    memory.save(user_id, prof)

    footer = (
        "\n\n---\n"
        "💡 **Next steps:**\n"
        "- `details` for a deeper architectural breakdown\n"
        "- `pr` when you're ready to draft a PR description\n"
        "- `more` to see other issues\n"
        "- Paste another issue URL to explore it"
    )
    return reply + footer


def _handle_pr_summary(user_id: str, prof: dict, text: str) -> str:
    """Draft a PR description from the user's summary."""
    issue_url = prof.get("_current_issue", "")
    issue_number = ""
    m = re.search(r"/issues/(\d+)", issue_url)
    if m:
        issue_number = m.group(1)

    prompt = prompts.PR_DESCRIPTION.format(
        issue_url=issue_url,
        issue_number=issue_number if issue_number else "N/A",
        summary=text,
    )
    reply = llm.chat(prompts.SYSTEM, prompt, temperature=0.3)

    prof["stage"] = "SHOWN_OPTIONS"
    memory.save(user_id, prof)

    return (
        "📋 **Here's your draft PR description:**\n\n"
        + reply
        + "\n\n---\n"
        "✏️ Copy and paste this when you open your PR. "
        "Feel free to edit it to match your actual changes!\n"
        "Type `more` to find another issue."
    )


def _show_profile(prof: dict) -> str:
    """Return a readable summary of the user's profile."""
    if not prof.get("skills"):
        return "No profile saved yet. Tell me about your skills to get started!"

    lines = [
        "👤 **Your Profile**",
        f"- **Skills**: {', '.join(prof['skills'])}",
        f"- **Level**: {prof.get('level', 'unknown')}",
        f"- **Time**: {prof.get('time_available', 'not set')}",
        f"- **Issues shown**: {len(prof.get('shown_urls', []))}",
        f"- **Issues tried**: {len(prof.get('tried', []))}",
    ]
    return "\n".join(lines)
