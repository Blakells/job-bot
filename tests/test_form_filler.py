"""Tests for form_filler.py — dropdown answer determination logic."""

import pytest

try:
    from job_bot.form_filler import _determine_dropdown_answer
    HAS_SCRAPLING = True
except ImportError:
    HAS_SCRAPLING = False

pytestmark = pytest.mark.skipif(
    not HAS_SCRAPLING,
    reason="scrapling (Selector) not available in this Python environment",
)


class TestDetermineDropdownAnswer:
    """Tests for _determine_dropdown_answer — the dynamic dropdown answer logic."""

    @pytest.fixture
    def profile(self):
        return {
            "personal": {
                "name": "Alex Carter",
                "location": "Florence, SC",
            },
            "eeoc": {
                "gender": "Male",
                "hispanic_ethnicity": "No",
                "veteran_status": "I am not a protected veteran",
                "disability_status": "No, I don't have a disability",
                "race": "Decline to self-identify",
            },
            "education": [
                {"degree": "Bachelor's in Computer Science", "school": "State University"}
            ],
        }

    # ── Yes/No detection ──────────────────────────────────────────────

    def test_work_authorization_yes(self, profile):
        result = _determine_dropdown_answer(
            "Are you authorized to work in the US?",
            ["Yes", "No"],
            profile,
        )
        assert result == "Yes"

    def test_sponsorship_no(self, profile):
        result = _determine_dropdown_answer(
            "Do you require sponsorship?",
            ["Yes", "No"],
            profile,
        )
        assert result == "No"

    def test_yes_with_asterisk(self, profile):
        """Paylocity uses 'Yes*' — asterisks should be stripped for matching."""
        result = _determine_dropdown_answer(
            "Are you legally authorized to work?",
            ["Yes*", "No*"],
            profile,
        )
        assert result == "Yes*"

    def test_background_check_yes(self, profile):
        result = _determine_dropdown_answer(
            "Are you willing to undergo a background check?",
            ["Yes", "No"],
            profile,
        )
        assert result == "Yes"

    def test_convicted_felony_no(self, profile):
        result = _determine_dropdown_answer(
            "Have you been convicted of a felony?",
            ["Yes", "No"],
            profile,
        )
        assert result == "No"

    def test_sms_consent_yes(self, profile):
        result = _determine_dropdown_answer(
            "Do we have permission to send you sms messages?",
            ["Yes", "No"],
            profile,
        )
        assert result == "Yes"

    def test_previously_applied_no(self, profile):
        result = _determine_dropdown_answer(
            "Have you applied before?",
            ["Yes", "No"],
            profile,
        )
        assert result == "No"

    # ── Profile-based answers ─────────────────────────────────────────

    def test_salary_type_yearly(self, profile):
        result = _determine_dropdown_answer(
            "Salary Type",
            ["Hourly", "Yearly", "Monthly"],
            profile,
        )
        assert result == "Yearly"

    def test_employment_type_fulltime(self, profile):
        result = _determine_dropdown_answer(
            "Desired Employment Type",
            ["Part-time", "Full-time", "Contract"],
            profile,
        )
        assert result == "Full-time"

    def test_how_did_you_hear(self, profile):
        result = _determine_dropdown_answer(
            "How did you hear about this position?",
            ["Indeed", "LinkedIn", "Company Website", "Referral"],
            profile,
        )
        assert result == "LinkedIn"

    # ── State dropdown ────────────────────────────────────────────────

    def test_state_dropdown(self, profile):
        result = _determine_dropdown_answer(
            "State",
            ["Alabama", "California", "South Carolina", "Texas"],
            profile,
        )
        assert result == "South Carolina"

    # ── Degree type ───────────────────────────────────────────────────

    def test_degree_type_bachelors(self, profile):
        result = _determine_dropdown_answer(
            "Degree Obtained",
            ["High School", "Associate's", "Bachelor's", "Master's", "Doctorate"],
            profile,
        )
        assert result == "Bachelor's"

    # ── School type ───────────────────────────────────────────────────

    def test_school_type(self, profile):
        result = _determine_dropdown_answer(
            "School Type",
            ["High School", "Community College", "University", "Vocational"],
            profile,
        )
        assert result == "University"

    # ── Unknown dropdown returns None ─────────────────────────────────

    def test_unknown_returns_none(self, profile):
        result = _determine_dropdown_answer(
            "Some completely unknown field",
            ["Option A", "Option B", "Option C"],
            profile,
        )
        assert result is None
