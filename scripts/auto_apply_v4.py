#!/usr/bin/env python3
"""
Job Bot - Auto-Apply Engine v4.0
Deterministic DOM parsing + robust async React-Select handling.

Key changes from v3:
- Location (City) fix: types just city name, not "City, State" (API match issue)
- Post-type debounce wait for async API-backed dropdowns (2s after last keystroke)
- Multi-strategy option selector: select__option, role=option, listbox children
- Slower keystrokes (100ms) for async fields to let API debounce fire
- DOM debug dump on final failure for easier troubleshooting
- More retries (3 instead of 2) for flaky async fields
"""

import json, os, sys, time, argparse, re
from pathlib import Path
import requests

# ─── Config ───────────────────────────────────────────────────────────────────

BROWSERBASE_API_KEY = os.environ.get("BROWSERBASE_API_KEY", "")
BROWSERBASE_PROJECT = os.environ.get("BROWSERBASE_PROJECT_ID", "")
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")
OPENROUTER_BASE = "https://openrouter.ai/api/v1/chat/completions"
MODEL = "anthropic/claude-sonnet-4-5"

# Browser mode: "local" or "cloud"
BROWSER_MODE = "local"

# Cookie/session storage directory
COOKIE_DIR = Path("profiles/.browser_sessions")

# ATS platform detection — maps URL patterns to platform names
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


def detect_ats_platform(url):
    """Detect which ATS platform a URL belongs to."""
    url_lower = url.lower()
    for pattern, platform in ATS_PLATFORMS.items():
        if pattern in url_lower:
            return platform
    return "unknown"


def get_session_path(platform):
    """Get the path to saved browser session for an ATS platform."""
    COOKIE_DIR.mkdir(parents=True, exist_ok=True)
    return COOKIE_DIR / "{}_session.json".format(platform)


def has_saved_session(platform):
    """Check if we have a saved browser session for this ATS."""
    path = get_session_path(platform)
    return path.exists()


def save_browser_session(context, platform):
    """Save browser cookies/session state for reuse."""
    path = get_session_path(platform)
    COOKIE_DIR.mkdir(parents=True, exist_ok=True)
    try:
        context.storage_state(path=str(path))
        print(f"  💾 Session saved for {platform} (reusable for future apps)")
    except Exception as e:
        print(f"  ⚠️  Could not save session: {e}")

# ─── Utilities ────────────────────────────────────────────────────────────────

def ask_claude(prompt):
    """Call Claude via OpenRouter (only used for non-Greenhouse forms)."""
    resp = requests.post(OPENROUTER_BASE,
        headers={"Authorization": f"Bearer {OPENROUTER_API_KEY}", "Content-Type": "application/json"},
        json={"model": MODEL, "messages": [{"role": "user", "content": prompt}],
              "max_tokens": 4000, "temperature": 0.1})
    data = resp.json()
    try:
        return data["choices"][0]["message"]["content"].strip()
    except Exception as e:
        print(f"  ❌ Claude error: {e}")
        return ""


def create_session():
    """Create a browser session — local or cloud (Browserbase)."""
    if BROWSER_MODE == "local":
        print("  🌐 Starting local browser...")
        return "local", "local"

    # Cloud mode: Browserbase
    print("  🌐 Starting cloud browser...")
    if not BROWSERBASE_API_KEY or not BROWSERBASE_PROJECT:
        print("  ❌ Browserbase keys not set. Use --local or set BROWSERBASE_API_KEY")
        return None, None
    resp = requests.post(
        "https://www.browserbase.com/v1/sessions",
        headers={"x-bb-api-key": BROWSERBASE_API_KEY, "Content-Type": "application/json"},
        json={"projectId": BROWSERBASE_PROJECT, "browserSettings": {"stealth": True}})
    data = resp.json()
    session_id = data.get("id")
    if not session_id:
        print(f"  ❌ Session error: {data}")
        return None, None
    connect_url = (
        data.get("connectUrl")
        or f"wss://connect.browserbase.com?apiKey={BROWSERBASE_API_KEY}&sessionId={session_id}"
    )
    print(f"  ✅ Session: {session_id}")
    return session_id, connect_url


def end_session(session_id):
    """Close browser session."""
    if session_id == "local":
        print("  🔒 Browser closed")
        return
    try:
        requests.delete(
            f"https://www.browserbase.com/v1/sessions/{session_id}",
            headers={"x-bb-api-key": BROWSERBASE_API_KEY})
    except Exception:
        pass
    print("  🔒 Session closed")


def screenshot(page, name):
    """Take and save a screenshot."""
    Path("outputs/screenshots").mkdir(parents=True, exist_ok=True)
    path = f"outputs/screenshots/{name}.png"
    page.screenshot(path=path)
    print(f"  📸 {path}")
    return path


def find_tailored_files(company, title, apply_url=None):
    """
    Find tailored resume and cover letter for a job.
    
    Search strategy (in order):
    1. APPLICATION_SUMMARY.json — match by URL (most reliable)
    2. APPLICATION_SUMMARY.json — match by company name
    3. Direct filename search in outputs/tailored/
    4. Default resume from resumes/ directory
    """
    tailored_dir = Path("outputs/tailored")
    resume = None
    cover_letter = None

    # ── Strategy 1 & 2: Use APPLICATION_SUMMARY.json ──────────────────
    summary_path = tailored_dir / "00_APPLICATION_SUMMARY.json"
    if summary_path.exists():
        try:
            summary = json.loads(summary_path.read_text())

            matched_entry = None

            # Strategy 1: Match by URL (exact or partial)
            if apply_url:
                for entry in summary:
                    entry_url = entry.get("apply_url", "")
                    # Match if URLs are the same or one contains the other
                    if entry_url and (
                        entry_url == apply_url
                        or entry_url in apply_url
                        or apply_url in entry_url
                    ):
                        matched_entry = entry
                        break

            # Strategy 2: Match by company name
            if not matched_entry:
                company_lower = company.lower().strip()
                for entry in summary:
                    if entry.get("company", "").lower().strip() == company_lower:
                        matched_entry = entry
                        break
                # Fuzzy company match
                if not matched_entry:
                    for entry in summary:
                        entry_co = entry.get("company", "").lower().strip()
                        if (company_lower in entry_co or entry_co in company_lower):
                            matched_entry = entry
                            break

            if matched_entry:
                # Summary stores .txt paths — check for .pdf version first
                txt_resume = matched_entry.get("resume_file", "")
                txt_cover = matched_entry.get("cover_letter_file", "")

                # Try PDF first, fall back to TXT
                for txt_path, label in [(txt_resume, "resume"), (txt_cover, "cover_letter")]:
                    if not txt_path:
                        continue
                    pdf_path = txt_path.replace(".txt", ".pdf")
                    if Path(pdf_path).exists():
                        if label == "resume":
                            resume = str(Path(pdf_path).absolute())
                        else:
                            cover_letter = str(Path(pdf_path).absolute())
                    elif Path(txt_path).exists():
                        if label == "resume":
                            resume = str(Path(txt_path).absolute())
                        else:
                            cover_letter = str(Path(txt_path).absolute())

                if resume:
                    print(f"  📄 Resume: {Path(resume).name}")
                    if cover_letter:
                        print(f"  📄 Cover:  {Path(cover_letter).name}")
                    return resume, cover_letter

        except Exception as e:
            print(f"  ⚠️  Error reading summary: {e}")

    # ── Strategy 3: Direct filename search ────────────────────────────
    if tailored_dir.exists():
        company_norm = re.sub(r'[^a-zA-Z0-9]+', '_', company).strip('_').lower()

        for ext in ['.pdf', '.txt']:
            for file in sorted(tailored_dir.glob(f"*_RESUME{ext}"), reverse=True):
                filename = file.stem.lower()
                # Check if company name appears in filename
                if company_norm in filename.replace('.', '_'):
                    resume = str(file.absolute())
                    # Find matching cover letter
                    cover_name = file.name.replace(f"_RESUME{ext}", f"_COVER_LETTER{ext}")
                    cover_file = file.parent / cover_name
                    if cover_file.exists():
                        cover_letter = str(cover_file.absolute())
                    print(f"  📄 Resume: {file.name} (filename match)")
                    if cover_letter:
                        print(f"  📄 Cover:  {Path(cover_letter).name}")
                    return resume, cover_letter

    # ── Strategy 4: Default resume ────────────────────────────────────
    for candidate in [
        "resumes/my_resume.txt", "resumes/my_resume.pdf",
        "profiles/resume.pdf", "profiles/resume.txt",
    ]:
        if Path(candidate).exists():
            resume = str(Path(candidate).absolute())
            print(f"  📄 Resume: {candidate} (default — not tailored)")
            return resume, None

    if not resume:
        print(f"  ⚠️  No resume found for {company}")
    return None, None


# ─── Greenhouse Detection ─────────────────────────────────────────────────────

def is_greenhouse_form(page):
    """Detect if the current page is a Greenhouse job board application."""
    url = page.url.lower()
    if "greenhouse.io" in url:
        return True
    # Also check for Greenhouse embedded forms
    try:
        has_gh = page.locator("div.application--questions").count() > 0
        if has_gh:
            return True
        has_gh = page.locator("div[class*='select-shell'][class*='remix-css']").count() > 0
        return has_gh
    except Exception:
        return False


# ─── React-Select Handler (the core fix) ──────────────────────────────────────

def _get_search_text(field_id, answer):
    """
    Determine the best search text to TYPE into a React-Select field.
    
    The key principle: type the MINIMUM needed to filter the dropdown,
    then let the matching logic in step 6 pick the right option.
    Typing too much (especially punctuation or long phrases) causes
    the API/filter to return zero results.
    """
    is_location = "location" in field_id.lower() or "candidate-location" == field_id.lower()

    if is_location:
        # Type ONLY the city name — the Greenhouse geocoding API doesn't
        # understand "Florence SC" format. It needs just "Florence" and
        # returns results like "Florence, South Carolina, United States".
        city = answer.split(",")[0].strip()
        return city

    # For short answers (Yes, No, Male, etc.) — type as-is
    if len(answer) <= 10:
        return answer

    # For longer answers, type just the first word before any comma/punctuation.
    # "No, I don't have a disability" → "No"
    # "I am not a protected veteran" → "I am not"
    # "I don't wish to answer" → "I don"  (bad! apostrophe breaks search)
    #
    # Strategy: take the first segment before a comma, then cap at
    # the first few words. This gives enough to filter without
    # typing garbage characters that break the search.
    first_segment = answer.split(",")[0].strip()
    words = first_segment.split()
    # Use up to 3 words from the first segment
    search = " ".join(words[:3])
    return search


def _find_options(page, field_id):
    """
    Find dropdown option elements scoped to the ACTIVE dropdown menu
    for a specific field. This prevents picking up options from other
    dropdowns on the page (like the phone country code picker).

    Returns a Playwright locator for the matching options, or None.
    """
    # React-select renders the menu as a sibling of the control inside
    # a container div. Find the select container for this field first.
    # The structure is typically:
    #   div.select__container (or div.select-shell)
    #     div.select__control  (contains the input)
    #     div.select__menu     (appears when open)
    #       div.select__menu-list
    #         div.select__option (one per option)

    # Strategy 1: Find menu within the same select container as our input
    for container_class in ['select-shell', 'select__container', 'select']:
        container = page.locator(
            f"input#{field_id} >> xpath=ancestor::div[contains(@class,'{container_class}')]"
        )
        if container.count() > 0:
            # Look for options within this container
            opts = container.first.locator("div[class*='select__option']")
            if opts.count() > 0:
                return opts

            # Try role="option" within the container
            opts = container.first.locator("[role='option']")
            if opts.count() > 0:
                return opts

    # Strategy 2: React-select sometimes renders the menu in a portal
    # (appended to body, not inside the container). In that case,
    # look for the most recently added select__menu on the page.
    menu = page.locator("div[class*='select__menu']")
    if menu.count() > 0:
        # Use the last one (most recently opened)
        opts = menu.last.locator("div[class*='select__option']")
        if opts.count() > 0:
            return opts

    # Strategy 3: ARIA listbox (scoped — not the phone picker)
    # The phone picker uses role="listbox" inside .iti__dropdown-content,
    # so exclude that.
    listbox = page.locator("[role='listbox']:not(.iti__country-list)")
    if listbox.count() > 0:
        opts = listbox.last.locator("[role='option']")
        if opts.count() > 0:
            return opts

    return None


def fill_react_select(page, field_id, answer, retries=3):
    """
    Fill a Greenhouse React-Select dropdown.

    Strategy (v4.1 — "open first, read, then pick"):
    1. Click to open the dropdown WITHOUT typing anything
    2. If options appear → read them all, pick the best match
    3. If NO options appear → it's an async/search field (like Location),
       so type a search term, wait for API results, then pick
    4. Match using scored fuzzy matching (handles abbreviations like SC)
    """
    is_location = "location" in field_id.lower() or "candidate-location" == field_id.lower()

    for attempt in range(retries + 1):
        try:
            combobox = page.locator(f"input#{field_id}")
            if combobox.count() == 0:
                print(f"      ❌ No combobox found with id={field_id}")
                return False

            # ── Step 1: Click to open the dropdown (no typing) ────────
            container = page.locator(
                f"input#{field_id} >> xpath=ancestor::div[contains(@class,'select__control')]"
            )
            if container.count() > 0:
                container.first.click()
            else:
                combobox.click()
            time.sleep(0.5)

            # Clear any leftover text from previous attempts
            combobox.press("Control+a")
            combobox.press("Backspace")
            time.sleep(0.3)

            # ── Step 2: Check if options appeared (static dropdown) ───
            options_appeared = _wait_for_options(page, field_id, timeout=2)

            # ── Step 3: If no options, type to search (async dropdown) ─
            if not options_appeared:
                search_text = _get_search_text(field_id, answer)
                keystroke_delay = 100 if is_location else 60
                combobox.type(search_text, delay=keystroke_delay)

                # Wait for async results
                wait_time = 8 if is_location else 5
                if is_location:
                    time.sleep(2.0)  # Extra pause for API debounce
                options_appeared = _wait_for_options(page, field_id, timeout=wait_time)

            if not options_appeared:
                if attempt < retries:
                    print(f"      ↻ No options appeared, retrying... ({attempt+1})")
                    # Press Escape to close any stuck menu, then retry
                    combobox.press("Escape")
                    time.sleep(0.5)
                    continue
                else:
                    debug = _debug_dropdown(page, field_id)
                    print(f"      🔍 Debug DOM state: {debug}")
                    print(f"      ⚠️  No options rendered for {field_id}")
                    return False

            # ── Step 4: Read all options ──────────────────────────────
            options = _find_options(page, field_id)
            if options is None or options.count() == 0:
                if attempt < retries:
                    combobox.press("Escape")
                    time.sleep(0.3)
                    continue
                return False

            option_count = options.count()
            option_texts = []
            for i in range(option_count):
                try:
                    option_texts.append((i, options.nth(i).inner_text().strip()))
                except Exception:
                    option_texts.append((i, ""))

            # ── Step 5: Pick the best match ───────────────────────────
            chosen_idx = _pick_best_option(option_texts, answer, is_location)

            if chosen_idx is not None:
                chosen_text = option_texts[chosen_idx][1]
                options.nth(chosen_idx).click()
                time.sleep(0.4)
                return _verify_selection(page, field_id, answer)

            # No match found at all
            if option_count > 0:
                print(f"      ⚠️  No match found. Options: {[t for _, t in option_texts[:10]]}")
                print(f"      ℹ️  Picking first: \"{option_texts[0][1]}\"")
                options.first.click()
                time.sleep(0.4)
                return _verify_selection(page, field_id, answer)

            return False

        except Exception as e:
            if attempt < retries:
                print(f"      ↻ Error, retrying: {e}")
                time.sleep(1)
                continue
            print(f"      ❌ React-Select failed for {field_id}: {e}")
            return False

    return False


def _wait_for_options(page, field_id, timeout=3):
    """Wait for dropdown options to appear, scoped to this field's container."""
    try:
        page.wait_for_function(
            f"""() => {{
                const el = document.getElementById("{field_id}");
                if (!el) return false;

                const container = el.closest('[class*="select-shell"]')
                    || el.closest('[class*="select__container"]')
                    || el.closest('[class*="select"]');
                if (container) {{
                    const opts = container.querySelectorAll(
                        '[class*="select__option"], [role="option"]'
                    );
                    if (opts.length > 0) return true;
                }}

                const menus = document.querySelectorAll('[class*="select__menu"]');
                for (const menu of menus) {{
                    if (menu.querySelectorAll('[class*="select__option"]').length > 0) {{
                        return true;
                    }}
                }}
                return false;
            }}""",
            timeout=timeout * 1000
        )
        return True
    except Exception:
        return False


def _debug_dropdown(page, field_id):
    """Dump DOM state of a dropdown for debugging."""
    try:
        return page.evaluate(f"""() => {{
            const el = document.getElementById("{field_id}");
            if (!el) return "INPUT NOT FOUND";
            const container = el.closest('[class*="select"]');
            const menu = container?.querySelector('[class*="menu"]');
            return {{
                ariaExpanded: el.getAttribute("aria-expanded"),
                menuExists: !!menu,
                menuHTML: menu ? menu.innerHTML.substring(0, 500) : "NO MENU",
                menuClasses: menu ? menu.className : "N/A"
            }};
        }}""")
    except Exception as e:
        return f"Debug error: {e}"


# State abbreviation ↔ full name mapping (used for fuzzy matching)
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
# Build reverse map: full name → abbreviation
STATE_MAP_REVERSE = {v: k for k, v in STATE_MAP.items()}


def _pick_best_option(option_texts, answer, is_location=False):
    """
    Pick the best matching option from a list of (index, text) tuples.

    Matching priority:
    1. Exact match (case-insensitive)
    2. Abbreviation/expansion EXACT match (SC ↔ South Carolina — no substrings)
    3. Scored keyword match (for location/long answers)
    4. Yes/No-aware fuzzy keyword overlap
    5. Partial string containment
    Returns the index into option_texts, or None.
    """
    answer_lower = answer.lower().strip()

    # ── 1. Exact match ────────────────────────────────────────────
    for idx, text in option_texts:
        if text.lower().strip() == answer_lower:
            return idx

    # ── 2. Abbreviation / expansion EXACT matching ────────────────
    # Build a set of exact variants: "South Carolina" → {"south carolina", "sc"}
    # IMPORTANT: Only use EXACT equality, never substring containment,
    # because "ar" (Arkansas) appears inside "south carolina" as a substring.
    answer_variants = {answer_lower}

    if answer_lower in STATE_MAP:
        answer_variants.add(STATE_MAP[answer_lower])
    if answer_lower in STATE_MAP_REVERSE:
        answer_variants.add(STATE_MAP_REVERSE[answer_lower])

    for part in re.split(r'[,\s]+', answer):
        part_lower = part.strip().lower()
        if part_lower in STATE_MAP:
            answer_variants.add(STATE_MAP[part_lower])
            answer_variants.add(part_lower)
        if part_lower in STATE_MAP_REVERSE:
            answer_variants.add(STATE_MAP_REVERSE[part_lower])
            answer_variants.add(part_lower)

    # EXACT match only against variants — no substring matching
    for idx, text in option_texts:
        text_lower = text.lower().strip()
        if text_lower in answer_variants:
            return idx

    # ── 3. Location-specific scored matching ──────────────────────
    if is_location:
        match_terms = list(answer_variants)
        match_terms.append("united states")

        best_idx = -1
        best_score = 0
        for idx, text in option_texts:
            text_lower = text.lower()
            score = sum(1 for term in match_terms if term in text_lower)
            if score > best_score:
                best_score = score
                best_idx = idx

        if best_idx >= 0 and best_score >= 1:
            print(f"      🔍 Options: {[t for _, t in option_texts[:10]]}")
            print(f"      ✓ Best match (score={best_score}): \"{option_texts[best_idx][1]}\"")
            return best_idx

    # ── 4. Yes/No-aware fuzzy keyword matching ────────────────────
    # Critical: for answers starting with "Yes" or "No", the first word
    # MUST match. "No, I don't have a disability" must NOT match
    # "Yes, I have a disability" even though they share keywords.
    answer_first_word = answer.split(",")[0].split()[0].lower() if answer else ""
    is_yes_no = answer_first_word in ("yes", "no")

    answer_keywords = set(
        w.lower() for w in re.split(r'[\s,\-\']+', answer) if len(w) > 2
    )
    if answer_keywords:
        best_idx = -1
        best_score = -1
        for idx, text in option_texts:
            text_lower = text.lower()
            text_first_word = text.split(",")[0].split()[0].lower() if text else ""

            # If answer starts with Yes/No, SKIP options that start
            # with the opposite word
            if is_yes_no:
                if answer_first_word == "yes" and text_first_word == "no":
                    continue
                if answer_first_word == "no" and text_first_word == "yes":
                    continue

            text_words = set(
                w.lower() for w in re.split(r'[\s,\-\']+', text) if len(w) > 2
            )
            overlap = len(answer_keywords & text_words)

            # Bonus: if first words match, add a point
            if answer_first_word == text_first_word:
                overlap += 1

            if overlap > best_score:
                best_score = overlap
                best_idx = idx

        if best_idx >= 0 and best_score >= 1:
            print(f"      ✓ Fuzzy match ({best_score} keywords): \"{option_texts[best_idx][1]}\"")
            return best_idx

    # ── 5. Partial string containment (long strings only) ─────────
    # Only use this for answers longer than 3 chars to avoid
    # false matches like "ar" in "carolina"
    if len(answer_lower) > 3:
        for idx, text in option_texts:
            text_lower = text.lower()
            if answer_lower in text_lower or text_lower in answer_lower:
                return idx

    return None


def _verify_selection(page, field_id, expected_answer):
    """Verify a React-Select dropdown actually accepted the selection."""
    try:
        # After selection, React-Select shows the value in a
        # div.select__single-value sibling. Check if it exists.
        container = page.locator(
            f"input#{field_id} >> xpath=ancestor::div[contains(@class,'select-shell')]"
        )
        if container.count() > 0:
            single_val = container.locator("div[class*='select__single-value']")
            if single_val.count() > 0:
                actual = single_val.first.inner_text().strip()
                if actual:
                    print(f"      ✓ Verified: \"{actual}\"")
                    return True

        # Fallback: check the hidden required input
        hidden = page.locator(
            f"input#{field_id} >> xpath=ancestor::div[contains(@class,'select__container')]"
            f"//input[@aria-hidden='true']"
        )
        if hidden.count() > 0:
            val = hidden.first.get_attribute("value")
            if val:
                return True

        # If we can't verify but the dropdown closed, assume success
        expanded = page.evaluate(
            f'document.getElementById("{field_id}")?.getAttribute("aria-expanded")'
        )
        if expanded == "false" or expanded is None:
            return True

        return True  # Optimistic — click was sent
    except Exception:
        return True  # Don't fail on verification errors


# ─── Text Field Handler ───────────────────────────────────────────────────────

def fill_text_field(page, field_id, answer):
    """Fill a standard text input by ID."""
    try:
        el = page.locator(f"input#{field_id}")
        if el.count() == 0:
            return False
        el.click()
        el.fill("")
        el.type(str(answer), delay=30)
        # Trigger blur to validate
        el.press("Tab")
        time.sleep(0.2)
        return True
    except Exception as e:
        print(f"      ❌ Text fill error ({field_id}): {e}")
        return False


# ─── File Upload Handler ──────────────────────────────────────────────────────

def upload_file(page, input_id, file_path):
    """
    Upload a file to a Greenhouse file input.

    Strategy:
    1. Try clicking the "Attach" button and intercepting the file chooser
       (this is how real users upload, so Greenhouse's JS validates it properly)
    2. Fall back to unhiding the <input type=file> and using set_input_files
    """
    try:
        if not file_path or not Path(file_path).exists():
            print(f"      ⚠️  File not found: {file_path}")
            return False

        abs_path = str(Path(file_path).absolute())

        # Strategy 1: Click the "Attach" button near this file input
        # and intercept the file chooser dialog
        try:
            # Find the file upload group containing this input
            attach_btn = page.locator(
                f"input#{input_id} >> xpath=ancestor::div[contains(@class,'file-upload')]"
                f"//button[contains(text(),'Attach')]"
            )

            if attach_btn.count() == 0:
                # Try alternate: look for any Attach button near the input
                attach_btn = page.locator(
                    f"input#{input_id} >> xpath=ancestor::div[contains(@class,'upload')]"
                    f"//a[contains(text(),'Attach')] | "
                    f"input#{input_id} >> xpath=ancestor::div[contains(@class,'upload')]"
                    f"//button[contains(text(),'Attach')]"
                )

            if attach_btn.count() == 0:
                # Broader search: look for Attach link/button in the same field group
                attach_btn = page.locator(
                    f"input#{input_id} >> xpath=ancestor::div[contains(@class,'field')]"
                    f"//*[contains(text(),'Attach')]"
                )

            if attach_btn.count() > 0:
                # Use file_chooser to intercept the dialog
                with page.expect_file_chooser(timeout=5000) as fc_info:
                    attach_btn.first.click()
                file_chooser = fc_info.value
                file_chooser.set_files(abs_path)
                time.sleep(2)

                # Verify upload by checking if filename appears
                upload_group = page.locator(
                    f"input#{input_id} >> xpath=ancestor::div[contains(@class,'file-upload')]"
                )
                if upload_group.count() > 0:
                    group_text = upload_group.first.inner_text()
                    filename = Path(file_path).name
                    if filename.lower() in group_text.lower() or "remove" in group_text.lower():
                        print(f"      ✅ Uploaded via Attach: {filename}")
                        return True

                # Even without verification, the file_chooser approach usually works
                print(f"      ✅ Uploaded via Attach: {Path(file_path).name}")
                return True

        except Exception as e:
            print(f"      ℹ️  Attach button method failed: {e}, trying direct input...")

        # Strategy 2: Direct set_input_files on the hidden file input
        # Make it visible first since Greenhouse hides file inputs
        page.evaluate(f"""() => {{
            const el = document.getElementById("{input_id}");
            if (el) {{
                el.style.display = 'block';
                el.style.opacity = '1';
                el.style.position = 'relative';
                el.style.width = '200px';
                el.style.height = '30px';
            }}
        }}""")
        time.sleep(0.3)

        el = page.locator(f"input#{input_id}")
        if el.count() > 0:
            el.set_input_files(abs_path)
            time.sleep(2)

            # Trigger change event in case Greenhouse needs it
            page.evaluate(f"""() => {{
                const el = document.getElementById("{input_id}");
                if (el) {{
                    el.dispatchEvent(new Event('change', {{ bubbles: true }}));
                    el.dispatchEvent(new Event('input', {{ bubbles: true }}));
                }}
            }}""")
            time.sleep(1)

            print(f"      ✅ Uploaded via direct input: {Path(file_path).name}")
            return True

        print(f"      ❌ Could not find file input #{input_id}")
        return False

    except Exception as e:
        print(f"      ❌ Upload error ({input_id}): {e}")
        return False


# ─── Greenhouse DOM Parser ────────────────────────────────────────────────────

def parse_greenhouse_fields(page):
    """
    Parse ALL form fields from a Greenhouse application page by reading the DOM.
    No LLM needed — the structure is deterministic.

    Returns a list of dicts:
        { "id": str, "label": str, "type": "react-select"|"text"|"file"|"tel",
          "required": bool }
    """
    fields = page.evaluate("""() => {
        const results = [];

        // 1. React-Select dropdowns: every combobox inside a select-shell
        document.querySelectorAll('input[role="combobox"]').forEach(input => {
            // Skip the phone country search combobox (it's inside intl-tel-input)
            if (input.closest('.iti__dropdown-content')) return;

            const id = input.id;
            if (!id) return;

            const labelEl = document.querySelector(`label[for="${id}"]`);
            const label = labelEl ? labelEl.textContent.replace(/\\*/g, '').trim() : id;
            const required = input.getAttribute('aria-required') === 'true';

            results.push({
                id: id,
                label: label,
                type: 'react-select',
                required: required
            });
        });

        // 2. Standard text/email/tel inputs
        document.querySelectorAll('input.input.input__single-line').forEach(input => {
            const id = input.id;
            if (!id) return;

            const labelEl = document.querySelector(`label[for="${id}"]`);
            const label = labelEl ? labelEl.textContent.replace(/\\*/g, '').trim() : id;
            const required = input.getAttribute('aria-required') === 'true';
            const inputType = input.type || 'text';

            results.push({
                id: id,
                label: label,
                type: inputType === 'tel' ? 'tel' : 'text',
                required: required
            });
        });

        // 3. File upload inputs
        document.querySelectorAll('input[type="file"]').forEach(input => {
            const id = input.id;
            if (!id) return;

            // Find label from the upload-label div
            const group = input.closest('.file-upload');
            const labelEl = group ? group.querySelector('.upload-label') : null;
            const label = labelEl ? labelEl.textContent.replace(/\\*/g, '').trim() : id;
            const required = group ? group.getAttribute('aria-required') === 'true' : false;

            results.push({
                id: id,
                label: label,
                type: 'file',
                required: required
            });
        });

        return results;
    }""")

    return fields


def build_answer_map(profile, company):
    """
    Build a mapping of field labels/IDs → answers from the user profile.
    This covers all standard Greenhouse fields.
    """
    name_parts = profile["personal"]["name"].split(" ", 1)
    first_name = name_parts[0]
    last_name = name_parts[1] if len(name_parts) > 1 else ""

    answers = {
        # Standard fields (by ID)
        "first_name": first_name,
        "last_name": last_name,
        "email": profile["personal"]["email"],
        "phone": profile["personal"]["phone"],

        # React-Select dropdowns (by ID)
        "country": "United States",
        "candidate-location": profile["personal"]["location"],

        # EEOC fields (by ID)
        "gender": "Male",
        "hispanic_ethnicity": "No",
        "veteran_status": "I am not a protected veteran",
        "disability_status": "No, I don't have a disability",

        # File uploads (by ID)
        "resume": "RESUME_FILE",
        "cover_letter": "COVER_LETTER_FILE",
    }

    # Dynamic question fields — match by label keywords
    location = profile["personal"].get("location", "")
    location_parts = [p.strip() for p in location.split(",")]
    state_abbrev = location_parts[1] if len(location_parts) > 1 else ""

    # Expand state abbreviation to full name using shared STATE_MAP
    state_full = STATE_MAP.get(state_abbrev.lower(), state_abbrev)
    # Capitalize for display: "south carolina" → "South Carolina"
    state_full = state_full.title() if state_full.islower() else state_full

    label_answers = {
        "legally authorized to work": "Yes",
        "work authorization": "Yes",
        "authorized to work in the united states": "Yes",
        "require sponsorship": "No",
        "visa status": "No",
        "visa sponsorship": "No",
        "how did you hear": "LinkedIn",
        "linkedin profile": profile["personal"].get("linkedin_url", ""),
        "linkedin url": profile["personal"].get("linkedin_url", ""),
        "do you know anyone": "No",
        "know anyone who currently works": "No",
        "full legal name": profile["personal"]["name"],
        "full name": profile["personal"]["name"],
        "preferred first name": first_name,
        "website": profile["personal"].get("portfolio_url", ""),
        "github": profile["personal"].get("github_url", ""),
        "years of experience": str(profile.get("years_of_experience", "")),
        "salary": str(profile.get("salary_range", {}).get("min", "")),
        "desired salary": str(profile.get("salary_range", {}).get("min", "")),
        # State / location fields
        "which state": state_full,
        "what state": state_full,
        "state do you": state_full,
        "state of residence": state_full,
        "where are you located": location,
        # Schedule / commitment questions
        "commit to this schedule": "Yes",
        "can you commute": "Yes",
        "willing to relocate": "Yes",
        "able to work": "Yes",
        "available to start": "Immediately",
        "start date": "Immediately",
    }

    # Merge in any saved extra answers from the profile
    for key, val in profile.get("extra_answers", {}).items():
        label_answers[key.lower()] = val

    return answers, label_answers


def resolve_answer(field, answers_by_id, answers_by_label):
    """
    Look up the answer for a given field, trying ID match first,
    then label keyword matching.
    """
    field_id = field["id"]
    label = field["label"].lower()

    # Direct ID match
    if field_id in answers_by_id:
        return answers_by_id[field_id]

    # Label keyword matching (for dynamic question IDs like question_63021724)
    for keyword, answer in answers_by_label.items():
        if keyword in label:
            return answer

    return None


# ─── Interactive Answer Prompt ────────────────────────────────────────────────

def prompt_for_answer(field):
    """
    Ask the user for an answer when the bot doesn't know what to fill.
    Returns the user's answer, or None if they want to skip.
    """
    label = field["label"]
    field_type = field["type"]
    required = field["required"]

    req_tag = " (REQUIRED)" if required else " (optional)"
    type_hint = ""
    if field_type == "react-select":
        type_hint = " [dropdown — I'll fuzzy match your answer to available options]"
    elif field_type == "text":
        type_hint = " [text field]"

    print(f"\n  ❓ Unknown field: {label}{req_tag}{type_hint}")
    answer = input(f"     Your answer (or SKIP to leave blank): ").strip()

    if answer.upper() == "SKIP" or answer == "":
        return None
    return answer


def save_answer_to_profile(profile, profile_path, field_label, answer):
    """
    Save a new answer to the profile's extra_answers so it's remembered
    for future applications.
    """
    if "extra_answers" not in profile:
        profile["extra_answers"] = {}

    # Use a normalized version of the label as the key
    # Extract the meaningful part — strip leading "Which/What/Are/Do/Will" etc.
    key = field_label.strip()

    # Don't save overly long keys — truncate at 80 chars
    if len(key) > 80:
        key = key[:80]

    profile["extra_answers"][key] = answer

    # Write back to disk
    try:
        Path(profile_path).write_text(json.dumps(profile, indent=2))
        print(f"     💾 Saved to profile for future use")
    except Exception as e:
        print(f"     ⚠️  Could not save to profile: {e}")


# ─── Universal Form Filler (any ATS / any website) ───────────────────────────

# JavaScript to extract ALL form fields from any page
EXTRACT_FIELDS_JS = """
() => {
    const fields = [];
    const seen = new Set();
    
    function getLabel(el) {
        // Try: explicit label via for/id
        if (el.id) {
            const label = document.querySelector('label[for="' + el.id + '"]');
            if (label) return label.innerText.trim();
        }
        // Try: parent label
        const parentLabel = el.closest('label');
        if (parentLabel) return parentLabel.innerText.trim();
        // Try: aria-label
        if (el.getAttribute('aria-label')) return el.getAttribute('aria-label').trim();
        // Try: aria-labelledby
        const labelledBy = el.getAttribute('aria-labelledby');
        if (labelledBy) {
            const ref = document.getElementById(labelledBy);
            if (ref) return ref.innerText.trim();
        }
        // Try: placeholder
        if (el.placeholder) return el.placeholder.trim();
        // Try: preceding sibling text or parent div text
        const prev = el.previousElementSibling;
        if (prev && prev.tagName !== 'INPUT' && prev.innerText) return prev.innerText.trim().slice(0, 100);
        // Try: name attribute cleaned up
        if (el.name) return el.name.replace(/[_\\-\\[\\]]/g, ' ').trim();
        return '';
    }
    
    function getOptions(el) {
        if (el.tagName === 'SELECT') {
            return Array.from(el.options).map(o => o.text.trim()).filter(t => t && t !== '');
        }
        return [];
    }
    
    function isVisible(el) {
        const rect = el.getBoundingClientRect();
        const style = window.getComputedStyle(el);
        return rect.width > 0 && rect.height > 0 && 
               style.display !== 'none' && style.visibility !== 'hidden' &&
               style.opacity !== '0';
    }
    
    // Scan all standard form elements
    const selectors = 'input, select, textarea';
    document.querySelectorAll(selectors).forEach(el => {
        const type = el.type || el.tagName.toLowerCase();
        // Skip hidden, submit, button, image types
        if (['hidden', 'submit', 'button', 'image', 'reset'].includes(type)) return;
        // Skip invisible elements (but keep file inputs which may be hidden)
        if (type !== 'file' && !isVisible(el)) return;
        
        const key = el.id || el.name || Math.random().toString(36).slice(2);
        if (seen.has(key)) return;
        seen.add(key);
        
        fields.push({
            tag: el.tagName.toLowerCase(),
            type: type,
            id: el.id || '',
            name: el.name || '',
            label: getLabel(el),
            placeholder: el.placeholder || '',
            required: el.required || el.getAttribute('aria-required') === 'true',
            options: getOptions(el),
            value: el.value || '',
            selector: el.id ? '#' + CSS.escape(el.id) : 
                      el.name ? '[name="' + el.name + '"]' : 
                      null
        });
    });
    
    return fields;
}
"""


def extract_page_fields(page):
    """
    Extract all form fields from any page using JavaScript injection.
    Returns a list of field dicts with: tag, type, id, name, label, 
    placeholder, required, options, selector.
    """
    try:
        fields = page.evaluate(EXTRACT_FIELDS_JS)
        # Filter out fields with no useful identifier
        return [f for f in fields if f.get("label") or f.get("id") or f.get("name")]
    except Exception as e:
        print(f"  ⚠️  Could not extract fields: {e}")
        return []


def claude_map_fields(fields, profile, job):
    """
    Ask Claude to map form fields to profile answers.
    Only called for fields that weren't auto-matched by build_answer_map.
    """
    # Build a compact description of each unmapped field
    field_descriptions = []
    for i, f in enumerate(fields):
        desc = "{}. [{}] label='{}' placeholder='{}' required={}".format(
            i, f.get("type", "text"), f.get("label", ""), 
            f.get("placeholder", ""), f.get("required", False))
        if f.get("options"):
            desc += " options={}".format(f["options"][:10])
        field_descriptions.append(desc)

    prompt = """You are filling out a job application form. Map the candidate's profile data to these form fields.

## CANDIDATE PROFILE:
Name: {name}
Email: {email}
Phone: {phone}
Location: {location}
LinkedIn: {linkedin}
Portfolio: {portfolio}
GitHub: {github}
Experience: {years} years ({level})
Target roles: {roles}
Certifications: {certs}
Authorized to work in US: Yes
Requires sponsorship: No
US citizen: Yes

## JOB:
Title: {title}
Company: {company}

## FORM FIELDS:
{fields}

## INSTRUCTIONS:
Return ONLY a JSON object mapping field index numbers to answers. Example:
{{"0": "Alex", "1": "Carter", "3": "Yes"}}

Rules:
- Only include fields you can confidently answer
- For file upload fields, use "RESUME_FILE" or "COVER_LETTER_FILE"  
- For optional EEOC/demographic fields, use "Decline to self-identify" or leave out
- For yes/no fields about work authorization, answer "Yes" for authorized, "No" for sponsorship
- For select dropdowns, pick the EXACT text from the options list
- Skip fields you're unsure about (the user will be asked)
- Do NOT fabricate information

Return ONLY the JSON object.""".format(
        name=profile["personal"].get("name", ""),
        email=profile["personal"].get("email", ""),
        phone=profile["personal"].get("phone", ""),
        location=profile["personal"].get("location", ""),
        linkedin=profile["personal"].get("linkedin_url", ""),
        portfolio=profile["personal"].get("portfolio_url", ""),
        github=profile["personal"].get("github_url", ""),
        years=profile.get("years_of_experience", 0),
        level=profile.get("experience_level", ""),
        roles=", ".join(profile.get("target_roles", [])[:5]),
        certs=", ".join(profile.get("certifications", [])[:5]),
        title=job.get("title", ""),
        company=job.get("company", ""),
        fields="\n".join(field_descriptions),
    )

    raw = ask_claude(prompt)
    if not raw:
        return {}

    # Parse JSON response
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
    return {}


def fill_generic_field(page, field, answer, resume_path=None, cover_letter_path=None):
    """
    Fill a single form field using generic Playwright actions.
    Works on any website — text inputs, selects, textareas, file uploads.
    """
    if not answer:
        return False

    selector = field.get("selector")
    field_type = field.get("type", "text")
    
    # Handle file uploads
    if answer == "RESUME_FILE" and resume_path:
        return handle_file_upload(page, field, resume_path)
    elif answer == "COVER_LETTER_FILE" and cover_letter_path:
        return handle_file_upload(page, field, cover_letter_path)
    elif answer in ("RESUME_FILE", "COVER_LETTER_FILE"):
        return False

    if not selector:
        return False

    try:
        el = page.locator(selector)
        if el.count() == 0:
            return False

        if field_type == "select-one" or field.get("tag") == "select":
            # Standard HTML select
            try:
                el.select_option(label=answer)
                return True
            except Exception:
                try:
                    el.select_option(value=answer)
                    return True
                except Exception:
                    pass
            return False

        elif field_type == "checkbox":
            if answer.lower() in ("yes", "true", "1", "checked"):
                el.check()
            else:
                el.uncheck()
            return True

        elif field_type == "radio":
            el.click()
            return True

        elif field_type == "file":
            return handle_file_upload(page, field, answer)

        else:
            # text, email, tel, number, textarea, url
            el.click()
            el.fill(str(answer))
            return True

    except Exception as e:
        print(f"      ⚠️  Could not fill {field.get('label','')}: {e}")
        return False


def handle_file_upload(page, field, file_path):
    """Handle file upload for any form — tries multiple approaches."""
    file_path = str(Path(file_path).absolute())
    if not Path(file_path).exists():
        print(f"      ⚠️  File not found: {file_path}")
        return False

    try:
        selector = field.get("selector")
        if selector:
            # Try direct set_input_files
            el = page.locator(selector)
            if el.count() > 0:
                # Unhide the file input if needed
                page.evaluate("""(sel) => {
                    const el = document.querySelector(sel);
                    if (el) {
                        el.style.display = 'block';
                        el.style.visibility = 'visible';
                        el.style.opacity = '1';
                        el.style.height = 'auto';
                        el.style.width = 'auto';
                        el.style.position = 'relative';
                    }
                }""", selector)
                time.sleep(0.3)
                el.set_input_files(file_path)
                return True

        # Fallback: find any file input on the page
        file_inputs = page.locator("input[type='file']")
        for i in range(file_inputs.count()):
            inp = file_inputs.nth(i)
            label = field.get("label", "").lower()
            # Match by nearby label text
            inp_name = (inp.get_attribute("name") or "").lower()
            inp_id = (inp.get_attribute("id") or "").lower()
            if ("resume" in label or "resume" in inp_name or "resume" in inp_id or 
                "cv" in label or "cv" in inp_name):
                page.evaluate("""(i) => {
                    const els = document.querySelectorAll('input[type="file"]');
                    if (els[i]) {
                        els[i].style.display = 'block';
                        els[i].style.visibility = 'visible';
                        els[i].style.opacity = '1';
                    }
                }""", i)
                time.sleep(0.3)
                inp.set_input_files(file_path)
                return True

    except Exception as e:
        print(f"      ⚠️  File upload error: {e}")
    return False


def run_universal_application(page, job, profile, profile_path, resume_path, cover_letter_path, slug, dry_run, browser_ctx=None, platform="unknown"):
    """
    Fill a job application form on ANY website using AI-assisted field mapping.
    
    Strategy:
    1. Extract all form fields from the page using JavaScript
    2. Auto-map common fields using profile data (no AI needed)
    3. Ask Claude to map remaining fields
    4. Show fill plan and get user confirmation
    5. Fill fields using generic Playwright actions
    """
    print(f"\n  🤖 Universal form filler — analyzing page...")

    # Step 1: Extract all form fields (check main page + iframes)
    fields = extract_page_fields(page)

    # Also check iframes (iCIMS, Workday, etc. load forms in iframes)
    if not fields:
        for frame in page.frames[1:]:
            try:
                frame_fields = frame.evaluate(EXTRACT_FIELDS_JS)
                frame_fields = [f for f in frame_fields if f.get("label") or f.get("id") or f.get("name")]
                if len(frame_fields) > len(fields):
                    fields = frame_fields
                    print(f"  📎 Found {len(fields)} fields inside iframe")
            except Exception:
                continue

    # Filter out navigation-only fields (search boxes, language selectors, etc.)
    # An application form should have at least 3 "meaningful" fields
    NAV_KEYWORDS = ["search", "filter", "sort", "region", "language", "locale", "country-selector"]
    meaningful = [f for f in fields if not any(
        kw in (f.get("label", "") + f.get("id", "") + f.get("name", "")).lower()
        for kw in NAV_KEYWORDS
    )]
    if len(meaningful) < 3 and len(fields) <= 5:
        # Probably just navigation fields, not an application form
        fields = []

    if not fields:
        # No fields found — try clicking Apply button automatically first
        print(f"\n  🔍 No form fields yet — trying to find and click Apply button...")
        page_text = ""
        try:
            page_text = page.inner_text("body")[:5000].lower()
        except Exception:
            pass

        clicked = click_apply_button(page)
        if clicked:
            time.sleep(4)
            dismiss_cookie_banner(page)  # New page might have its own cookie banner
            screenshot(page, f"{slug}_02_after_apply_click")

            # Re-extract fields after clicking
            fields = extract_page_fields(page)

            # Check iframes too
            if not fields:
                for frame in page.frames[1:]:
                    try:
                        frame_fields = frame.evaluate(EXTRACT_FIELDS_JS)
                        frame_fields = [f for f in frame_fields if f.get("label") or f.get("id") or f.get("name")]
                        if len(frame_fields) > len(fields):
                            fields = frame_fields
                            print(f"  📎 Found {len(fields)} fields inside iframe")
                    except Exception:
                        continue

            if fields:
                print(f"  ✅ Found {len(fields)} fields after clicking Apply")

    if not fields:
        # Still no fields — last resort: ask user to navigate manually
        print(f"\n  ⚠️  No form fields found yet.")
        print(f"     Current page: {page.url[:70]}")
        print(f"\n  ┌─────────────────────────────────────────────────┐")
        print(f"  │  The application form might require you to:      │")
        print(f"  │    • Log in or create an account                 │")
        print(f"  │    • Solve a CAPTCHA                             │")
        print(f"  │    • Navigate to the form manually               │")
        print(f"  │                                                   │")
        print(f"  │  👉 Use the browser to get to the actual         │")
        print(f"  │     application FORM (name, email, resume, etc.) │")
        print(f"  │                                                   │")
        print(f"  │  Press Enter when you're on the form page.       │")
        print(f"  │  Type SKIP to skip this job.                     │")
        print(f"  └─────────────────────────────────────────────────┘")

        user_input = input("\n  ⏳ Press Enter when on the form (or SKIP): ").strip()
        if user_input.upper() == "SKIP":
            return "user_skipped"

        # Save session cookies so we don't have to log in again for this ATS
        if browser_ctx and platform != "unknown":
            save_browser_session(browser_ctx, platform)

        # Re-check for fields after user navigated
        time.sleep(2)
        fields = extract_page_fields(page)

        # Check iframes again
        if not fields:
            for frame in page.frames[1:]:
                try:
                    frame_fields = frame.evaluate(EXTRACT_FIELDS_JS)
                    frame_fields = [f for f in frame_fields if f.get("label") or f.get("id") or f.get("name")]
                    if len(frame_fields) > len(fields):
                        fields = frame_fields
                        print(f"  📎 Found {len(fields)} fields inside iframe")
                except Exception:
                    continue

        if not fields:
            print(f"  ❌ Still no form fields found. Skipping this job.")
            screenshot(page, f"{slug}_no_fields")
            return "no_form_found"

    print(f"  ✅ Found {len(fields)} form fields")

    # Step 2: Auto-map using existing profile answer map
    answers_by_id, answers_by_label = build_answer_map(profile, slug)
    auto_mapped = {}
    unmapped_fields = []

    for i, f in enumerate(fields):
        fid = f.get("id", "").lower()
        fname = f.get("name", "").lower()
        flabel = f.get("label", "").lower()

        answer = None

        # Try ID match
        for key, val in answers_by_id.items():
            if key == fid or key == fname:
                answer = val
                break

        # Try label keyword match
        if not answer:
            for key, val in answers_by_label.items():
                if key in flabel:
                    answer = val
                    break

        # Try file field detection
        if not answer and f.get("type") == "file":
            if any(kw in flabel for kw in ["resume", "cv"]):
                answer = "RESUME_FILE"
            elif "cover" in flabel or "letter" in flabel:
                answer = "COVER_LETTER_FILE"

        if answer:
            auto_mapped[str(i)] = answer
        else:
            unmapped_fields.append((i, f))

    print(f"  📊 Auto-mapped: {len(auto_mapped)} | Unmapped: {len(unmapped_fields)}")

    # Step 3: Ask Claude to map remaining fields
    claude_mapped = {}
    if unmapped_fields and OPENROUTER_API_KEY:
        print(f"  🤖 Asking Claude to map {len(unmapped_fields)} remaining fields...")
        unmapped_for_claude = [f for _, f in unmapped_fields]
        raw_mapping = claude_map_fields(unmapped_for_claude, profile, job)

        # Convert Claude's response (which uses unmapped index) to global index
        for local_idx_str, answer in raw_mapping.items():
            try:
                local_idx = int(local_idx_str)
                if 0 <= local_idx < len(unmapped_fields):
                    global_idx = unmapped_fields[local_idx][0]
                    claude_mapped[str(global_idx)] = answer
            except (ValueError, IndexError):
                continue

        print(f"  ✅ Claude mapped {len(claude_mapped)} additional fields")

    # Merge all mappings
    all_answers = {}
    all_answers.update(auto_mapped)
    all_answers.update(claude_mapped)

    # Step 4: Show fill plan
    print(f"\n  📋 Fill plan ({len(all_answers)}/{len(fields)} fields):")
    for i, f in enumerate(fields):
        answer = all_answers.get(str(i))
        ftype = f.get("type", "?")[:12]
        flabel = f.get("label", f.get("name", "unknown"))[:45]
        req = "*" if f.get("required") else " "

        if answer == "RESUME_FILE":
            display = "📄 {}".format(Path(resume_path).name) if resume_path else "NO FILE"
        elif answer == "COVER_LETTER_FILE":
            display = "📄 {}".format(Path(cover_letter_path).name) if cover_letter_path else "NO FILE"
        elif answer:
            display = str(answer)[:50]
        else:
            display = "❓ will ask" if f.get("required") else "(skip)"

        print(f"     {ftype:12s} | {flabel:45s}{req} → {display}")

    print(f"  {'─'*80}")
    screenshot(page, f"{slug}_universal_plan")

    if dry_run:
        print(f"\n  [DRY RUN] Would fill {len(all_answers)} of {len(fields)} fields")
        return "dry_run_ok"

    # Step 5: Fill fields
    print(f"\n  ✏️  Filling fields...")
    filled = 0
    failed = []

    for i, f in enumerate(fields):
        answer = all_answers.get(str(i))
        if not answer:
            # Ask user for required fields without an answer
            if f.get("required"):
                label = f.get("label", f.get("name", "unknown field"))
                user_answer = input(f"\n  ❓ {label}: ").strip()
                if user_answer:
                    answer = user_answer
                    save_answer_to_profile(profile, profile_path, label, user_answer)
                else:
                    continue
            else:
                continue

        success = fill_generic_field(page, f, answer, resume_path, cover_letter_path)
        if success:
            filled += 1
            label = f.get("label", f.get("name", ""))[:40]
            print(f"     ✅ {label}")
        else:
            failed.append(f)
            label = f.get("label", f.get("name", ""))[:40]
            print(f"     ❌ {label}")

        time.sleep(0.3)  # Brief pause between fields

    screenshot(page, f"{slug}_filled")
    print(f"\n  📊 Filled {filled}/{len(fields)} fields")

    if failed:
        print(f"  ⚠️  {len(failed)} fields could not be filled")

    return filled, len(fields), failed



def dismiss_cookie_banner(page):
    """
    Automatically dismiss cookie consent banners that block page interaction.
    Tries clicking common accept/close buttons found across websites.
    """
    COOKIE_BUTTON_PATTERNS = [
        "Accept all", "Accept All", "Accept all cookies", "Accept Cookies",
        "Accept cookies", "I Accept", "I agree", "Allow all", "Allow All",
        "Allow cookies", "OK", "Got it", "Got it!", "Agree",
        "Agree and close", "Dismiss", "Consent",
    ]

    for pattern in COOKIE_BUTTON_PATTERNS:
        try:
            btn = page.get_by_role("button", name=pattern, exact=False)
            if btn.count() > 0 and btn.first.is_visible():
                btn.first.click()
                time.sleep(1)
                print(f"  🍪 Dismissed cookie banner ('{pattern}')")
                return True
        except Exception:
            pass

    COOKIE_SELECTORS = [
        "button[id*='accept']", "button[id*='cookie']",
        "button[class*='accept']", "button[class*='consent']",
        "a[id*='accept']", "a[class*='accept']",
        "[data-testid*='cookie'] button", "[data-testid*='accept']",
        ".cookie-banner button", ".cookie-consent button",
        ".cc-accept", ".cc-btn",
        "#onetrust-accept-btn-handler",
        "#CybotCookiebotDialogBodyLevelButtonLevelOptinAllowAll",
        ".evidon-banner-acceptbutton",
    ]

    for selector in COOKIE_SELECTORS:
        try:
            el = page.locator(selector)
            if el.count() > 0 and el.first.is_visible():
                el.first.click()
                time.sleep(1)
                print(f"  🍪 Dismissed cookie banner")
                return True
        except Exception:
            continue

    # Last resort: close overlays that mention cookies/privacy
    try:
        close_btns = page.locator("[aria-label='Close'], [aria-label='close'], .close-button, .modal-close")
        for i in range(min(close_btns.count(), 3)):
            btn = close_btns.nth(i)
            if btn.is_visible():
                parent_text = ""
                try:
                    parent_text = btn.locator("..").inner_text()[:200].lower()
                except Exception:
                    pass
                if any(kw in parent_text for kw in ["cookie", "consent", "privacy", "gdpr", "tracking"]):
                    btn.click()
                    time.sleep(1)
                    print(f"  🍪 Dismissed cookie overlay")
                    return True
    except Exception:
        pass

    return False


def click_apply_button(page):
    """Click the Apply button if we're on a job description page.
    Handles buttons, links, and page navigation (iCIMS, Lever, etc.)."""
    
    apply_patterns = [
        "Apply for this job online",
        "Apply for this job",
        "Apply for this position",
        "Apply Now",
        "Apply now",
        "Apply",
        "Start Application",
        "Start application",
        "Begin Application",
        "Submit Application",
    ]

    old_url = page.url

    # Try button elements
    for pattern in apply_patterns:
        try:
            btn = page.get_by_role("button", name=pattern)
            if btn.count() > 0 and btn.first.is_visible():
                btn.first.click()
                time.sleep(4)
                # Check if we navigated to a new page
                if page.url != old_url:
                    print(f"  📄 Navigated to: {page.url[:70]}")
                    time.sleep(2)
                return True
        except Exception:
            continue

    # Try link elements
    for pattern in apply_patterns:
        try:
            link = page.get_by_role("link", name=pattern)
            if link.count() > 0 and link.first.is_visible():
                link.first.click()
                time.sleep(4)
                if page.url != old_url:
                    print(f"  📄 Navigated to: {page.url[:70]}")
                    time.sleep(2)
                return True
        except Exception:
            continue

    # Try any element containing apply text (some sites use <div> or <span>)
    try:
        apply_el = page.locator("text=/[Aa]pply/i").first
        if apply_el.is_visible():
            apply_el.click()
            time.sleep(4)
            if page.url != old_url:
                print(f"  📄 Navigated to: {page.url[:70]}")
                time.sleep(2)
            return True
    except Exception:
        pass

    return False


def run_greenhouse_application(page, profile, profile_path, resume_path, cover_letter_path, slug, dry_run):
    """
    Fill a Greenhouse application form using deterministic DOM parsing.
    No LLM calls needed.
    """
    print("\n  🌿 Greenhouse form detected — using deterministic DOM parser")

    # Parse fields from the DOM
    fields = parse_greenhouse_fields(page)
    print(f"  ✅ Found {len(fields)} fields from DOM")

    # Build answer mappings
    answers_by_id, answers_by_label = build_answer_map(
        profile, slug
    )

    # Show fill plan
    print(f"\n  📋 Fill plan:")
    for f in fields:
        answer = resolve_answer(f, answers_by_id, answers_by_label)
        display = answer or ("❓ will ask" if f["required"] else "(no answer)")
        if answer == "RESUME_FILE":
            display = f"📄 {Path(resume_path).name}" if resume_path else "NO FILE"
        elif answer == "COVER_LETTER_FILE":
            display = f"📄 {Path(cover_letter_path).name}" if cover_letter_path else "NO FILE"
        req = "*" if f["required"] else ""
        print(f"     {f['type']:14s} | {f['label'][:45]:45s}{req} → {str(display)[:50]}")
    print(f"  {'─'*80}")

    if dry_run:
        screenshot(page, f"{slug}_dryrun_preview")
        print(f"\n  [DRY RUN] Would fill {len(fields)} fields")
        return "dry_run_ok"

    # Fill each field
    print(f"\n  ✏️  Filling fields...")
    filled_count = 0
    failed_fields = []

    for f in fields:
        field_id = f["id"]
        field_type = f["type"]
        label = f["label"]
        answer = resolve_answer(f, answers_by_id, answers_by_label)

        if not answer:
            if f["required"] or f["type"] == "react-select":
                # Ask the user interactively
                answer = prompt_for_answer(f)
                if answer:
                    # Save to profile for future use
                    save_answer_to_profile(profile, profile_path, label, answer)
                    # Also add to current session's label answers so the
                    # fill plan printout would show it next time
                    answers_by_label[label.lower()] = answer
                else:
                    if f["required"]:
                        print(f"    ⚠️  {label} — SKIPPED (required!)")
                        failed_fields.append(label)
                    continue
            else:
                continue

        # Skip file uploads with no file
        if answer == "RESUME_FILE" and not resume_path:
            continue
        if answer == "COVER_LETTER_FILE" and not cover_letter_path:
            continue

        print(f"    → {label[:50]}...", end=" ")

        success = False

        if field_type == "file":
            file_path = resume_path if answer == "RESUME_FILE" else cover_letter_path
            success = upload_file(page, field_id, file_path)

        elif field_type == "react-select":
            success = fill_react_select(page, field_id, answer)

        elif field_type in ("text", "tel"):
            success = fill_text_field(page, field_id, answer)

        if success:
            print(f"✅")
            filled_count += 1
        else:
            print(f"❌")
            failed_fields.append(label)

        # Small delay between fields to avoid race conditions
        time.sleep(0.3)

    # Take screenshot of filled form
    screenshot(page, f"{slug}_filled")

    # Scroll down and screenshot bottom of form
    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
    time.sleep(1)
    screenshot(page, f"{slug}_filled_bottom")

    # Report
    total = len([f for f in fields if resolve_answer(f, answers_by_id, answers_by_label)])
    print(f"\n  📊 Results: {filled_count}/{total} fields filled")
    if failed_fields:
        print(f"  ❌ Failed: {', '.join(failed_fields)}")

    return filled_count, total, failed_fields


def run_application(connect_url, job, profile, profile_path, resume_path, cover_letter_path, dry_run):
    """Run the full application flow for a single job."""
    title = job.get("title", "")
    company = job.get("company", "")
    url = job.get("apply_url", "")
    slug = re.sub(r'[^a-zA-Z0-9]+', '_', company).strip('_')

    # Detect ATS platform for session reuse
    platform = detect_ats_platform(url)
    session_path = get_session_path(platform)
    has_session = has_saved_session(platform)

    if platform != "unknown" and has_session:
        print(f"  🍪 Found saved session for {platform}")

    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            if connect_url == "local":
                print(f"  🖥️  Launching local browser...")
                browser = p.chromium.launch(headless=False)

                # Load saved session if available
                if has_session:
                    try:
                        ctx = browser.new_context(storage_state=str(session_path))
                        print(f"  🍪 Loaded saved {platform} session")
                    except Exception:
                        ctx = browser.new_context()
                else:
                    ctx = browser.new_context()

                page = ctx.new_page()
            else:
                print(f"  🔌 Connecting to cloud browser...")
                browser = p.chromium.connect_over_cdp(connect_url)
                ctx = browser.contexts[0] if browser.contexts else browser.new_context()
                page = ctx.pages[0] if ctx.pages else ctx.new_page()

            # Load URL
            print(f"  🔗 Loading: {url[:70]}...")
            page.goto(url, wait_until="domcontentloaded", timeout=30000)
            time.sleep(3)

            # Dismiss any cookie banners before interacting
            dismiss_cookie_banner(page)

            screenshot(page, f"{slug}_01_loaded")

            # Check if we need to click Apply first
            # Strategy: if the page has very few form fields, we're probably
            # on a job listing page and need to click through to the form
            has_form_fields = page.locator("input:visible, select:visible, textarea:visible").count() > 3
            
            if not has_form_fields:
                page_text = page.inner_text("body")[:3000].lower()
                if any(kw in page_text for kw in ["apply for this", "apply now", "apply online",
                                                    "start application", "submit application"]):
                    print(f"  🖱️  Clicking Apply...")
                    clicked = click_apply_button(page)
                    if clicked:
                        time.sleep(3)
                        dismiss_cookie_banner(page)
                        screenshot(page, f"{slug}_02_form_opened")
                    else:
                        print(f"  ⚠️  Could not find apply button")

            # Detect form type
            if is_greenhouse_form(page):
                result = run_greenhouse_application(
                    page, profile, profile_path, resume_path, cover_letter_path, slug, dry_run
                )

                if dry_run:
                    browser.close()
                    return "dry_run_ok"

                filled_count, total, failed_fields = result

                # Prompt for submission
                print(f"\n  📸 Review screenshots:")
                print(f"     open outputs/screenshots/{slug}_filled.png")
                print(f"     open outputs/screenshots/{slug}_filled_bottom.png")

                if failed_fields:
                    print(f"\n  ⚠️  {len(failed_fields)} fields failed — review before submitting")

                confirm = input("\n  Type YES to submit, SKIP to skip: ").strip().upper()
                if confirm == "YES":
                    # Click submit
                    for pattern in ["Submit application", "Submit", "Apply"]:
                        try:
                            btn = page.get_by_role("button", name=pattern)
                            if btn.count() > 0:
                                btn.first.click()
                                time.sleep(4)
                                screenshot(page, f"{slug}_submitted")
                                print(f"  🎉 Submitted!")
                                browser.close()
                                return "submitted"
                        except Exception:
                            continue
                    browser.close()
                    return "submit_error"
                else:
                    browser.close()
                    return "user_skipped"

            else:
                # Non-Greenhouse form — use universal AI-powered form filler
                result = run_universal_application(
                    page, job, profile, profile_path, resume_path, cover_letter_path, slug, dry_run,
                    browser_ctx=ctx, platform=platform
                )

                if dry_run:
                    browser.close()
                    return "dry_run_ok" if result == "dry_run_ok" else result

                if result == "no_form_found":
                    browser.close()
                    return "no_form_found"

                filled_count, total, failed_fields = result

                # Prompt for submission
                print(f"\n  📸 Review screenshot:")
                print(f"     open outputs/screenshots/{slug}_filled.png")

                if failed_fields:
                    print(f"\n  ⚠️  {len(failed_fields)} fields could not be filled — review before submitting")

                confirm = input("\n  Type YES to submit, SKIP to skip: ").strip().upper()
                if confirm == "YES":
                    # Try clicking submit
                    for pattern in ["Submit application", "Submit", "Apply", "Apply now",
                                    "Submit Application", "Send Application", "Complete"]:
                        try:
                            btn = page.get_by_role("button", name=pattern)
                            if btn.count() > 0:
                                btn.first.click()
                                time.sleep(4)
                                screenshot(page, f"{slug}_submitted")
                                print(f"  🎉 Submitted!")
                                browser.close()
                                return "submitted"
                        except Exception:
                            continue
                    # Try input[type=submit]
                    try:
                        submit = page.locator("input[type='submit']")
                        if submit.count() > 0:
                            submit.first.click()
                            time.sleep(4)
                            screenshot(page, f"{slug}_submitted")
                            print(f"  🎉 Submitted!")
                            browser.close()
                            return "submitted"
                    except Exception:
                        pass
                    print(f"  ⚠️  Could not find submit button")
                    browser.close()
                    return "submit_error"
                else:
                    browser.close()
                    return "user_skipped"

    except Exception as e:
        print(f"  ❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return "error"


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Job Bot Auto-Apply v4.0")
    parser.add_argument("--jobs", default="profiles/scored_jobs.json")
    parser.add_argument("--profile", default="profiles/job_profile.json")
    parser.add_argument("--min-score", type=int, default=50)
    parser.add_argument("--dry-run", action="store_true",
                        help="Analyze and fill-plan only, don't submit")
    parser.add_argument("--single", type=int, default=None,
                        help="Run only job at this index (0-based)")
    parser.add_argument("--url", type=str, default=None,
                        help="Apply to a single URL directly")
    parser.add_argument("--resume", type=str, default=None,
                        help="Path to resume file (PDF/DOCX)")
    parser.add_argument("--cover-letter", type=str, default=None,
                        help="Path to cover letter file (PDF/DOCX)")
    parser.add_argument("--local", action="store_true", default=True,
                        help="Use local browser (default — no Browserbase needed)")
    parser.add_argument("--cloud", action="store_true",
                        help="Use Browserbase cloud browser instead of local")
    args = parser.parse_args()

    # Set browser mode
    global BROWSER_MODE
    if args.cloud:
        BROWSER_MODE = "cloud"
    else:
        BROWSER_MODE = "local"

    print("\n🚀 Job Bot — Auto-Apply Engine v4.0")
    print("=" * 60)
    print("  🖥️  Browser: {}".format("Cloud (Browserbase)" if BROWSER_MODE == "cloud" else "Local"))
    if args.dry_run:
        print("  ⚠️  DRY RUN MODE — will NOT submit\n")

    profile = json.loads(Path(args.profile).read_text())

    # Single URL mode
    if args.url:
        # Try to resolve company/title from scored_jobs.json
        job_title = "Direct Application"
        job_company = "Unknown"
        scored_jobs_path = Path(args.jobs)
        if scored_jobs_path.exists():
            try:
                scored = json.loads(scored_jobs_path.read_text())
                for sj in scored:
                    sj_url = sj.get("apply_url", "")
                    if sj_url and (sj_url == args.url or sj_url in args.url or args.url in sj_url):
                        job_title = sj.get("title", job_title)
                        job_company = sj.get("company", job_company)
                        print(f"  🔍 Matched job: {job_title} @ {job_company}")
                        break
            except Exception:
                pass

        job = {
            "title": job_title,
            "company": job_company,
            "apply_url": args.url,
            "score": 100
        }
        session_id, connect_url = create_session()
        if not session_id:
            return

        # Find resume: CLI arg → tailored files → profile default
        resume_path = args.resume
        cover_letter_path = getattr(args, 'cover_letter', None)

        if not resume_path:
            resume_path, cover_letter_path = find_tailored_files(
                job_company, job_title, apply_url=args.url
            )
        else:
            print(f"  📄 Resume: {Path(resume_path).name} (CLI)")
            if cover_letter_path:
                print(f"  📄 Cover:  {Path(cover_letter_path).name} (CLI)")

        if not resume_path:
            print(f"  ⚠️  No resume found — use --resume flag or place files in outputs/tailored/")

        try:
            status = run_application(
                connect_url, job, profile, args.profile, resume_path, cover_letter_path, args.dry_run
            )
            print(f"\n  ➡️  Result: {status}")
        finally:
            end_session(session_id)
        return

    # Batch mode
    jobs = json.loads(Path(args.jobs).read_text())
    qualified = [j for j in jobs if j.get("score", 0) >= args.min_score]

    if args.single is not None:
        if 0 <= args.single < len(qualified):
            qualified = [qualified[args.single]]
        else:
            print(f"  ❌ Index {args.single} out of range (0-{len(qualified)-1})")
            return

    results = []
    print(f"  ✅ {len(qualified)} jobs to process\n")

    for i, job in enumerate(qualified, 1):
        title = job.get('title', '')
        company = job.get('company', '')
        score = job.get('score', 0)
        url = job.get('apply_url', '')

        print(f"\n{'='*60}")
        print(f"  🎯 [{i}/{len(qualified)}] {title} @ {company} ({score}%)")
        print(f"{'='*60}")

        if not url:
            results.append({"job": title, "company": company, "status": "no_url"})
            continue

        # Find tailored files
        resume_path, cover_letter_path = find_tailored_files(company, title, apply_url=url)
        if not resume_path:
            results.append({"job": title, "company": company, "status": "no_resume"})
            continue

        # Create browser session
        session_id, connect_url = create_session()
        if not session_id:
            results.append({"job": title, "company": company, "status": "session_error"})
            continue

        try:
            status = run_application(
                connect_url, job, profile, args.profile, resume_path, cover_letter_path, args.dry_run
            )
            results.append({
                "job": title, "company": company, "status": status, "score": score
            })
            print(f"\n  ➡️  Result: {status}")
        finally:
            end_session(session_id)

    # Save results
    Path("outputs/application_log.json").write_text(json.dumps(results, indent=2))

    print(f"\n{'='*60}")
    print(f"✅ Complete!\n")

    icons = {
        "submitted": "🎉", "dry_run_ok": "✅", "user_skipped": "⏭️",
        "error": "❌", "no_resume": "⚠️", "non_greenhouse_skipped": "🔸",
        "no_form_found": "🔍", "submit_error": "⚠️", "session_error": "❌"
    }
    for r in results:
        icon = icons.get(r.get("status", ""), "•")
        print(f"  {icon} {r['company']} → {r['status']}")

    print(f"\n  📸 Screenshots: open outputs/screenshots/")


if __name__ == "__main__":
    main()
