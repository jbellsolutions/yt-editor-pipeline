"""Tests for runtime validation schemas."""
import pytest
from validation import (
    ValidationError,
    validate_intake_result,
    validate_edit_plan,
    validate_short_designs,
    validate_package_result,
    validate_qa_result,
)


# ─── Intake Validation ───

class TestValidateIntakeResult:
    def test_valid_intake(self):
        data = {
            "content_rating": 7,
            "filler_words": [{"word": "um", "start": 1.0, "end": 1.2}],
            "topic_segments": [],
        }
        result = validate_intake_result(data)
        assert result["content_rating"] == 7

    def test_missing_content_rating(self):
        with pytest.raises(ValidationError, match="content_rating"):
            validate_intake_result({"filler_words": []})

    def test_non_dict_raises(self):
        with pytest.raises(ValidationError):
            validate_intake_result("not a dict")

    def test_non_numeric_rating_defaults(self):
        data = {"content_rating": "high"}
        result = validate_intake_result(data)
        assert result["content_rating"] == 5

    def test_non_list_filler_words_fixed(self):
        data = {"content_rating": 8, "filler_words": "none"}
        result = validate_intake_result(data)
        assert result["filler_words"] == []


# ─── Edit Plan Validation ───

class TestValidateEditPlan:
    def test_valid_edit_plan(self):
        data = {
            "cut_segments": [
                {"start": 5.0, "end": 7.5, "reason": "dead air"},
                {"start": 15.0, "end": 16.0, "reason": "filler"},
            ],
            "text_overlays": [
                {"text": "Hello", "start": 0, "end": 3},
            ],
        }
        result = validate_edit_plan(data)
        assert len(result["cut_segments"]) == 2

    def test_start_greater_than_end_raises(self):
        data = {"cut_segments": [{"start": 10.0, "end": 5.0}]}
        with pytest.raises(ValidationError, match="start.*>=.*end"):
            validate_edit_plan(data)

    def test_negative_start_raises(self):
        data = {"cut_segments": [{"start": -1.0, "end": 5.0}]}
        with pytest.raises(ValidationError, match="negative"):
            validate_edit_plan(data)

    def test_non_numeric_start_raises(self):
        data = {"cut_segments": [{"start": "five", "end": 10}]}
        with pytest.raises(ValidationError, match="numeric"):
            validate_edit_plan(data)

    def test_overlay_missing_text_raises(self):
        data = {"text_overlays": [{"start": 0, "end": 3}]}
        with pytest.raises(ValidationError, match="text"):
            validate_edit_plan(data)

    def test_empty_plan_valid(self):
        result = validate_edit_plan({})
        assert result == {}


# ─── Short Designs Validation ───

class TestValidateShortDesigns:
    def test_valid_shorts(self):
        data = [
            {"start": 10.0, "end": 40.0, "title": "Hook moment"},
            {"start": 60.0, "end": 85.0, "title": "Key insight"},
        ]
        result = validate_short_designs(data)
        assert len(result) == 2

    def test_non_list_raises(self):
        with pytest.raises(ValidationError):
            validate_short_designs({"start": 0, "end": 30})

    def test_missing_start_raises(self):
        with pytest.raises(ValidationError, match="start"):
            validate_short_designs([{"end": 30, "title": "test"}])

    def test_start_after_end_raises(self):
        with pytest.raises(ValidationError, match="start.*>=.*end"):
            validate_short_designs([{"start": 40, "end": 10}])

    def test_empty_list_valid(self):
        result = validate_short_designs([])
        assert result == []


# ─── Package Result Validation ───

class TestValidatePackageResult:
    def test_valid_package(self):
        data = {
            "long_form": {
                "title": "My Video",
                "title_variants": ["Title 1", "Title 2"],
                "description": "Great video",
                "tags": ["python", "tutorial"],
            },
            "shorts": [{"title": "Short 1", "tags": ["short"]}],
            "community_posts": [{"text": "Check out my new video!", "type": "engagement"}],
        }
        result = validate_package_result(data)
        assert len(result["shorts"]) == 1

    def test_non_dict_raises(self):
        with pytest.raises(ValidationError):
            validate_package_result([])

    def test_non_list_shorts_fixed(self):
        data = {"long_form": {"title": "Test"}, "shorts": "none"}
        result = validate_package_result(data)
        assert result["shorts"] == []

    def test_empty_package_warns_but_passes(self):
        result = validate_package_result({})
        assert isinstance(result, dict)


# ─── QA Result Validation ───

class TestValidateQAResult:
    def test_valid_qa_pass(self):
        data = {"verdict": "PASS", "passed": True, "coherence_score": 25}
        result = validate_qa_result(data)
        assert result["verdict"] == "PASS"

    def test_valid_qa_fail(self):
        data = {"verdict": "FAIL", "passed": False}
        result = validate_qa_result(data)
        assert result["passed"] is False

    def test_missing_verdict_defaults_to_fail(self):
        data = {"coherence_score": 20}
        result = validate_qa_result(data)
        assert result["verdict"] == "FAIL"
        assert result["passed"] is False

    def test_non_dict_raises(self):
        with pytest.raises(ValidationError):
            validate_qa_result("PASS")
