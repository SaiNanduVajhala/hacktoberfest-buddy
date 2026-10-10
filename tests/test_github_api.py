"""
tests/test_github_api.py – Mocked tests for github_api.py (no network).

Tests query building, deduplication, JSON parsing, and intent detection.
All GitHub API calls are mocked — no network required.
"""

import json
import pytest
from unittest.mock import patch, MagicMock

# Mock config module before importing anything from buddy
import sys
from types import ModuleType

mock_config = ModuleType("buddy.config")
mock_config.OLLAMA_BASE_URL = "http://localhost:11434/v1"
mock_config.OLLAMA_MODEL = "llama3.2"
mock_config.GITHUB_TOKEN = ""
mock_config.TELEGRAM_BOT_TOKEN = ""
sys.modules["buddy.config"] = mock_config

from buddy.github_api import search_issues, _get, GitHubRateLimitError, GitHubAPIError


def _make_issue(n, repo="owner/repo", updated="2026-10-01T00:00:00Z"):
    """Helper to build a fake GitHub issue API response item."""
    return {
        "html_url": f"https://github.com/{repo}/issues/{n}",
        "title": f"Issue {n}",
        "repository_url": f"https://api.github.com/repos/{repo}",
        "labels": [{"name": "good first issue"}, {"name": "hacktoberfest"}],
        "comments": n,
        "updated_at": updated,
        "body": f"Body of issue {n}" + " x" * 100,
    }


class TestSearchIssues:
    """Tests for search_issues()."""

    @patch("buddy.github_api._get")
    def test_basic_search_returns_results(self, mock_get):
        """Should return formatted issue dicts from GitHub search."""
        mock_get.return_value = {
            "items": [_make_issue(1), _make_issue(2)]
        }
        results = search_issues(["python"], labels=["good first issue"], limit=5)
        assert len(results) > 0
        assert "title" in results[0]
        assert "url" in results[0]
        assert "repo" in results[0]
        assert results[0]["repo"] == "owner/repo"

    @patch("buddy.github_api._get")
    def test_deduplication(self, mock_get):
        """Same issue URL from different label queries should appear only once."""
        mock_get.return_value = {
            "items": [_make_issue(1), _make_issue(1)]  # same issue twice
        }
        results = search_issues(["python"], labels=["good first issue"], limit=10)
        urls = [r["url"] for r in results]
        assert len(urls) == len(set(urls)), "Duplicate URLs found"

    @patch("buddy.github_api._get")
    def test_exclude_urls(self, mock_get):
        """Issues in exclude_urls should not appear in results."""
        mock_get.return_value = {
            "items": [_make_issue(1), _make_issue(2), _make_issue(3)]
        }
        exclude = {"https://github.com/owner/repo/issues/2"}
        results = search_issues(["python"], limit=10, exclude_urls=exclude)
        urls = [r["url"] for r in results]
        assert "https://github.com/owner/repo/issues/2" not in urls

    @patch("buddy.github_api._get")
    def test_body_snippet_truncated(self, mock_get):
        """body_snippet should be at most 500 chars."""
        mock_get.return_value = {
            "items": [_make_issue(1)]
        }
        results = search_issues(["python"], limit=5)
        assert len(results[0]["body_snippet"]) <= 500

    @patch("buddy.github_api._get")
    def test_sorted_by_updated(self, mock_get):
        """Results should be sorted by updated_at descending."""
        mock_get.return_value = {
            "items": [
                _make_issue(1, updated="2026-09-01T00:00:00Z"),
                _make_issue(2, updated="2026-10-05T00:00:00Z"),
                _make_issue(3, updated="2026-10-01T00:00:00Z"),
            ]
        }
        results = search_issues(["python"], limit=10)
        dates = [r["updated"] for r in results]
        assert dates == sorted(dates, reverse=True)

    @patch("buddy.github_api._get")
    def test_multiple_languages(self, mock_get):
        """Should query for each language and combine results."""
        mock_get.return_value = {"items": [_make_issue(1)]}
        results = search_issues(
            ["python", "javascript"],
            labels=["good first issue"],
            limit=10,
        )
        # Called once per language × label combination
        assert mock_get.call_count == 2

    @patch("buddy.github_api._get")
    def test_rate_limit_propagates(self, mock_get):
        """GitHubRateLimitError should propagate to caller."""
        mock_get.side_effect = GitHubRateLimitError("rate limited")
        with pytest.raises(GitHubRateLimitError):
            search_issues(["python"], limit=5)

    @patch("buddy.github_api._get")
    def test_api_error_propagates(self, mock_get):
        """GitHubAPIError should propagate to caller, not be silently swallowed."""
        mock_get.side_effect = GitHubAPIError("server error")
        with pytest.raises(GitHubAPIError):
            search_issues(["python"], limit=5)

    @patch("buddy.github_api._get")
    def test_network_error_propagates(self, mock_get):
        """Network errors should propagate, not be silently swallowed."""
        mock_get.side_effect = ConnectionError("network down")
        with pytest.raises(ConnectionError):
            search_issues(["python"], limit=5)

    @patch("buddy.github_api._get")
    def test_empty_results(self, mock_get):
        """Should return empty list when no items found."""
        mock_get.return_value = {"items": []}
        results = search_issues(["cobol"], limit=5)
        assert results == []


class TestJSONParsing:
    """Test the defensive JSON parsing in core.py."""

    def test_parse_clean_json(self):
        from buddy.core import _parse_json
        data = _parse_json('[{"url": "a", "reason": "b"}]')
        assert isinstance(data, list)
        assert data[0]["url"] == "a"

    def test_parse_json_with_fences(self):
        from buddy.core import _parse_json
        text = '```json\n[{"url": "a", "reason": "b"}]\n```'
        data = _parse_json(text)
        assert isinstance(data, list)
        assert data[0]["url"] == "a"

    def test_parse_json_returns_none_on_garbage(self):
        from buddy.core import _parse_json
        assert _parse_json("this is not json at all") is None

    def test_parse_json_dict(self):
        from buddy.core import _parse_json
        data = _parse_json('{"skills": ["python"], "level": "beginner"}')
        assert isinstance(data, dict)
        assert "python" in data["skills"]

    def test_parse_json_with_backticks_only(self):
        from buddy.core import _parse_json
        text = '```\n{"key": "value"}\n```'
        data = _parse_json(text)
        assert isinstance(data, dict)
        assert data["key"] == "value"


class TestIntentDetection:
    """Test intent detection in core.py."""

    def test_more_intent(self):
        from buddy.core import _detect_intent
        assert _detect_intent("more")[0] == "more"
        assert _detect_intent("/more")[0] == "more"
        assert _detect_intent("show more")[0] == "more"
        assert _detect_intent("next")[0] == "more"

    def test_pick_intent(self):
        from buddy.core import _detect_intent
        intent, arg = _detect_intent("pick 2")
        assert intent == "pick"
        assert arg == "2"

    def test_pick_with_hash(self):
        from buddy.core import _detect_intent
        intent, arg = _detect_intent("pick #3")
        assert intent == "pick"
        assert arg == "3"

    def test_pick_url_intent(self):
        from buddy.core import _detect_intent
        intent, arg = _detect_intent("https://github.com/owner/repo/issues/42")
        assert intent == "pick_url"
        assert arg == "https://github.com/owner/repo/issues/42"

    def test_profile_intent(self):
        from buddy.core import _detect_intent
        assert _detect_intent("profile")[0] == "profile"
        assert _detect_intent("/profile")[0] == "profile"

    def test_reset_intent(self):
        from buddy.core import _detect_intent
        assert _detect_intent("reset")[0] == "reset"
        assert _detect_intent("/reset")[0] == "reset"
        assert _detect_intent("start over")[0] == "reset"

    def test_pr_intent(self):
        from buddy.core import _detect_intent
        assert _detect_intent("pr")[0] == "pr"
        assert _detect_intent("/pr")[0] == "pr"
        assert _detect_intent("draft pr")[0] == "pr"

    def test_freetext_intent(self):
        from buddy.core import _detect_intent
        intent, arg = _detect_intent("I know Python and React")
        assert intent == "freetext"
        assert arg == "I know Python and React"


class TestLLMJsonRetry:
    """Test that _llm_json retries on parse failure and raises on exhaustion."""

    @patch("buddy.core.llm")
    def test_succeeds_on_first_try(self, mock_llm):
        from buddy.core import _llm_json
        mock_llm.chat.return_value = '{"skills": ["python"]}'
        result = _llm_json("sys", "user", expect_type=dict)
        assert result["skills"] == ["python"]
        assert mock_llm.chat.call_count == 1

    @patch("buddy.core.llm")
    def test_retries_on_bad_json(self, mock_llm):
        from buddy.core import _llm_json
        mock_llm.chat.side_effect = [
            "not json",  # first attempt fails
            '{"skills": ["python"]}',  # second succeeds
        ]
        result = _llm_json("sys", "user", expect_type=dict)
        assert result["skills"] == ["python"]
        assert mock_llm.chat.call_count == 2

    @patch("buddy.core.llm")
    def test_raises_after_all_retries_fail(self, mock_llm):
        from buddy.core import _llm_json
        mock_llm.chat.return_value = "definitely not json"
        with pytest.raises(RuntimeError, match="valid JSON"):
            _llm_json("sys", "user", expect_type=dict)

    @patch("buddy.core.llm")
    def test_wrong_type_triggers_retry(self, mock_llm):
        from buddy.core import _llm_json
        mock_llm.chat.side_effect = [
            '{"key": "value"}',  # dict, but we want list
            '[{"url": "a"}]',    # correct type
        ]
        result = _llm_json("sys", "user", expect_type=list)
        assert isinstance(result, list)
