"""Centralized configuration: environment variables, API URLs, constants."""

import os
from pathlib import Path

# ── API Keys (from environment) ──────────────────────────────────────────────

OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")

# ── API Endpoints ────────────────────────────────────────────────────────────

OPENROUTER_BASE = "https://openrouter.ai/api/v1/chat/completions"
MODEL = "anthropic/claude-sonnet-4-5"

# ── Defaults ─────────────────────────────────────────────────────────────────

DEFAULT_MAX_TOKENS = 4000
DEFAULT_TEMPERATURE = 0.1

# ── Paths ────────────────────────────────────────────────────────────────────

COOKIE_DIR = Path("profiles/.browser_sessions")

# ── ATS Platform Detection ───────────────────────────────────────────────────

ATS_PLATFORMS = {
    "icims.com":           "icims",
    "myworkdayjobs.com":   "workday",
    "workday.com":         "workday",
    "lever.co":            "lever",
    "greenhouse.io":       "greenhouse",
    "smartrecruiters.com": "smartrecruiters",
    "taleo.net":           "taleo",
    "paylocity.com":       "paylocity",
    "adp.com":             "adp",
    "jobvite.com":         "jobvite",
    "ultipro.com":         "ultipro",
    "breezy.hr":           "breezy",
    "ashbyhq.com":         "ashby",
}

# ── US State Abbreviation Mapping ────────────────────────────────────────────

STATE_MAP = {
    "al": "alabama", "ak": "alaska", "az": "arizona", "ar": "arkansas",
    "ca": "california", "co": "colorado", "ct": "connecticut", "de": "delaware",
    "dc": "district of columbia", "fl": "florida", "ga": "georgia",
    "hi": "hawaii", "id": "idaho", "il": "illinois", "in": "indiana",
    "ia": "iowa", "ks": "kansas", "ky": "kentucky", "la": "louisiana",
    "me": "maine", "md": "maryland", "ma": "massachusetts", "mi": "michigan",
    "mn": "minnesota", "ms": "mississippi", "mo": "missouri", "mt": "montana",
    "ne": "nebraska", "nv": "nevada", "nh": "new hampshire", "nj": "new jersey",
    "nm": "new mexico", "ny": "new york", "nc": "north carolina",
    "nd": "north dakota", "oh": "ohio", "ok": "oklahoma", "or": "oregon",
    "pa": "pennsylvania", "ri": "rhode island", "sc": "south carolina",
    "sd": "south dakota", "tn": "tennessee", "tx": "texas", "ut": "utah",
    "vt": "vermont", "va": "virginia", "wa": "washington",
    "wv": "west virginia", "wi": "wisconsin", "wy": "wyoming",
}

STATE_MAP_REVERSE = {v: k for k, v in STATE_MAP.items()}
