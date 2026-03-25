"""Tests for job_bot.utils — location parsing, URL normalization, salary calculation."""

import pytest

from job_bot.utils import (
    _normalize_field_id,
    _title_case_state,
    build_location_strings,
    calculate_salary_range,
    normalize_linkedin_url,
    parse_location,
)


# ── parse_location tests ─────────────────────────────────────────────────────


class TestParseLocation:
    def test_city_state_abbreviation(self):
        result = parse_location("Florence, SC")
        assert result["city"] == "Florence"
        assert result["state_abbrev"] == "sc"
        assert result["state_full"] == "South Carolina"
        assert "United States" in result["location_full"]

    def test_city_state_country(self):
        result = parse_location("Florence, SC, US")
        assert result["city"] == "Florence"
        assert result["state_abbrev"] == "sc"
        assert result["state_full"] == "South Carolina"
        assert result["country"] == "US"

    def test_city_only(self):
        result = parse_location("Florence")
        assert result["city"] == "Florence"
        assert result["state_abbrev"] == ""
        assert result["state_full"] == ""

    def test_state_abbreviation_only(self):
        result = parse_location("SC")
        assert result["city"] == ""
        assert result["state_abbrev"] == "sc"
        assert result["state_full"] == "South Carolina"

    def test_full_state_name_only(self):
        result = parse_location("south carolina")
        assert result["city"] == ""
        assert result["state_abbrev"] == "sc"
        assert result["state_full"] == "South Carolina"

    def test_district_of_columbia(self):
        """The .title() bug: should NOT produce 'District Of Columbia'."""
        result = parse_location("Washington, DC")
        assert result["city"] == "Washington"
        assert result["state_full"] == "District of Columbia"

    def test_empty_string(self):
        result = parse_location("")
        assert result["city"] == ""
        assert result["state_abbrev"] == ""
        assert result["state_full"] == ""
        assert result["location_full"] == ""

    def test_whitespace_only(self):
        result = parse_location("   ")
        assert result["city"] == ""
        assert result["location_full"] == ""

    def test_new_york(self):
        result = parse_location("New York, NY")
        assert result["city"] == "New York"
        assert result["state_abbrev"] == "ny"
        assert result["state_full"] == "New York"

    def test_embedded_zip(self):
        result = parse_location("Florence, SC 29501")
        assert result["city"] == "Florence"
        assert result["state_abbrev"] == "sc"
        assert result["zip_code"] == "29501"

    def test_embedded_zip_plus_four(self):
        result = parse_location("Florence, SC 29501-1234")
        assert result["zip_code"] == "29501-1234"
        assert result["state_abbrev"] == "sc"

    def test_full_state_name_in_location(self):
        result = parse_location("Austin, Texas")
        assert result["city"] == "Austin"
        assert result["state_full"] == "Texas"
        assert result["state_abbrev"] == "tx"

    def test_preserves_raw(self):
        result = parse_location("Florence, SC")
        assert result["raw"] == "Florence, SC"

    def test_none_like_input(self):
        result = parse_location("")
        assert result["city"] == ""


# ── _title_case_state tests ──────────────────────────────────────────────────


class TestTitleCaseState:
    def test_district_of_columbia(self):
        assert _title_case_state("district of columbia") == "District of Columbia"

    def test_new_york(self):
        assert _title_case_state("new york") == "New York"

    def test_west_virginia(self):
        assert _title_case_state("west virginia") == "West Virginia"

    def test_empty(self):
        assert _title_case_state("") == ""

    def test_single_word(self):
        assert _title_case_state("texas") == "Texas"


# ── normalize_linkedin_url tests ─────────────────────────────────────────────


class TestNormalizeLinkedinUrl:
    def test_bare_domain(self):
        assert normalize_linkedin_url("linkedin.com/in/alex") == "https://www.linkedin.com/in/alex"

    def test_already_full(self):
        assert normalize_linkedin_url("https://www.linkedin.com/in/alex") == "https://www.linkedin.com/in/alex"

    def test_www_no_protocol(self):
        assert normalize_linkedin_url("www.linkedin.com/in/alex") == "https://www.linkedin.com/in/alex"

    def test_https_no_www(self):
        result = normalize_linkedin_url("https://linkedin.com/in/alex")
        assert result == "https://www.linkedin.com/in/alex"

    def test_strips_tracking_params(self):
        result = normalize_linkedin_url("https://www.linkedin.com/in/alex?utm_source=abc&ref=123")
        assert result == "https://www.linkedin.com/in/alex"

    def test_relative_path(self):
        assert normalize_linkedin_url("/in/alex") == "https://www.linkedin.com/in/alex"

    def test_empty(self):
        assert normalize_linkedin_url("") == ""

    def test_whitespace(self):
        assert normalize_linkedin_url("  ") == ""


# ── calculate_salary_range tests ─────────────────────────────────────────────


class TestCalculateSalaryRange:
    def test_both_values(self):
        assert calculate_salary_range({"min": 80000, "max": 120000}) == (80000, 120000)

    def test_min_only(self):
        assert calculate_salary_range({"min": 80000}) == (80000, 120000)

    def test_min_with_zero_max(self):
        assert calculate_salary_range({"min": 85000, "max": 0}) == (85000, 127500)

    def test_empty_dict(self):
        assert calculate_salary_range({}) == (0, 0)

    def test_none_input(self):
        assert calculate_salary_range(None) == (0, 0)

    def test_string_values(self):
        """Should coerce string numbers to int."""
        assert calculate_salary_range({"min": "80000", "max": "120000"}) == (80000, 120000)

    def test_invalid_string(self):
        """Should handle non-numeric strings gracefully."""
        assert calculate_salary_range({"min": "abc"}) == (0, 0)


# ── _normalize_field_id tests ────────────────────────────────────────────────


class TestNormalizeFieldId:
    def test_strips_trailing_digits(self):
        assert _normalize_field_id("phone_1") == "phone"

    def test_preserves_word_boundaries(self):
        assert _normalize_field_id("phone_extra") == "phone_extra"

    def test_no_false_match(self):
        """phone and phone_extra should normalize to different strings."""
        assert _normalize_field_id("phone") != _normalize_field_id("phone_extra")

    def test_normalizes_delimiters(self):
        assert _normalize_field_id("first-name") == "first_name"
        assert _normalize_field_id("first.name") == "first_name"
        assert _normalize_field_id("first_name") == "first_name"

    def test_case_insensitive(self):
        assert _normalize_field_id("FirstName") == "firstname"

    def test_multiple_trailing_digits(self):
        assert _normalize_field_id("field_123") == "field"

    def test_digits_in_middle(self):
        """Digits in the middle of the ID should be preserved."""
        assert _normalize_field_id("address2_line") == "address2_line"


# ── build_location_strings tests ─────────────────────────────────────────────


class TestBuildLocationStrings:
    def test_full_profile(self, minimal_profile):
        result = build_location_strings(minimal_profile)
        assert result["city"] == "Florence"
        assert result["state_full"] == "South Carolina"
        assert result["zip_code"] == "29501"
        assert result["street_address"] == "123 Elm Street"
        assert result["county"] == "Florence"

    def test_missing_location(self):
        profile = {"personal": {}}
        result = build_location_strings(profile)
        assert result["city"] == ""
        assert result["state_full"] == ""

    def test_missing_personal(self):
        profile = {}
        result = build_location_strings(profile)
        assert result["city"] == ""

    def test_county_fallback_to_city(self):
        profile = {"personal": {"location": "Austin, TX"}}
        result = build_location_strings(profile)
        assert result["county"] == "Austin"
