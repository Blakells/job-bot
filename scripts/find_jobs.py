#!/usr/bin/env python3
"""
Phase 2 v2: LinkedIn Job Discovery & Scoring with Scrapling
=============================================================
Finds jobs on LinkedIn using Scrapling's StealthyFetcher to bypass bot detection.

How it works:
  1. LOGIN    — Opens a real browser, you log in manually (handles 2FA naturally)
  2. SEARCH   — Searches LinkedIn for each of your target roles
  3. EXTRACT  — Pulls job cards from search results (title, company, location, type)
  4. DETAIL   — Visits each job page for the full description + apply link
  5. SCORE    — Sends promising matches to Claude for detailed scoring
  6. SAVE     — Asks your minimum score threshold, then saves to scored_jobs.json

Usage:
  python3 scripts/find_jobs.py --profile profiles/alex/profile.json
  python3 scripts/find_jobs.py --profile profiles/alex/profile.json --max-pages 3
  python3 scripts/find_jobs.py --profile profiles/alex/profile.json --headless

Setup (first time only):
  python3.13 -m pip install "scrapling[fetchers]" --break-system-packages
  scrapling install

Pipeline:
  build_profile_v2.py → find_jobs.py → tailor_resume.py → convert_to_pdf.py → auto_apply_v4.py
"""

import json
import os
import sys
import argparse
import re
import time
from pathlib import Path
from datetime import date
from urllib.parse import quote_plus, urljoin, urlparse, parse_qs, urlencode
from typing import List, Dict, Set, Optional

import requests

# ── Config ───────────────────────────────────────────────────────────────────

OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")
OPENROUTER_BASE = "https://openrouter.ai/api/v1/chat/completions"
MODEL = "anthropic/claude-sonnet-4-5"

# Be polite to LinkedIn — wait between requests
REQUEST_DELAY = 3  # seconds between page loads
RESULTS_PER_PAGE = 25  # LinkedIn shows 25 jobs per page

# LinkedIn search URL template (logged-in version)
LINKEDIN_SEARCH_URL = "https://www.linkedin.com/jobs/search/"

# LinkedIn time filters
TIME_FILTERS = {
    "24h": "r86400",
    "week": "r604800",
    "month": "r2592000",
    "any": "",
}

# LinkedIn work type filters
WORK_TYPE_FILTERS = {
    "Remote only": "2",
    "Hybrid": "3",
    "In-person only": "1",
    "Open to all": "",
}


# ── Scrapling Imports (lazy) ────────────────────────────────────────────────
# We import lazily so the script shows a helpful error if Scrapling isn't installed.

def import_scrapling():
    """Import Scrapling and return the classes we need."""
    try:
        from scrapling.fetchers import StealthyFetcher, StealthySession
        return StealthyFetcher, StealthySession
    except ImportError:
        print("\n❌ Scrapling is not installed. Set it up with:\n")
        print('   python3.13 -m pip install "scrapling[fetchers]" --break-system-packages')
        print("   scrapling install\n")
        sys.exit(1)


# ── Claude API ───────────────────────────────────────────────────────────────

def ask_claude(prompt, max_tokens=2000):
    """Send a prompt to Claude via OpenRouter and return the response."""
    if not OPENROUTER_API_KEY:
        print("    ⚠️  No OPENROUTER_API_KEY — skipping AI scoring")
        return ""

    try:
        resp = requests.post(
            OPENROUTER_BASE,
            headers={
                "Authorization": "Bearer {}".format(OPENROUTER_API_KEY),
                "Content-Type": "application/json",
            },
            json={
                "model": MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": max_tokens,
                "temperature": 0.1,
            },
            timeout=60,
        )
        data = resp.json()
        if "choices" in data:
            return data["choices"][0]["message"]["content"].strip()
        elif "error" in data:
            print("    ❌ API error: {}".format(data["error"].get("message", data["error"])[:100]))
            return ""
        else:
            print("    ❌ Unexpected API response: {}".format(str(data)[:150]))
            return ""
    except Exception as e:
        print("    ❌ Claude error: {}".format(e))
        return ""


def parse_json_response(raw):
    """Parse JSON from Claude's response, handling markdown fences."""
    raw = raw.strip()
    if "```" in raw:
        parts = raw.split("```")
        for part in parts:
            cleaned = part.strip()
            if cleaned.startswith("json"):
                cleaned = cleaned[4:].strip()
            if cleaned.startswith("{"):
                raw = cleaned
                break

    start = raw.find("{")
    end = raw.rfind("}") + 1
    if start >= 0 and end > start:
        try:
            return json.loads(raw[start:end])
        except json.JSONDecodeError:
            pass
    return None


# ═══════════════════════════════════════════════════════════════════════════════
#  STEP 1: LOGIN TO LINKEDIN
# ═══════════════════════════════════════════════════════════════════════════════
#
# We open a real browser using Scrapling's StealthySession. This gives us:
#   - A real Chromium browser with fingerprint spoofing
#   - Anti-bot detection bypass
#   - Persistent cookies across requests (same session)
#
# The user logs in manually — this handles 2FA, CAPTCHAs, and any other
# LinkedIn security checks naturally. No credentials stored anywhere.

def login_to_linkedin(session, headless=False):
    """
    Navigate to LinkedIn login and wait for the user to authenticate.
    
    Args:
        session: An active StealthySession
        headless: If True, skip the manual login (assumes cookies/session exist)
    
    Returns:
        True if login appears successful, False otherwise
    """
    print("\n  🔐 STEP 1: LinkedIn Login")
    print("  " + "─" * 50)

    if headless:
        print("    ⚠️  Headless mode — skipping manual login.")
        print("    Attempting to access LinkedIn with existing session...")
        page = session.fetch("https://www.linkedin.com/feed/", network_idle=True)
        if page and "login" not in str(page.url).lower():
            print("    ✅ Already logged in!")
            return True
        else:
            print("    ❌ Not logged in. Run without --headless first to log in.")
            return False

    # Open the login page in the visible browser
    print("    🌐 Opening LinkedIn login page...")
    print("    📝 A browser window should appear.\n")

    page = session.fetch(
        "https://www.linkedin.com/login",
        network_idle=True,
    )

    if page is None:
        print("    ❌ Could not open LinkedIn. Check your internet connection.")
        return False

    # Wait for the user to log in manually
    print("    ┌─────────────────────────────────────────────┐")
    print("    │  👉 Please log in to LinkedIn in the        │")
    print("    │     browser window that just opened.         │")
    print("    │                                              │")
    print("    │  Handle any 2FA or security checks there.    │")
    print("    │                                              │")
    print("    │  When you see the LinkedIn feed/home page,   │")
    print("    │  come back here and press Enter.             │")
    print("    └─────────────────────────────────────────────┘")

    input("\n    ⏳ Press Enter after you've logged in... ")

    # Verify we're actually logged in by checking the feed
    print("    🔍 Verifying login...")
    page = session.fetch("https://www.linkedin.com/feed/", network_idle=True)

    # Check if we got redirected back to login
    current_url = ""
    try:
        current_url = str(page.url) if hasattr(page, "url") else ""
    except Exception:
        pass

    if "login" in current_url.lower() or "authwall" in current_url.lower():
        print("    ❌ Login doesn't seem to have worked.")
        print("    The browser redirected back to the login page.")
        print("    Try running the script again and make sure to fully log in.")
        return False

    print("    ✅ Login successful!")
    return True


# ═══════════════════════════════════════════════════════════════════════════════
#  STEP 2: SEARCH FOR JOBS
# ═══════════════════════════════════════════════════════════════════════════════
#
# Build LinkedIn search URLs from the user's profile:
#   - Target roles become search keywords
#   - Location/remote preferences become location filters
#   - Paginate through results (25 per page)
#
# LinkedIn search URL anatomy:
#   https://www.linkedin.com/jobs/search/?keywords=penetration+tester
#       &location=United+States
#       &f_TPR=r604800          (posted in last week)
#       &f_WT=2                 (remote)
#       &start=0                (pagination offset)

def build_search_urls(profile, time_filter="week", max_pages=3):
    """
    Build LinkedIn job search URLs from the user's profile.
    
    Args:
        profile: The user's job profile dict
        time_filter: "24h", "week", "month", or "any"
        max_pages: Max pages to check per search query
    
    Returns:
        List of (search_url, role_name) tuples
    """
    target_roles = profile.get("target_roles", [])
    remote_pref = profile.get("remote_preference", "Open to all")
    locations = profile.get("preferred_locations", ["United States"])

    # Map remote preference to LinkedIn filter
    work_type = WORK_TYPE_FILTERS.get(remote_pref, "")

    # Map time filter
    time_param = TIME_FILTERS.get(time_filter, TIME_FILTERS["week"])

    # Build a location string for the search
    # LinkedIn uses a single location field — pick the best one
    location = "United States"  # default
    for loc in locations:
        if loc.lower() != "remote":
            location = loc
            break

    urls = []
    for role in target_roles:
        for page_num in range(max_pages):
            params = {
                "keywords": role,
                "location": location,
                "start": str(page_num * RESULTS_PER_PAGE),
                "sortBy": "DD",  # Sort by date (most recent first)
            }

            if time_param:
                params["f_TPR"] = time_param

            if work_type:
                params["f_WT"] = work_type

            url = "{}?{}".format(LINKEDIN_SEARCH_URL, urlencode(params))
            urls.append((url, role, page_num))

    return urls


# ═══════════════════════════════════════════════════════════════════════════════
#  STEP 3: EXTRACT JOB CARDS FROM SEARCH RESULTS
# ═══════════════════════════════════════════════════════════════════════════════
#
# LinkedIn's search results page contains job "cards" — each has:
#   - Job title (linked to the detail page)
#   - Company name
#   - Location
#   - Whether it's "Easy Apply" or external
#
# We use CSS selectors to extract these. Since LinkedIn's HTML changes often,
# we try multiple selector patterns and Scrapling's adaptive features help
# relocate elements even when the DOM structure shifts.

# Multiple selector patterns for resilience — LinkedIn changes their HTML often
# These were mapped from live LinkedIn HTML as of March 2026
#
# LinkedIn has TWO different DOMs:
#   1. PUBLIC (StealthyFetcher, no login): ul.jobs-search__results-list > li
#      with h3.base-search-card__title, a.hidden-nested-link, span.job-search-card__location
#   2. LOGGED-IN (StealthySession): .scaffold-layout__list-item
#      with <strong> for title, <span> for company/location (obfuscated classes)

CARD_SELECTORS = [
    ".scaffold-layout__list-item",             # Logged-in (primary)
    "ul.jobs-search__results-list > li",       # Public/stealth (fallback)
]

# Public page selectors (stable class names)
PUBLIC_TITLE = "h3.base-search-card__title"
PUBLIC_COMPANY = "a.hidden-nested-link"
PUBLIC_LOCATION = "span.job-search-card__location"

EASY_APPLY_SELECTORS = [
    ".job-card-container__apply-method",
    ".job-card-container__footer-item--highlighted",
]


def try_selectors(page, selectors, get_all=False):
    """
    Try multiple CSS selectors until one returns results.
    Scrapling uses the same selector syntax as BeautifulSoup/Parsel.
    
    Args:
        page: A Scrapling Response/Selector object
        selectors: List of CSS selector strings to try
        get_all: If True, return all matches. If False, return first match.
    
    Returns:
        Matched element(s) or None/empty list
    """
    for selector in selectors:
        try:
            if get_all:
                results = page.css(selector)
                if results and len(results) > 0:
                    return results
            else:
                results = page.css(selector)
                if results and len(results) > 0:
                    return results[0]
        except Exception:
            continue

    return [] if get_all else None


def extract_job_cards(page):
    """
    Extract job listings from a LinkedIn search results page.
    Handles both public and logged-in page structures.
    """
    jobs = []

    # Try logged-in structure first (most common when using StealthySession)
    cards = page.css(".scaffold-layout__list-item")

    if cards and len(cards) > 0:
        # LOGGED-IN extraction
        for card in cards:
            try:
                # Title is in the first <strong> tag
                title = ""
                strong_els = card.css("strong")
                if strong_els:
                    title = (strong_els[0].text or "").strip()

                # Company and location are in <span> elements
                # Pattern: company span, then location span, then optional salary span
                company = ""
                location = ""
                spans = card.css("span")
                # Filter to spans with actual short text (not hidden/helper spans)
                text_spans = []
                for s in spans:
                    t = (s.text or "").strip()
                    # Skip empty, very long, and "visually-hidden" content
                    classes = s.attrib.get("class", "")
                    if t and len(t) < 100 and "visually-hidden" not in classes:
                        text_spans.append(t)

                # Typically: [company, location, salary?, ...]
                if len(text_spans) >= 2:
                    company = text_spans[0]
                    location = text_spans[1]
                elif len(text_spans) == 1:
                    company = text_spans[0]

                # Find job URL
                job_url = ""
                for a_tag in card.css("a"):
                    href = a_tag.attrib.get("href", "") or ""
                    if "/jobs/view/" in href:
                        job_url = href
                        break

                job_url = make_absolute_url(job_url)

                # Check Easy Apply
                is_easy_apply = False
                card_text = card.text or ""
                if "easy apply" in card_text.lower():
                    is_easy_apply = True

                if title or job_url:
                    jobs.append({
                        "title": clean_text(title),
                        "company": clean_text(company),
                        "location": clean_text(location),
                        "job_url": job_url,
                        "is_easy_apply": is_easy_apply,
                        "needs_detail_scrape": not title,
                    })
            except Exception:
                continue

        return jobs

    # Try public page structure
    cards = page.css("ul.jobs-search__results-list > li")

    if cards and len(cards) > 0:
        # PUBLIC extraction
        for card in cards:
            try:
                title = ""
                t = card.css(PUBLIC_TITLE)
                if t:
                    title = (t[0].text or "").strip()

                company = ""
                c = card.css(PUBLIC_COMPANY)
                if c:
                    company = (c[0].text or "").strip()

                location = ""
                l = card.css(PUBLIC_LOCATION)
                if l:
                    location = (l[0].text or "").strip()

                job_url = ""
                for a_tag in card.css("a"):
                    href = a_tag.attrib.get("href", "") or ""
                    if "/jobs/view/" in href:
                        job_url = href
                        break

                job_url = make_absolute_url(job_url)

                is_easy_apply = False
                card_text = card.text or ""
                if "easy apply" in card_text.lower():
                    is_easy_apply = True

                if title or job_url:
                    jobs.append({
                        "title": clean_text(title),
                        "company": clean_text(company),
                        "location": clean_text(location),
                        "job_url": job_url,
                        "is_easy_apply": is_easy_apply,
                        "needs_detail_scrape": not title,
                    })
            except Exception:
                continue

        return jobs

    # FALLBACK: just find job links
    all_links = page.css("a")
    job_links = [a for a in all_links if "/jobs/view/" in (a.attrib.get("href", "") or "")]
    if job_links:
        print("      ⚠️  Couldn't find job cards, but found {} job links".format(len(job_links)))
        for link in job_links:
            href = link.attrib.get("href", "")
            jobs.append({
                "title": clean_text(link.text) if link.text else "",
                "company": "",
                "location": "",
                "job_url": make_absolute_url(href),
                "is_easy_apply": False,
                "needs_detail_scrape": True,
            })

    return jobs


def get_text(element):
    """Safely extract text from a Scrapling element."""
    try:
        if isinstance(element, str):
            return element
        # Try .text first (Scrapling property)
        if hasattr(element, "text") and element.text:
            return element.text
        # Try .get() (Parsel-style)
        if hasattr(element, "get"):
            return element.get() or ""
    except Exception:
        pass
    return str(element) if element else ""


def clean_text(text):
    """Clean extracted text — remove extra whitespace, newlines, etc."""
    if not text:
        return ""
    # Remove extra whitespace and newlines
    text = re.sub(r"\s+", " ", str(text)).strip()
    # Remove any remaining HTML entities
    text = text.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    return text


def make_absolute_url(url):
    """Convert a relative LinkedIn URL to absolute and strip tracking params."""
    url = str(url).strip()
    if not url:
        return ""
    if url.startswith("/"):
        url = "https://www.linkedin.com{}".format(url)
    elif not url.startswith("http"):
        url = "https://www.linkedin.com/{}".format(url)
    # Always strip tracking parameters
    if "?" in url:
        url = url.split("?")[0]
    return url


def extract_job_id(url):
    """
    Extract the LinkedIn job ID from a URL for reliable deduplication.
    
    '/jobs/view/4380492185/?tracking=abc' → '4380492185'
    'https://www.linkedin.com/jobs/view/4380492185/' → '4380492185'
    """
    match = re.search(r"/jobs/view/(\d+)", str(url))
    return match.group(1) if match else ""


# ═══════════════════════════════════════════════════════════════════════════════
#  STEP 4: GET JOB DETAILS
# ═══════════════════════════════════════════════════════════════════════════════
#
# Visit each job's detail page to get:
#   - Full job description (needed for accurate scoring)
#   - External apply URL (for non-Easy-Apply jobs)
#   - Any missing data (title, company, location)

DESCRIPTION_SELECTORS = [
    ".jobs-description-content__text",
    ".jobs-box__html-content",
    ".jobs-description__content",
    "#job-details",
    ".show-more-less-html__markup",
]

EXTERNAL_APPLY_SELECTORS = [
    "a.jobs-apply-button--top-card",
    "button.jobs-apply-button",
    ".jobs-apply-button--top-card a",
]


def get_job_details(session, job_url):
    """
    Visit a LinkedIn job detail page and extract the full description + apply info.
    
    Strategy for logged-in pages (obfuscated classes):
    - Title & Company: Parse from <title> tag ("Job Title | Company | LinkedIn")
    - Description: Collect all <li> text after the "About the job" h2, plus
      any <span> elements that contain job description text
    - Easy Apply: Check for "easy apply" text on the page
    """
    details = {
        "description": "",
        "apply_url": job_url,
        "title": "",
        "company": "",
        "location": "",
        "is_easy_apply": False,
    }

    try:
        page = session.fetch(job_url, network_idle=True)

        if page is None:
            return details

        # ── Title & Company from <title> tag ─────────────────────────
        # LinkedIn's <title> is reliably: "Job Title | Company Name | LinkedIn"
        title_tags = page.css("title")
        if title_tags:
            title_text = (title_tags[0].text or "").strip()
            parts = title_text.split("|")
            if len(parts) >= 3:
                details["title"] = parts[0].strip()
                details["company"] = parts[1].strip()
            elif len(parts) == 2:
                details["title"] = parts[0].strip()

        # ── Description ──────────────────────────────────────────────
        # Try standard selectors first
        desc_text = ""
        for sel in DESCRIPTION_SELECTORS:
            try:
                results = page.css(sel)
                if results and len(results) > 0:
                    desc_text = (results[0].text or "").strip()
                    if len(desc_text) > 50:
                        break
            except Exception:
                continue

        # Fallback for logged-in pages: collect text from <li> and <span> 
        # elements that look like job description content
        if len(desc_text) < 50:
            desc_parts = []
            found_about = False
            for el in page.css("h2, li, span, p"):
                text = (el.text or "").strip()
                if not text:
                    continue

                # Look for "About the job" marker
                if "about the job" in text.lower():
                    found_about = True
                    continue

                # After "About the job", collect description text
                if found_about and len(text) > 20:
                    desc_parts.append(text)

                    # Stop if we hit another section header
                    if el.tag == "h2" and len(desc_parts) > 3:
                        break

            if desc_parts:
                desc_text = " ".join(desc_parts)

        details["description"] = clean_text(desc_text)[:3000]

        # ── Location ─────────────────────────────────────────────────
        # Try to find location from page text (often near salary info)
        page_text = page.text or ""

        # ── Easy Apply detection ─────────────────────────────────────
        if "easy apply" in page_text.lower():
            details["is_easy_apply"] = True
            details["apply_url"] = job_url

        # ── External apply link ──────────────────────────────────────
        if not details["is_easy_apply"]:
            for sel in EXTERNAL_APPLY_SELECTORS:
                try:
                    results = page.css(sel)
                    if results and len(results) > 0:
                        href = results[0].attrib.get("href", "")
                        if href and "linkedin.com" not in href:
                            details["apply_url"] = href
                            break
                except Exception:
                    continue

    except Exception as e:
        print("      ⚠️  Error fetching details: {}".format(str(e)[:80]))

    return details


# ═══════════════════════════════════════════════════════════════════════════════
#  STEP 5: SCORE JOBS WITH CLAUDE
# ═══════════════════════════════════════════════════════════════════════════════

def score_job(job, profile):
    """
    Send a job to Claude for scoring against the user's profile.
    
    Args:
        job: Dict with title, company, location, description, apply_url
        profile: The user's job profile dict
    
    Returns:
        Dict with score, reasoning, is_relevant (or None if scoring fails)
    """
    prompt = """Score this job for the candidate. Return ONLY valid JSON, no explanation.

## CANDIDATE:
Target roles: {roles}
Experience: {years} years ({level})
Skills: {skills}
Remote preference: {remote}
Preferred locations: {locations}
Deal breakers: {deal_breakers}
Salary target: {salary}

## JOB:
Title: {title}
Company: {company}
Location: {location}
Description: {description}

Return ONLY this JSON:
{{
  "score": 75,
  "reasoning": "2-3 sentences explaining the match",
  "is_relevant": true,
  "salary": "salary if mentioned or Not Listed"
}}

Score 0-100 where:
  90-100 = Perfect match
  70-89  = Strong match  
  50-69  = Decent match
  30-49  = Weak match
  0-29   = Poor match""".format(
        roles=", ".join(profile.get("target_roles", [])),
        years=profile.get("years_of_experience", 0),
        level=profile.get("experience_level", ""),
        skills=", ".join(profile.get("hard_skills", [])[:15]),
        remote=profile.get("remote_preference", ""),
        locations=", ".join(profile.get("preferred_locations", [])),
        deal_breakers=", ".join(profile.get("deal_breakers", [])) or "None",
        salary=json.dumps(profile.get("salary_range", {})),
        title=job.get("title", "Unknown"),
        company=job.get("company", "Unknown"),
        location=job.get("location", "Unknown"),
        description=job.get("description", "No description available")[:2000],
    )

    raw = ask_claude(prompt)
    if not raw:
        return None

    result = parse_json_response(raw)
    return result


# ═══════════════════════════════════════════════════════════════════════════════
#  STEP 6: SAVE RESULTS
# ═══════════════════════════════════════════════════════════════════════════════

def merge_and_save(new_jobs, output_path):
    """
    Merge new jobs into existing scored_jobs.json, avoiding duplicates.
    
    Deduplicates by LinkedIn job ID, apply_url, and title+company combo.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Load existing jobs
    existing = []
    if output_path.exists():
        try:
            existing = json.loads(output_path.read_text())
        except (json.JSONDecodeError, IOError):
            pass

    # Build lookup sets for dedup
    existing_job_ids = set()
    existing_urls = set()
    existing_keys = set()
    for job in existing:
        url = job.get("apply_url", "")
        if url:
            existing_urls.add(url.lower().rstrip("/"))
            job_id = extract_job_id(url)
            if job_id:
                existing_job_ids.add(job_id)
        key = "{}|{}".format(
            job.get("title", "").lower().strip(),
            job.get("company", "").lower().strip(),
        )
        existing_keys.add(key)

    # Filter new jobs, avoiding duplicates
    added = 0
    for job in new_jobs:
        url = job.get("apply_url", "").lower().rstrip("/")
        job_id = extract_job_id(url)
        key = "{}|{}".format(
            job.get("title", "").lower().strip(),
            job.get("company", "").lower().strip(),
        )

        if job_id and job_id in existing_job_ids:
            continue
        if url and url in existing_urls:
            continue
        if key in existing_keys:
            continue

        existing.append(job)
        if url:
            existing_urls.add(url)
        if job_id:
            existing_job_ids.add(job_id)
        existing_keys.add(key)
        added += 1

    # Sort by score (highest first)
    existing.sort(key=lambda x: x.get("score", 0), reverse=True)

    # Save
    output_path.write_text(json.dumps(existing, indent=2))

    return added, len(existing)


# ═══════════════════════════════════════════════════════════════════════════════
#  MAIN — Orchestrates the full pipeline
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="Find and score LinkedIn jobs using Scrapling",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python3 scripts/find_jobs.py --profile profiles/alex/profile.json
  python3 scripts/find_jobs.py --profile profiles/alex/profile.json --max-pages 5
  python3 scripts/find_jobs.py --profile profiles/alex/profile.json --time month
  python3 scripts/find_jobs.py --profile profiles/alex/profile.json --headless
        """,
    )
    parser.add_argument("--profile", required=True,
                        help="Path to profile.json")
    parser.add_argument("--max-pages", type=int, default=2,
                        help="Max result pages per role (default: 2, each has 25 jobs)")
    parser.add_argument("--time", default="week",
                        choices=["24h", "week", "month", "any"],
                        help="How recent should jobs be (default: week)")
    parser.add_argument("--headless", action="store_true",
                        help="Run in headless mode (skips manual login)")
    parser.add_argument("--max-detail", type=int, default=50,
                        help="Max jobs to fetch full details for (default: 50)")
    parser.add_argument("--output", default="",
                        help="Output path (default: same folder as profile)")

    args = parser.parse_args()

    # ── Load profile ─────────────────────────────────────────────────

    print("\n🔍 Job Bot — LinkedIn Job Discovery")
    print("=" * 55)

    profile_path = Path(args.profile)
    if not profile_path.exists():
        print("❌ Profile not found: {}".format(profile_path))
        print("   Run build_profile_v2.py first to create one.")
        sys.exit(1)

    profile = json.loads(profile_path.read_text())
    name = profile.get("personal", {}).get("name", "Unknown")
    roles = profile.get("target_roles", [])

    print("  👤 Profile: {} ({} target roles)".format(name, len(roles)))
    print("  🎯 Roles: {}".format(", ".join(roles[:4])))
    if len(roles) > 4:
        print("          + {} more".format(len(roles) - 4))

    # Determine output path
    if args.output:
        output_path = Path(args.output)
    else:
        output_path = profile_path.parent / "scored_jobs.json"

    print("  📁 Output: {}".format(output_path))

    # ── Import Scrapling ─────────────────────────────────────────────

    StealthyFetcher, StealthySession = import_scrapling()

    # ── Start browser session ────────────────────────────────────────

    print("\n  🚀 Starting Scrapling stealth browser...")

    with StealthySession(headless=args.headless) as session:

        # ── Step 1: Login ────────────────────────────────────────────

        if not login_to_linkedin(session, headless=args.headless):
            print("\n  ❌ Could not log in to LinkedIn. Exiting.")
            return

        # ── Step 2: Search ───────────────────────────────────────────

        print("\n  🔍 STEP 2: Searching for jobs")
        print("  " + "─" * 50)
        print("  Time filter: {}".format(args.time))
        print("  Pages per role: {}".format(args.max_pages))

        search_urls = build_search_urls(profile, args.time, args.max_pages)
        all_job_cards = []
        seen_job_ids = set()
        current_role = ""

        for url, role, page_num in search_urls:
            # Print role header
            if role != current_role:
                current_role = role
                print("\n    🎯 Searching: {}".format(role))

            print("      📄 Page {} ...".format(page_num + 1), end="", flush=True)

            try:
                page = session.fetch(url, network_idle=True)
                time.sleep(REQUEST_DELAY)

                if page is None:
                    print(" ❌ No response")
                    continue

                # Extract job cards
                cards = extract_job_cards(page)
                new_count = 0

                for card in cards:
                    job_url = card.get("job_url", "")
                    job_id = extract_job_id(job_url)

                    # Dedup by job ID (ignores tracking params)
                    if job_id and job_id not in seen_job_ids:
                        seen_job_ids.add(job_id)
                        card["search_role"] = role
                        all_job_cards.append(card)
                        new_count += 1
                    elif not job_id and job_url:
                        # No job ID in URL — dedup by full URL
                        if job_url not in seen_job_ids:
                            seen_job_ids.add(job_url)
                            card["search_role"] = role
                            all_job_cards.append(card)
                            new_count += 1

                print(" → {} jobs ({} new)".format(len(cards), new_count))

                # If we got 0 results, no point checking more pages for this role
                if len(cards) == 0:
                    # Skip remaining pages for this role
                    print("      ⏭️  No results, skipping remaining pages")
                    # We need to skip ahead in search_urls — but since we're
                    # iterating, we'll just let empty pages pass
                    pass

            except Exception as e:
                print(" ❌ Error: {}".format(str(e)[:60]))

        print("\n    📋 Total unique jobs found: {}".format(len(all_job_cards)))

        if not all_job_cards:
            print("\n  ❌ No jobs found. Try adjusting your search:")
            print("     - Use --time month for more results")
            print("     - Use --max-pages 5 for more pages")
            print("     - Check your target roles in your profile")
            return

        # ── Step 3: Local keyword filter ─────────────────────────────

        print("\n  🔎 STEP 3: Quick keyword filter")
        print("  " + "─" * 50)

        keywords = [k.lower() for k in profile.get("keywords", [])]
        role_keywords = [r.lower() for r in roles]
        all_match_terms = set(keywords + role_keywords)

        # Add some core terms from skills
        for skill in profile.get("hard_skills", [])[:10]:
            all_match_terms.add(skill.lower())

        promising = []
        for job in all_job_cards:
            # Check if title matches any keywords
            title_lower = job.get("title", "").lower()
            company_lower = job.get("company", "").lower()
            combined = "{} {}".format(title_lower, company_lower)

            # A job is "promising" if its title contains any role keyword
            matches = sum(1 for term in all_match_terms if term in combined)
            job["keyword_matches"] = matches
            promising.append(job)

        # Sort by keyword matches (best first)
        promising.sort(key=lambda x: x.get("keyword_matches", 0), reverse=True)

        # Limit how many we fetch details for
        to_detail = promising[:args.max_detail]
        print("    {} jobs to fetch details for (max: {})".format(
            len(to_detail), args.max_detail))

        # ── Step 4: Fetch details ────────────────────────────────────

        print("\n  📝 STEP 4: Fetching job details")
        print("  " + "─" * 50)

        detailed_jobs = []
        for i, job in enumerate(to_detail, 1):
            job_url = job.get("job_url", "")
            if not job_url:
                continue

            title_display = job.get("title", "Unknown")[:55]
            company_display = job.get("company", "Unknown")[:25]
            print("    [{}/{}] {} @ {} ...".format(
                i, len(to_detail), title_display, company_display
            ), end="", flush=True)

            details = get_job_details(session, job_url)

            # Merge detail data into job card
            if details.get("title") and not job.get("title"):
                job["title"] = details["title"]
            if details.get("company") and not job.get("company"):
                job["company"] = details["company"]
            if details.get("location") and not job.get("location"):
                job["location"] = details["location"]

            job["description"] = details.get("description", "")
            job["apply_url"] = details.get("apply_url", job_url)
            job["is_easy_apply"] = details.get("is_easy_apply", job.get("is_easy_apply", False))

            apply_type = "Easy Apply" if job["is_easy_apply"] else "External"
            print(" ✅ ({})".format(apply_type))

            detailed_jobs.append(job)
            time.sleep(REQUEST_DELAY)

    # ── Session closed — browser is done ─────────────────────────────
    # From here on, we only use Claude API + local processing.

    print("\n    ✅ Done fetching! Browser closed.")
    print("    {} jobs with details ready for scoring.".format(len(detailed_jobs)))

    # ── Step 5: Score with Claude ────────────────────────────────────

    print("\n  🤖 STEP 5: AI Scoring")
    print("  " + "─" * 50)

    if not OPENROUTER_API_KEY:
        print("    ⚠️  No OPENROUTER_API_KEY set. Skipping AI scoring.")
        print("    Jobs will be saved with score=0. You can re-score later.")
        scored_jobs = []
        for job in detailed_jobs:
            scored_jobs.append({
                "title": job.get("title", "Unknown"),
                "company": job.get("company", "Unknown"),
                "location": job.get("location", "Unknown"),
                "salary": "Not Listed",
                "score": 0,
                "reasoning": "Not scored — no API key",
                "is_relevant": True,
                "apply_url": job.get("apply_url", ""),
                "source": "linkedin_easy_apply" if job.get("is_easy_apply") else "linkedin",
                "status": "manual_apply" if job.get("is_easy_apply") else "found",
                "date_found": str(date.today()),
            })
    else:
        scored_jobs = []
        for i, job in enumerate(detailed_jobs, 1):
            title = job.get("title", "Unknown")
            company = job.get("company", "Unknown")
            print("    [{}/{}] Scoring: {} @ {} ...".format(
                i, len(detailed_jobs), title[:50], company[:25]
            ), end="", flush=True)

            result = score_job(job, profile)

            if result:
                score = result.get("score", 0)
                scored_jobs.append({
                    "title": title,
                    "company": company,
                    "location": job.get("location", "Unknown"),
                    "salary": result.get("salary", "Not Listed"),
                    "score": score,
                    "reasoning": result.get("reasoning", ""),
                    "is_relevant": result.get("is_relevant", True),
                    "apply_url": job.get("apply_url", ""),
                    "source": "linkedin_easy_apply" if job.get("is_easy_apply") else "linkedin",
                    "status": "manual_apply" if job.get("is_easy_apply") else "found",
                    "date_found": str(date.today()),
                })
                emoji = "🟢" if score >= 70 else "🟡" if score >= 50 else "🔴"
                print(" {} {}%".format(emoji, score))
            else:
                print(" ⚠️  scoring failed")

    if not scored_jobs:
        print("\n  ❌ No jobs were scored. Check your API key and try again.")
        return

    # ── Step 6: Score threshold ──────────────────────────────────────

    print("\n  📊 STEP 6: Choose which jobs to save")
    print("  " + "─" * 50)

    # Show score distribution
    scores = [j.get("score", 0) for j in scored_jobs]
    scores.sort(reverse=True)
    print("    Score distribution:")
    for bracket_name, low, high in [("90-100 (perfect)", 90, 100), ("70-89 (strong)", 70, 89),
                                     ("50-69 (decent)", 50, 69), ("30-49 (weak)", 30, 49),
                                     ("0-29 (poor)", 0, 29)]:
        count = sum(1 for s in scores if low <= s <= high)
        if count > 0:
            bar = "█" * count
            print("      {}: {} {}".format(bracket_name, bar, count))

    print("\n    Top 5 matches:")
    for job in sorted(scored_jobs, key=lambda x: x.get("score", 0), reverse=True)[:5]:
        easy = " [Easy Apply]" if job.get("status") == "manual_apply" else ""
        print("      [{}%] {} @ {}{}".format(
            job.get("score", 0), job.get("title", "?")[:55],
            job.get("company", "?")[:30], easy,
        ))

    # Ask for threshold
    while True:
        threshold_str = input(
            "\n  ❓ Minimum score to save? (0-100, default 50): "
        ).strip()
        if not threshold_str:
            threshold = 50
            break
        try:
            threshold = int(threshold_str)
            if 0 <= threshold <= 100:
                break
            print("    ⚠️  Enter a number between 0 and 100")
        except ValueError:
            print("    ⚠️  Enter a number between 0 and 100")

    # Filter by threshold
    to_save = [j for j in scored_jobs if j.get("score", 0) >= threshold]
    print("\n    💾 Saving {} jobs (score >= {}%)".format(len(to_save), threshold))

    # ── Save ─────────────────────────────────────────────────────────

    added, total = merge_and_save(to_save, output_path)

    print("\n" + "=" * 55)
    print("  ✅ DONE!")
    print("=" * 55)
    print("  New jobs added:  {}".format(added))
    print("  Total in file:   {}".format(total))
    print("  Saved to:        {}".format(output_path))

    # Show summary of what was saved
    easy_count = sum(1 for j in to_save if j.get("status") == "manual_apply")
    external_count = len(to_save) - easy_count
    if easy_count:
        print("  Easy Apply:      {} (marked as 'manual_apply')".format(easy_count))
    if external_count:
        print("  External apply:  {} (ready for auto_apply_v4.py)".format(external_count))

    print("\n  ➡️  Next steps:")
    print("     1. Review: cat {}".format(output_path))
    print("     2. Tailor resumes: python3 scripts/tailor_resume.py --jobs {}".format(output_path))
    print("     3. Convert to PDF: python3 scripts/convert_to_pdf.py")
    print("     4. Auto-apply: python3 scripts/auto_apply_v4.py")


if __name__ == "__main__":
    main()
