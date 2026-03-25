"""Tests for applier.py and profile.py — answer mapping and field resolution."""

import pytest

from job_bot.profile import build_answer_map, resolve_answer
from job_bot.utils import _normalize_field_id


class TestBuildAnswerMap:
    """Tests for build_answer_map — profile-to-form-field answer generation."""

    def test_basic_fields(self, sample_profile):
        by_id, by_label = build_answer_map(sample_profile, "test_company")
        # ID-based lookups
        assert by_id["email"] == sample_profile["personal"]["email"]
        assert by_id["phone"] == sample_profile["personal"]["phone"]

    def test_location_fields(self, sample_profile):
        by_id, by_label = build_answer_map(sample_profile, "test_company")
        assert by_label["city"] == "Florence"
        assert by_label["state"] == "South Carolina"
        assert by_label["zip code"] == "29501"
        assert by_label["country"] == "United States"

    def test_linkedin_normalized(self, sample_profile):
        by_id, by_label = build_answer_map(sample_profile, "test_company")
        linkedin = by_label["linkedin"]
        assert linkedin.startswith("https://")
        assert "www." in linkedin

    def test_salary_fields(self, sample_profile):
        by_id, by_label = build_answer_map(sample_profile, "test_company")
        # Profile has min=85000, max=0 → max should be 85000 * 1.5 = 127500
        assert by_label["minimum salary"] == "85000"
        assert by_label["maximum salary"] == "127500"

    def test_work_authorization(self, sample_profile):
        by_id, by_label = build_answer_map(sample_profile, "test_company")
        assert by_label["legally authorized to work"] == "Yes"
        assert by_label["require sponsorship"] == "No"

    def test_district_of_columbia(self):
        """Verify .title() bug is fixed — should NOT produce 'District Of Columbia'."""
        profile = {
            "personal": {
                "name": "Jane Doe",
                "email": "jane@example.com",
                "phone": "555-0000",
                "location": "Washington, DC",
            }
        }
        by_id, by_label = build_answer_map(profile, "test")
        assert by_label["state"] == "District of Columbia"
        assert "Of" not in by_label["state"]  # NOT "District Of Columbia"


class TestResolveAnswer:
    """Tests for resolve_answer — looking up answers for form fields."""

    def test_id_match(self, sample_profile):
        by_id, by_label = build_answer_map(sample_profile, "test")
        field = {"id": "email", "label": "Something else"}
        assert resolve_answer(field, by_id, by_label) == sample_profile["personal"]["email"]

    def test_label_match(self, sample_profile):
        by_id, by_label = build_answer_map(sample_profile, "test")
        field = {"id": "unknown_id_123", "label": "Phone Number"}
        assert resolve_answer(field, by_id, by_label) == sample_profile["personal"]["phone"]

    def test_no_match_returns_none(self, sample_profile):
        by_id, by_label = build_answer_map(sample_profile, "test")
        field = {"id": "totally_unknown", "label": "Completely unknown field"}
        assert resolve_answer(field, by_id, by_label) is None


class TestFieldIdNormalization:
    """Tests that the fuzzy ID matching works correctly after the fix."""

    def test_phone_1_matches_phone(self):
        """phone_1 should normalize to match phone key."""
        assert _normalize_field_id("phone_1") == _normalize_field_id("phone")

    def test_phone_does_not_match_phone_extra(self):
        """phone should NOT match phone_extra — the old bug."""
        assert _normalize_field_id("phone") != _normalize_field_id("phone_extra")

    def test_first_name_variants(self):
        """first-name, first_name, first.name should all match."""
        n1 = _normalize_field_id("first-name")
        n2 = _normalize_field_id("first_name")
        n3 = _normalize_field_id("first.name")
        assert n1 == n2 == n3

    def test_email_1_matches_email(self):
        assert _normalize_field_id("email_1") == _normalize_field_id("email")

    def test_address_2_distinct_from_address(self):
        """address_2 should still match address (trailing digits stripped)."""
        assert _normalize_field_id("address_2") == _normalize_field_id("address")

    def test_address2_line_preserved(self):
        """address2_line has digits in the middle — should NOT strip them."""
        assert _normalize_field_id("address2_line") == "address2_line"
