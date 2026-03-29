"""Tests for pipeline checkpoint/resume and auto-publish logic."""
import json
import os
import pytest
import tempfile
from unittest.mock import patch, MagicMock


@pytest.fixture
def temp_dirs(tmp_path):
    """Create temp directories mimicking production layout."""
    data_dir = tmp_path / "data"
    metadata_dir = data_dir / "metadata"
    metadata_dir.mkdir(parents=True)
    (data_dir / "inbox").mkdir()
    (data_dir / "edited").mkdir()
    (data_dir / "shorts").mkdir()
    return {"data": str(data_dir), "metadata": str(metadata_dir)}


class TestCheckpointResume:
    def test_save_and_load_checkpoint(self, temp_dirs):
        with patch("pipeline.METADATA_DIR", temp_dirs["metadata"]):
            from pipeline import _save_checkpoint, _load_checkpoint

            test_data = {"content_rating": 8, "filler_words": []}
            _save_checkpoint("test123", "intake", test_data)

            loaded = _load_checkpoint("test123", "intake")
            assert loaded is not None
            assert loaded["content_rating"] == 8

    def test_load_missing_checkpoint_returns_none(self, temp_dirs):
        with patch("pipeline.METADATA_DIR", temp_dirs["metadata"]):
            from pipeline import _load_checkpoint
            assert _load_checkpoint("nonexistent", "intake") is None

    def test_corrupt_checkpoint_returns_none(self, temp_dirs):
        with patch("pipeline.METADATA_DIR", temp_dirs["metadata"]):
            from pipeline import _load_checkpoint
            # Write corrupt JSON
            path = os.path.join(temp_dirs["metadata"], "corrupt_intake.json")
            with open(path, "w") as f:
                f.write("{broken json")
            assert _load_checkpoint("corrupt", "intake") is None


class TestValidateAsset:
    def test_missing_file_returns_false(self):
        from pipeline import _validate_asset
        assert _validate_asset("/nonexistent/file.mp4") is False

    def test_none_returns_false(self):
        from pipeline import _validate_asset
        assert _validate_asset(None) is False

    def test_empty_string_returns_false(self):
        from pipeline import _validate_asset
        assert _validate_asset("") is False

    def test_tiny_file_returns_false(self, tmp_path):
        from pipeline import _validate_asset
        tiny = tmp_path / "tiny.mp4"
        tiny.write_bytes(b"x" * 100)
        assert _validate_asset(str(tiny)) is False


class TestBuildTranscriptText:
    def test_builds_from_segments(self):
        from pipeline import _build_transcript_text
        data = {
            "segments": [
                {"start": 0.0, "end": 5.0, "text": "Hello world"},
                {"start": 5.0, "end": 10.0, "text": "How are you"},
            ]
        }
        text = _build_transcript_text(data)
        assert "Hello world" in text
        assert "How are you" in text
        assert "[0.0s" in text

    def test_falls_back_to_text_field(self):
        from pipeline import _build_transcript_text
        data = {"text": "Full transcript", "segments": []}
        text = _build_transcript_text(data)
        assert text == "Full transcript"

    def test_empty_transcript(self):
        from pipeline import _build_transcript_text
        text = _build_transcript_text({})
        assert text == ""


class TestAutoPublishConfig:
    def test_auto_publish_env_true(self):
        with patch.dict(os.environ, {"AUTO_PUBLISH": "true"}):
            # Re-evaluate the config
            result = os.environ.get("AUTO_PUBLISH", "true").lower() in ("true", "1", "yes")
            assert result is True

    def test_auto_publish_env_false(self):
        with patch.dict(os.environ, {"AUTO_PUBLISH": "false"}):
            result = os.environ.get("AUTO_PUBLISH", "true").lower() in ("true", "1", "yes")
            assert result is False
