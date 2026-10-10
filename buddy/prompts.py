"""
prompts.py – All LLM prompt templates as constants.

Keeping prompts here makes them easy to review, tweak, and test
without touching logic code.
"""

# ── System prompt (used for ALL LLM calls) ────────────────────────────
SYSTEM = """\
You are Hacktoberfest Buddy, a patient and honest open-source mentor.

Rules you MUST follow:
- Never claim an issue is easy unless you have actually read the issue body and repo context.
- Never fabricate repository details; if the provided context lacks something, say so.
- Discourage spam and low-effort PRs. Quality over quantity.
- Always remind users to read and follow each project's CONTRIBUTING guide and any AI-contribution policy.
- Never submit anything (PRs, comments, code) on the user's behalf.
- Keep replies concise and scannable. Use light markdown (bold, bullets, numbered lists) that looks fine in both a terminal and Telegram. Avoid tables.
"""

# ── Extract user profile from their intro message ─────────────────────
EXTRACT_PROFILE = """\
The user just introduced themselves. Extract the following as strict JSON (no markdown fences):
{{
  "skills": ["list", "of", "languages/frameworks"],
  "level": "beginner|intermediate|advanced",
  "time_available": "e.g. 2 hours"
}}

Only output the JSON object, nothing else.

User message:
{message}
"""

# ── Rank issues for the user ──────────────────────────────────────────
RANK_ISSUES = """\
You are helping a contributor find their first open-source issue.

**User profile:**
- Skills: {skills}
- Level: {level}
- Time available: {time}

**Candidate issues (up to 10):**
{issues_text}

Pick the BEST 3 issues for this user. Prefer:
- Recently updated, clearly described issues
- Few existing comments (less competition)
- Matches the user's skill level and time budget
- Skip vague, stale, or overly complex issues

Return strict JSON (no markdown fences, no extra text):
[
  {{"url": "...", "reason": "one-line why this fits"}},
  {{"url": "...", "reason": "..."}},
  {{"url": "...", "reason": "..."}}
]
"""

# ── Explain an issue + repo with reasoning-driven Git commands ────────
EXPLAIN_ISSUE = """\
The user picked an issue to work on. Carefully inspect the provided repository context (README, CONTRIBUTING, issues, languages, dependencies, and configuration).

Provide the following structured guide:

1. **What this project does** – plain language explanation of the repository's purpose and tech stack.
2. **What the issue asks for** – clear breakdown of the problem and expected outcome.
3. **Step-by-step contribution plan:**
   1. Forking & local repository setup
   2. Where to look in the codebase (mark guesses as "likely" or "best guess")
   3. What to change
   4. How to test (using the project's real test commands if found in README/CONTRIBUTING)
   5. Common pitfalls & gotchas
4. **🚀 One-Click Terminal Commands:**
   Reason over the repository's actual language, package manager, and build tool (e.g., npm/pnpm/yarn, pip/poetry/uv, cargo, go, maven, etc.) and synthesize an issue-specific branch name. DO NOT use a static template. Synthesize a single copy-paste bash block tailored specifically to this issue and repo:
   ```bash
   # Clone, setup branch, install dependencies, and run tests
   ...
   ```
5. **CONTRIBUTING rules they must follow** (from the context; say "none specified" if absent).
6. **Draft comment to claim the issue** – polite, concise, mentioning their intended approach.

Repo & issue context:
{context}
"""

# ── Detailed deep-dive description on demand ──────────────────────────
DETAILED_DESCRIPTION = """\
The user requested a detailed, in-depth technical description of this repository and issue.
Analyze the context below and provide a comprehensive deep-dive:

1. **Architecture & Project Overview**: What is the application, how is it structured, and what technologies/frameworks does it rely on?
2. **Issue Deep Dive**: Detailed analysis of the reported bug or requested feature. What is the current behavior vs intended behavior?
3. **Affected Components & Files**: Which files, modules, or directories are most likely involved based on the codebase clues?
4. **Key Concepts & Prerequisites**: What domain knowledge or language features should the contributor know before tackling this?
5. **🚀 One-Click Terminal Commands**:
   Reason over the context to provide the exact, tailored terminal commands for cloning, creating an issue-specific branch, installing dependencies, and running tests. DO NOT use a generic placeholder template; reason dynamically based on the project's actual tools.
6. **Testing & Verification Strategy**: How can the contributor verify their fix works without breaking existing functionality?

Repo & issue context:
{context}
"""

# ── Draft a PR description ────────────────────────────────────────────
PR_DESCRIPTION = """\
The user wants to draft a PR description. They described their change below.

Write a PR description with these sections:
- **What this changes**
- **Why** (include "Fixes #{issue_number}" if the issue number is known)
- **How I tested it**
- **Notes** (optional, e.g. anything reviewers should know)

Keep it concise and professional.

Issue URL: {issue_url}
User's description of their change:
{summary}
"""
