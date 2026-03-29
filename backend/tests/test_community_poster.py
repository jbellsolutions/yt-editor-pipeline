"""Tests for community post browser automation."""
import pytest
from unittest.mock import patch


class TestPostCommunityUpdates:
    def test_missing_playwright_returns_failed(self):
        """If playwright not installed, all posts return failed."""
        with patch.dict("sys.modules", {"playwright": None, "playwright.sync_api": None}):
            # Force reimport
            import importlib
            import engines.community_poster as cp
            importlib.reload(cp)
            results = cp.post_community_updates([
                {"text": "Test post 1"},
                {"text": "Test post 2"},
            ])
            assert len(results) == 2
            assert all(r["status"] == "failed" for r in results)

    def test_missing_cookies_returns_failed(self):
        """If cookies file doesn't exist, all posts return failed."""
        from engines.community_poster import post_community_updates
        results = post_community_updates(
            [{"text": "Test"}],
            cookie_path="/nonexistent/cookies.json",
        )
        assert len(results) == 1
        assert results[0]["status"] == "failed"
        assert "cookies" in results[0]["error"]

    def test_empty_posts_returns_empty(self):
        from engines.community_poster import post_community_updates
        results = post_community_updates(
            [],
            cookie_path="/nonexistent/cookies.json",
        )
        assert results == []
