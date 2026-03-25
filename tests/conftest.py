"""Shared test fixtures for job_bot tests."""

import json
from pathlib import Path

import pytest


@pytest.fixture
def sample_profile():
    """Load the Alex Carter test profile."""
    profile_path = Path(__file__).parent.parent / "profiles" / "alex" / "profile.json"
    with open(profile_path) as f:
        return json.load(f)


@pytest.fixture
def minimal_profile():
    """A minimal profile with just the fields needed for location/salary tests."""
    return {
        "personal": {
            "first_name": "Alex",
            "last_name": "Carter",
            "email": "alex@example.com",
            "phone": "555-123-4567",
            "location": "Florence, SC",
            "street_address": "123 Elm Street",
            "county": "Florence",
            "zip_code": "29501",
            "linkedin_url": "linkedin.com/in/alexjcarter",
        },
        "salary_range": {"min": 85000, "max": 0, "currency": "USD"},
    }


@pytest.fixture
def mock_fields():
    """Sample form fields matching the structure from EXTRACT_FIELDS_JS."""
    return [
        {
            "id": "first_name",
            "name": "first_name",
            "label": "First Name",
            "type": "text",
            "tag": "input",
            "placeholder": "",
            "helperText": "",
            "parentClass": "",
            "section": "",
        },
        {
            "id": "email_address",
            "name": "email",
            "label": "Email Address",
            "type": "email",
            "tag": "input",
            "placeholder": "you@example.com",
            "helperText": "",
            "parentClass": "",
            "section": "",
        },
        {
            "id": "phone_1",
            "name": "phone",
            "label": "Phone Number",
            "type": "tel",
            "tag": "input",
            "placeholder": "",
            "helperText": "",
            "parentClass": "",
            "section": "",
        },
        {
            "id": "resume",
            "name": "resume_file",
            "label": "Resume",
            "type": "file",
            "tag": "input",
            "placeholder": "",
            "helperText": "",
            "parentClass": "",
            "section": "",
        },
        {
            "id": "city",
            "name": "city",
            "label": "City",
            "type": "text",
            "tag": "input",
            "placeholder": "",
            "helperText": "",
            "parentClass": "",
            "section": "",
        },
        {
            "id": "state",
            "name": "state",
            "label": "State",
            "type": "text",
            "tag": "input",
            "placeholder": "",
            "helperText": "",
            "parentClass": "",
            "section": "",
        },
    ]
