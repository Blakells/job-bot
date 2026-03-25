"""Shared utility functions: location parsing, URL normalization, salary calculation."""

from __future__ import annotations

import logging
import re
from urllib.parse import urlparse, urlunparse

from job_bot.config import STATE_MAP, STATE_MAP_REVERSE

logger = logging.getLogger(__name__)

# Prepositions/articles that should stay lowercase in title-cased state names
_LOWERCASE_WORDS = {"of", "and", "the"}


def _title_case_state(name: str) -> str:
    """Title-case a state name, keeping prepositions lowercase.

    "district of columbia" -> "District of Columbia"
    "new york"            -> "New York"
    "west virginia"       -> "West Virginia"
    """
    if not name:
        return ""
    words = name.split()
    result = []
    for i, word in enumerate(words):
        if i > 0 and word.lower() in _LOWERCASE_WORDS:
            result.append(word.lower())
        else:
            result.append(word.capitalize())
    return " ".join(result)


def _normalize_field_id(fid: str) -> str:
    """Normalize a field ID for fuzzy comparison, preserving word boundaries.

    Converts delimiters to underscores and strips trailing numeric suffixes.
    "phone_1"     -> "phone"
    "phone_extra" -> "phone_extra"  (preserved, no false match with "phone")
    "first-name"  -> "first_name"
    "FirstName"   -> "firstname"
    """
    normalized = re.sub(r'[-_.]+', '_', fid).strip('_').lower()
    return re.sub(r'_\d+$', '', normalized)


def parse_location(location: str) -> dict:
    """Parse a location string into structured components.

    Handles many formats:
      "Florence, SC"          -> city=Florence, state_abbrev=sc, state_full=South Carolina
      "Florence, SC, US"      -> + country=US
      "Florence"              -> city=Florence (no state)
      "SC"                    -> state_abbrev=sc, state_full=South Carolina (no city)
      "South Carolina"        -> state_full=South Carolina (no city)
      "Washington, DC"        -> city=Washington, state=District of Columbia
      ""                      -> all empty
      "Florence, SC 29501"    -> extracts embedded zip

    Returns:
        dict with keys: city, state_abbrev, state_full, zip_code, country, raw,
                        location_full (formatted as "City, State, United States")
    """
    result = {
        "city": "",
        "state_abbrev": "",
        "state_full": "",
        "zip_code": "",
        "country": "",
        "raw": location,
        "location_full": "",
    }

    if not location or not location.strip():
        return result

    location = location.strip()

    # Extract embedded zip code (5 digits or 5+4 format)
    zip_match = re.search(r'\b(\d{5}(?:-\d{4})?)\b', location)
    if zip_match:
        result["zip_code"] = zip_match.group(1)
        # Remove the zip from the string for further parsing
        location = location[:zip_match.start()] + location[zip_match.end():]
        location = location.strip().rstrip(",").strip()

    parts = [p.strip() for p in location.split(",") if p.strip()]

    if len(parts) == 0:
        return result

    if len(parts) == 1:
        token = parts[0].strip()
        token_lower = token.lower()

        # Check if it's a state abbreviation (2 letters)
        if token_lower in STATE_MAP:
            result["state_abbrev"] = token_lower
            result["state_full"] = _title_case_state(STATE_MAP[token_lower])
        # Check if it's a full state name
        elif token_lower in STATE_MAP_REVERSE:
            result["state_abbrev"] = STATE_MAP_REVERSE[token_lower]
            result["state_full"] = _title_case_state(token_lower)
        else:
            # Assume it's a city
            result["city"] = token
        logger.debug("parse_location(%r) -> single token: %s", location, result)
        _build_location_full(result)
        return result

    if len(parts) == 2:
        result["city"] = parts[0]
        _resolve_state(parts[1], result)
        _build_location_full(result)
        logger.debug("parse_location(%r) -> city+state: %s", location, result)
        return result

    # 3+ parts: city, state, country (and possibly more)
    result["city"] = parts[0]
    _resolve_state(parts[1], result)
    result["country"] = parts[2]
    _build_location_full(result)
    logger.debug("parse_location(%r) -> city+state+country: %s", location, result)
    return result


def _resolve_state(token: str, result: dict) -> None:
    """Resolve a token into state_abbrev and state_full in the result dict."""
    token = token.strip()
    token_lower = token.lower()

    if token_lower in STATE_MAP:
        result["state_abbrev"] = token_lower
        result["state_full"] = _title_case_state(STATE_MAP[token_lower])
    elif token_lower in STATE_MAP_REVERSE:
        result["state_abbrev"] = STATE_MAP_REVERSE[token_lower]
        result["state_full"] = _title_case_state(token_lower)
    else:
        # Unknown state — store as-is
        result["state_full"] = token
        logger.debug("Unknown state token: %r", token)


def _build_location_full(result: dict) -> None:
    """Build the formatted location_full string."""
    city = result["city"]
    state = result["state_full"]
    country = result.get("country", "")

    if city and state:
        result["location_full"] = f"{city}, {state}, United States"
    elif city:
        result["location_full"] = f"{city}, United States"
    elif state:
        result["location_full"] = f"{state}, United States"
    else:
        result["location_full"] = result["raw"]

    # If an explicit country was provided, use it instead of "United States"
    if country and country.lower() not in ("us", "usa", "united states"):
        result["location_full"] = result["location_full"].replace(
            "United States", country
        )


def normalize_linkedin_url(url: str) -> str:
    """Normalize a LinkedIn URL to a full, clean https URL.

    Handles:
      "linkedin.com/in/alex"                   -> "https://www.linkedin.com/in/alex"
      "https://www.linkedin.com/in/alex"        -> unchanged
      "www.linkedin.com/in/alex"                -> "https://www.linkedin.com/in/alex"
      "https://linkedin.com/in/alex?utm=abc"    -> "https://www.linkedin.com/in/alex"
      "/in/alex"                                -> "https://www.linkedin.com/in/alex"
      ""                                        -> ""
    """
    url = str(url).strip()
    if not url:
        return ""

    # Handle relative paths
    if url.startswith("/"):
        url = f"https://www.linkedin.com{url}"
    elif not url.startswith("http"):
        if url.startswith("www."):
            url = f"https://{url}"
        else:
            url = f"https://www.{url}"

    # Ensure www. is present
    parsed = urlparse(url)
    hostname = parsed.hostname or ""
    if hostname == "linkedin.com":
        url = url.replace("://linkedin.com", "://www.linkedin.com", 1)
        parsed = urlparse(url)

    # Strip tracking parameters
    if parsed.query:
        clean = parsed._replace(query="", fragment="")
        url = urlunparse(clean)

    return url


def calculate_salary_range(salary_range: dict) -> tuple[int, int]:
    """Extract and validate salary min/max from a salary range dict.

    Args:
        salary_range: dict with optional "min" and "max" keys

    Returns:
        (min_val, max_val) as integers. If min is set but not max, max = min * 1.5
    """
    if not salary_range or not isinstance(salary_range, dict):
        return (0, 0)

    try:
        salary_min = int(salary_range.get("min", 0) or 0)
    except (ValueError, TypeError):
        logger.warning("Invalid salary min: %r", salary_range.get("min"))
        salary_min = 0

    try:
        salary_max = int(salary_range.get("max", 0) or 0)
    except (ValueError, TypeError):
        logger.warning("Invalid salary max: %r", salary_range.get("max"))
        salary_max = 0

    if salary_min and not salary_max:
        salary_max = int(salary_min * 1.5)

    return (salary_min, salary_max)


def build_location_strings(profile: dict) -> dict:
    """Build all location-related strings needed by the fill pipeline.

    Reads from profile["personal"] and returns a dict with:
      city, state_abbrev, state_full, location_full, zip_code,
      street_address, county
    """
    personal = profile.get("personal", {})
    location = personal.get("location", "")

    loc = parse_location(location)

    # Pull additional fields from profile, with fallbacks
    zip_code = personal.get("zip_code", "") or loc["zip_code"]
    street_address = personal.get("street_address", "")
    county = personal.get("county", "") or loc["city"]  # fallback to city

    return {
        "city": loc["city"],
        "state_abbrev": loc["state_abbrev"],
        "state_full": loc["state_full"],
        "location_full": loc["location_full"],
        "zip_code": zip_code,
        "street_address": street_address,
        "county": county,
    }
