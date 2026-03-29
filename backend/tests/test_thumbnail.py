"""Tests for thumbnail and community post image generation."""
import os
import pytest
from unittest.mock import patch, MagicMock


class TestCommunityImageFromAI:
    def test_missing_replicate_returns_none(self):
        """If replicate package not installed, returns None gracefully."""
        with patch.dict("sys.modules", {"replicate": None}):
            from engines.thumbnail import _community_image_from_ai
            result = _community_image_from_ai("test post", "/tmp/test.png")
            # Should return None since replicate import fails
            assert result is None


class TestGenerateCommunityPostImage:
    def test_unknown_method_returns_none(self):
        from engines.thumbnail import generate_community_post_image
        result = generate_community_post_image(
            "/fake/video.mp4", "test", "job123", 0, method="unknown"
        )
        assert result is None

    def test_frame_method_called(self):
        with patch("engines.thumbnail._community_image_from_frame") as mock:
            mock.return_value = "/tmp/test.png"
            from engines.thumbnail import generate_community_post_image
            result = generate_community_post_image(
                "/fake/video.mp4", "test post", "job123", 0, method="frame"
            )
            mock.assert_called_once()
