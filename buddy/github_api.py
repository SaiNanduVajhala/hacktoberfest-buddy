"""
github_api.py – GitHub search and repo context fetching.

Uses only `requests`. Authenticates with GITHUB_TOKEN if available,
otherwise falls back to unauthenticated (lower rate limits).
"""

import base64
import time
import requests
from buddy.config import GITHUB_TOKEN

# ── HTTP helpers ──────────────────────────────────────────────────────

_SESSION = requests.Session()
_SESSION.headers.update({
    "Accept": "application/vnd.github+json",
    "User-Agent": "hacktoberfest-buddy/1.0",
})
if GITHUB_TOKEN:
    _SESSION.headers["Authorization"] = f"Bearer {GITHUB_TOKEN}"


class GitHubRateLimitError(Exception):
    """Raised when GitHub returns 403/429 due to rate limiting."""
    pass


class GitHubAPIError(Exception):
    """Raised for other GitHub API errors."""
    pass


def _get(url: str, params: dict = None, allow_retry: bool = True) -> dict:
    """GET a GitHub API URL; handle rate-limit and error responses."""
    resp = _SESSION.get(url, params=params, timeout=15)

    if resp.status_code in (403, 429):
        # Check for Retry-After header (common for GitHub secondary rate limits)
        retry_after = resp.headers.get("Retry-After")
        if retry_after and allow_retry:
            try:
                wait_sec = min(int(retry_after), 10)
                time.sleep(wait_sec)
                return _get(url, params=params, allow_retry=False)
            except Exception:
                pass

        msg = resp.json().get("message", resp.text)
        if "rate limit" in msg.lower():
            hint = ""
            if not GITHUB_TOKEN:
                hint = "\n   💡 Set GITHUB_TOKEN in .env to raise your rate limit."
            raise GitHubRateLimitError(
                f"⚠️ GitHub rate limit hit: {msg}{hint}"
            )
        raise GitHubAPIError(f"GitHub {resp.status_code}: {msg}")

    if resp.status_code == 404:
        return None  # resource not found (valid for optional files like CONTRIBUTING)

    if resp.status_code >= 400:
        msg = resp.json().get("message", resp.text) if resp.headers.get("content-type", "").startswith("application/json") else resp.text
        raise GitHubAPIError(f"GitHub {resp.status_code}: {msg}")

    return resp.json()


# ── Issue search ──────────────────────────────────────────────────────

def search_issues(
    languages: list[str],
    labels: list[str] = None,
    limit: int = 10,
    exclude_urls: set = None,
) -> list[dict]:
    """
    Search GitHub for open, unassigned issues matching the given
    languages and labels. Returns deduplicated results sorted by
    updated_at descending.

    Each result dict:
      title, url, repo, labels, comments, updated, body_snippet
    """
    if labels is None:
        labels = ["good first issue", "hacktoberfest"]
    if exclude_urls is None:
        exclude_urls = set()

    seen_urls = set()
    results = []

    for lang in languages:
        for label in labels:
            if len(results) >= limit * 2:
                break  # We already have plenty of candidates for LLM ranking

            # Build the search query
            q = (
                f'label:"{label}" is:issue is:open '
                f"no:assignee -linked:pr archived:false language:{lang}"
            )
            data = _get(
                "https://api.github.com/search/issues",
                params={
                    "q": q,
                    "sort": "updated",
                    "order": "desc",
                    "per_page": 15,
                },
            )
            time.sleep(0.5)  # Pace queries to avoid GitHub secondary rate limits

            for item in data.get("items", []):
                url = item["html_url"]
                if url in seen_urls or url in exclude_urls:
                    continue
                seen_urls.add(url)

                # Parse owner/repo from repository_url
                # e.g. "https://api.github.com/repos/owner/name"
                repo = "/".join(item["repository_url"].rsplit("/", 2)[-2:])

                body = item.get("body") or ""
                results.append({
                    "title": item["title"],
                    "url": url,
                    "repo": repo,
                    "labels": [l["name"] for l in item.get("labels", [])],
                    "comments": item.get("comments", 0),
                    "updated": item.get("updated_at", ""),
                    "body_snippet": body[:500],
                })

    # Sort by most recently updated first
    results.sort(key=lambda r: r["updated"], reverse=True)
    return results[:limit]


# ── Repo brief ────────────────────────────────────────────────────────

def _try_contributing(owner: str, repo: str) -> str:
    """Try to fetch CONTRIBUTING.md from common locations. Returns '' if not found."""
    paths = [
        "CONTRIBUTING.md",
        ".github/CONTRIBUTING.md",
        "docs/CONTRIBUTING.md",
    ]
    for path in paths:
        url = f"https://api.github.com/repos/{owner}/{repo}/contents/{path}"
        data = _get(url)
        if data and data.get("content"):
            text = base64.b64decode(data["content"]).decode("utf-8", errors="replace")
            return text[:2000]
    return ""


def repo_brief(issue_url: str) -> str:
    """
    Given an issue URL (https://github.com/owner/repo/issues/N) or
    "owner/repo", fetch repo metadata, the issue, the README, and
    CONTRIBUTING, then return a single markdown text block for the LLM.
    """
    # Parse owner/repo and optional issue number from the URL
    issue_number = None
    if "github.com" in issue_url:
        parts = issue_url.rstrip("/").split("/")
        # .../owner/repo/issues/N
        if "issues" in parts:
            idx = parts.index("issues")
            owner, repo_name = parts[idx - 2], parts[idx - 1]
            issue_number = parts[idx + 1] if idx + 1 < len(parts) else None
        else:
            # Just owner/repo
            owner, repo_name = parts[-2], parts[-1]
    elif "/" in issue_url:
        owner, repo_name = issue_url.split("/", 1)
    else:
        raise GitHubAPIError(f"Could not parse repo from: {issue_url}")

    sections = []

    # 1. Repo metadata (required – if this fails, propagate the error)
    repo_data = _get(f"https://api.github.com/repos/{owner}/{repo_name}")
    if repo_data:
        lic = repo_data.get("license") or {}
        sections.append(
            f"## Repository: {owner}/{repo_name}\n"
            f"- **Description**: {repo_data.get('description', 'N/A')}\n"
            f"- **Language**: {repo_data.get('language', 'N/A')}\n"
            f"- **Stars**: {repo_data.get('stargazers_count', 0)}\n"
            f"- **License**: {lic.get('spdx_id', 'N/A')}\n"
            f"- **Topics**: {', '.join(repo_data.get('topics', []))}\n"
            f"- **Last push**: {repo_data.get('pushed_at', 'N/A')}"
        )

    # 2. Issue details + comments
    if issue_number:
        issue_data = _get(
            f"https://api.github.com/repos/{owner}/{repo_name}/issues/{issue_number}"
        )
        if issue_data:
            body = (issue_data.get("body") or "")[:3000]
            sections.append(
                f"## Issue #{issue_number}: {issue_data.get('title', '')}\n"
                f"- **State**: {issue_data.get('state', '')}\n"
                f"- **Labels**: {', '.join(l['name'] for l in issue_data.get('labels', []))}\n\n"
                f"{body}"
            )
            # Fetch up to 5 comments
            comments_data = _get(
                f"https://api.github.com/repos/{owner}/{repo_name}/issues/{issue_number}/comments"
                f"?per_page=5"
            )
            if comments_data and isinstance(comments_data, list):
                comment_lines = []
                for c in comments_data[:5]:
                    author = c.get("user", {}).get("login", "unknown")
                    cbody = (c.get("body") or "")[:600]
                    comment_lines.append(f"**@{author}**: {cbody}")
                if comment_lines:
                    sections.append("### Comments\n" + "\n\n".join(comment_lines))

    # 3. README
    readme_data = _get(f"https://api.github.com/repos/{owner}/{repo_name}/readme")
    if readme_data and readme_data.get("content"):
        readme_text = base64.b64decode(readme_data["content"]).decode(
            "utf-8", errors="replace"
        )[:3000]
        sections.append(f"## README (first 3000 chars)\n{readme_text}")

    # 4. CONTRIBUTING
    contrib = _try_contributing(owner, repo_name)
    if contrib:
        sections.append(f"## CONTRIBUTING (first 2000 chars)\n{contrib}")

    if not sections:
        raise GitHubAPIError(f"Could not fetch any context for {owner}/{repo_name}.")

    return "\n\n".join(sections)
