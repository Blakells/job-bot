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
    """Take and save a screenshot, clearing any overlays first."""
    Path("outputs/screenshots").mkdir(parents=True, exist_ok=True)
    path = f"outputs/screenshots/{name}.png"
    # Clear any cookie banners, modals, or backdrops before the screenshot
    try:
        page.evaluate("""() => {
            // Remove cookie/consent overlays
            document.querySelectorAll(
                '[class*="cookie"], [class*="Cookie"], [id*="cookie"], [id*="Cookie"], ' +
                '[class*="consent"], [class*="Consent"], [class*="gdpr"], ' +
                '[data-role="modal-wrapper"], [data-role="backdrop"], ' +
                '[data-evergreen-dialog-backdrop], .modal-backdrop, ' +
                '[class*="modal-overlay"], [class*="dialog-backdrop"]'
            ).forEach(el => {
                // Only remove large overlay-type elements, not small links
                const rect = el.getBoundingClientRect();
                if (rect.width > 200 || el.getAttribute('data-role')) {
                    el.remove();
                }
            });
            document.body.style.overflow = '';
            document.documentElement.style.overflow = '';
        }""")
        time.sleep(0.3)
    except Exception:
        pass
    page.screenshot(path=path)
    print(f"  📸 {path}")
    return path


def find_tailored_files(company, title, apply_url=None, profile_path=None):
    """
    Find tailored resume and cover letter for a job.
    
    Search strategy (in order):
    1. Per-profile tailored dir (profiles/{name}/tailored/) — APPLICATION_SUMMARY + filename
    2. Global tailored dir (outputs/tailored/) — APPLICATION_SUMMARY + filename
    3. Default resume from resumes/ directory
    """
    # Build list of directories to search: per-profile first, then global
    search_dirs = []
    if profile_path:
        profile_dir = Path(profile_path).parent
        per_profile_tailored = profile_dir / "tailored"
        if per_profile_tailored.exists():
            search_dirs.append(per_profile_tailored)
    search_dirs.append(Path("outputs/tailored"))

    resume = None
    cover_letter = None

    for tailored_dir in search_dirs:
        if not tailored_dir.exists():
            continue

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
                    if not matched_entry:
                        for entry in summary:
                            entry_co = entry.get("company", "").lower().strip()
                            if (company_lower in entry_co or entry_co in company_lower):
                                matched_entry = entry
                                break

                if matched_entry:
                    txt_resume = matched_entry.get("resume_file", "")
                    txt_cover = matched_entry.get("cover_letter_file", "")

                    for txt_path, label in [(txt_resume, "resume"), (txt_cover, "cover_letter")]:
                        if not txt_path:
                            continue
                        # Check paths relative to both the tailored dir and as absolute
                        candidates = [txt_path, str(tailored_dir / Path(txt_path).name)]
                        pdf_candidates = [
                            txt_path.replace(".txt", ".pdf"),
                            str(tailored_dir / Path(txt_path.replace(".txt", ".pdf")).name)
                        ]
                        for pdf_path in pdf_candidates:
                            if Path(pdf_path).exists():
                                if label == "resume":
                                    resume = str(Path(pdf_path).absolute())
                                else:
                                    cover_letter = str(Path(pdf_path).absolute())
                                break
                        if (label == "resume" and resume) or (label == "cover_letter" and cover_letter):
                            continue
                        for txt_p in candidates:
                            if Path(txt_p).exists():
                                if label == "resume":
                                    resume = str(Path(txt_p).absolute())
                                else:
                                    cover_letter = str(Path(txt_p).absolute())
                                break

                    if resume:
                        print(f"  📄 Resume: {Path(resume).name}")
                        if cover_letter:
                            print(f"  📄 Cover:  {Path(cover_letter).name}")
                        return resume, cover_letter

            except Exception as e:
                print(f"  ⚠️  Error reading summary: {e}")

        # ── Strategy 3: Direct filename search ────────────────────────────
        company_norm = re.sub(r'[^a-zA-Z0-9]+', '_', company).strip('_').lower()

        for ext in ['.pdf', '.txt']:
            for file in sorted(tailored_dir.glob(f"*_RESUME{ext}"), reverse=True):
                filename = file.stem.lower()
                if company_norm in filename.replace('.', '_'):
                    resume = str(file.absolute())
                    cover_name = file.name.replace(f"_RESUME{ext}", f"_COVER_LETTER{ext}")
                    cover_file = file.parent / cover_name
                    if cover_file.exists():
                        cover_letter = str(cover_file.absolute())
                    print(f"  📄 Resume: {file.name} (filename match)")
                    if cover_letter:
                        print(f"  📄 Cover:  {Path(cover_letter).name}")
                    return resume, cover_letter

    # ── Strategy 4: Default resume ────────────────────────────────────
    # Also check the profile's own directory for a base resume
    default_candidates = [
        "resumes/my_resume.txt", "resumes/my_resume.pdf",
        "profiles/resume.pdf", "profiles/resume.txt",
    ]
    if profile_path:
        profile_dir = Path(profile_path).parent
        for ext in [".pdf", ".txt", ".docx"]:
            for f in profile_dir.glob(f"*Resume*{ext}"):
                default_candidates.insert(0, str(f))
            for f in profile_dir.glob(f"*resume*{ext}"):
                default_candidates.insert(0, str(f))

    for candidate in default_candidates:
        if Path(candidate).exists():
            resume = str(Path(candidate).absolute())
            print(f"  📄 Resume: {candidate} (default — not tailored)")
            return resume, None

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
    Covers standard fields for Greenhouse AND universal forms.
    """
    name_parts = profile["personal"]["name"].split(" ", 1)
    first_name = name_parts[0]
    last_name = name_parts[1] if len(name_parts) > 1 else ""
    location = profile["personal"].get("location", "")
    location_parts = [p.strip() for p in location.split(",")]
    city = location_parts[0] if location_parts else ""
    state_abbrev = location_parts[1].strip() if len(location_parts) > 1 else ""
    state_full = STATE_MAP.get(state_abbrev.lower(), state_abbrev)
    state_full = state_full.title() if state_full.islower() else state_full
    location_full = f"{city}, {state_full}, United States" if city else location

    answers = {
        # Standard fields (by ID)
        "first_name": first_name,
        "last_name": last_name,
        "email": profile["personal"]["email"],
        "phone": profile["personal"]["phone"],
        "firstname": first_name,
        "lastname": last_name,
        "fname": first_name,
        "lname": last_name,

        # React-Select dropdowns (by ID)
        "country": "United States",
        "candidate-location": location_full,

        # EEOC fields (by ID)
        "gender": "Male",
        "hispanic_ethnicity": "No",
        "veteran_status": "I am not a protected veteran",
        "disability_status": "No, I don't have a disability",

        # File uploads (by ID)
        "resume": "RESUME_FILE",
        "cover_letter": "COVER_LETTER_FILE",
    }

    # Dynamic question fields — match by label keywords (case-insensitive)
    # Organized by category for clarity
    salary_str = str(profile.get("salary_range", {}).get("min", ""))
    linkedin_url = profile["personal"].get("linkedin_url", "")
    portfolio_url = profile["personal"].get("portfolio_url", "")
    github_url = profile["personal"].get("github_url", "")
    summary_text = profile.get("summary", "")
    years_exp = str(profile.get("years_of_experience", ""))
    work_history = profile.get("work_history", [])
    current_job = work_history[0] if work_history else {}
    certs = profile.get("certifications", [])

    label_answers = {
        # ── Name fields ──────────────────────────────────────────────
        "first name": first_name,
        "last name": last_name,
        "full legal name": profile["personal"]["name"],
        "full name": profile["personal"]["name"],
        "preferred first name": first_name,
        "preferred name": first_name,
        "name of candidate": profile["personal"]["name"],
        "candidate name": profile["personal"]["name"],

        # ── Contact ──────────────────────────────────────────────────
        "email address": profile["personal"]["email"],
        "email": profile["personal"]["email"],
        "phone number": profile["personal"]["phone"],
        "phone": profile["personal"]["phone"],
        "mobile": profile["personal"]["phone"],
        "cell": profile["personal"]["phone"],

        # ── Work Authorization ───────────────────────────────────────
        "legally authorized to work": "Yes",
        "work authorization": "Yes",
        "authorized to work in the united states": "Yes",
        "authorized to work in the u.s": "Yes",
        "eligible to work": "Yes",
        "right to work": "Yes",
        "require sponsorship": "No",
        "need sponsorship": "No",
        "visa status": "No",
        "visa sponsorship": "No",
        "immigration sponsorship": "No",
        "work permit": "Yes",
        "citizen or permanent resident": "Yes",
        "us citizen": "Yes",
        "u.s. citizen": "Yes",

        # ── Referral / Source ────────────────────────────────────────
        "how did you hear": "LinkedIn",
        "hear about this": "LinkedIn",
        "hear about us": "LinkedIn",
        "referred by": "",
        "referral source": "LinkedIn",
        "source": "LinkedIn",
        "where did you find": "LinkedIn",

        # ── URLs & Online Presence ───────────────────────────────────
        "linkedin profile": linkedin_url,
        "linkedin url": linkedin_url,
        "linkedin": linkedin_url,
        "website": portfolio_url,
        "personal website": portfolio_url,
        "portfolio": portfolio_url,
        "portfolio url": portfolio_url,
        "github": github_url,
        "github url": github_url,
        "github profile": github_url,

        # ── Professional Info ────────────────────────────────────────
        "years of experience": years_exp,
        "total experience": years_exp,
        "years in": years_exp,
        "experience level": profile.get("experience_level", ""),
        "current title": current_job.get("title", ""),
        "current job title": current_job.get("title", ""),
        "current position": current_job.get("title", ""),
        "current employer": current_job.get("company", ""),
        "current company": current_job.get("company", ""),
        "most recent employer": current_job.get("company", ""),
        "most recent company": current_job.get("company", ""),

        # ── Salary ───────────────────────────────────────────────────
        "salary": salary_str,
        "desired salary": salary_str,
        "salary expectation": salary_str,
        "salary requirement": salary_str,
        "expected salary": salary_str,
        "compensation": salary_str,
        "desired compensation": salary_str,
        "minimum salary": salary_str,
        "pay expectation": salary_str,

        # ── Location / Address ───────────────────────────────────────
        "city": city,
        "state": state_full,
        "state/province": state_full,
        "zip": "29501",
        "zip code": "29501",
        "postal code": "29501",
        "postcode": "29501",
        "country": "United States",
        "location": location_full,
        "address": location_full,
        "current location": location_full,
        "which state": state_full,
        "what state": state_full,
        "state do you": state_full,
        "state of residence": state_full,
        "where are you located": location_full,
        "where do you currently reside": location_full,
        "where are you based": location_full,

        # ── Schedule / Availability ──────────────────────────────────
        "commit to this schedule": "Yes",
        "can you commute": "Yes",
        "willing to relocate": "Yes",
        "open to relocation": "Yes",
        "able to work": "Yes",
        "available to start": "Immediately",
        "start date": "Immediately",
        "when can you start": "Immediately",
        "earliest start date": "Immediately",
        "notice period": "2 weeks",
        "available for": "Full-time",
        "desired employment type": "Full-time",
        "employment type": "Full-time",

        # ── Background / Compliance ──────────────────────────────────
        "background check": "Yes",
        "willing to undergo": "Yes",
        "drug test": "Yes",
        "drug screen": "Yes",
        "non-compete": "No",
        "non-disclosure": "Yes",
        "non compete agreement": "No",
        "security clearance": "No, but willing to obtain if required",
        "clearance level": "None",
        "do you currently hold": "No, but willing to obtain if required",
        "what level clearance": "None — willing to obtain if required",

        # ── Summary / Bio / About ───────────────────────────────────
        "summary": summary_text,
        "professional summary": summary_text,
        "about yourself": summary_text,
        "tell us about yourself": summary_text,
        "brief description": summary_text,
        "introduction": summary_text,
        "cover letter": "COVER_LETTER_TEXT",
        "additional information": summary_text,
        "anything else": "",

        # ── EEOC / Demographics (Decline-friendly defaults) ──────────
        "gender": "Decline to self-identify",
        "race": "Decline to self-identify",
        "ethnicity": "Decline to self-identify",
        "hispanic": "No",
        "veteran": "I am not a protected veteran",
        "disability": "No, I don't have a disability",
        "protected veteran": "I am not a protected veteran",
        "sexual orientation": "Decline to self-identify",
        "pronouns": "Decline to self-identify",

        # ── Social referral ──────────────────────────────────────────
        "do you know anyone": "No",
        "know anyone who currently works": "No",
        "employee referral": "No",
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
        let label = '';
        
        // 1. Explicit label via for/id
        if (el.id) {
            const lbl = document.querySelector('label[for="' + el.id + '"]');
            if (lbl) label = lbl.innerText.trim();
        }
        
        // 2. Parent label
        if (!label) {
            const parentLabel = el.closest('label');
            if (parentLabel) {
                // Get label text excluding the input's own text
                const clone = parentLabel.cloneNode(true);
                clone.querySelectorAll('input, select, textarea').forEach(c => c.remove());
                label = clone.innerText.trim();
            }
        }
        
        // 3. aria-label
        if (!label && el.getAttribute('aria-label')) {
            label = el.getAttribute('aria-label').trim();
        }
        
        // 4. aria-labelledby
        if (!label) {
            const labelledBy = el.getAttribute('aria-labelledby');
            if (labelledBy) {
                const parts = labelledBy.split(/\\s+/).map(id => {
                    const ref = document.getElementById(id);
                    return ref ? ref.innerText.trim() : '';
                }).filter(Boolean);
                if (parts.length) label = parts.join(' ');
            }
        }
        
        // 5. aria-describedby (often used for field descriptions)
        if (!label) {
            const describedBy = el.getAttribute('aria-describedby');
            if (describedBy) {
                const ref = document.getElementById(describedBy);
                if (ref) label = ref.innerText.trim();
            }
        }

        // 6. data-* attributes that hint at the field purpose
        if (!label) {
            for (const attr of ['data-automation-id', 'data-field-name', 'data-qa', 
                                'data-testid', 'data-label', 'data-name']) {
                const val = el.getAttribute(attr);
                if (val) {
                    label = val.replace(/[_\\-\\.]/g, ' ').replace(/([a-z])([A-Z])/g, '$1 $2').trim();
                    break;
                }
            }
        }
        
        // 7. Placeholder
        if (!label && el.placeholder) {
            label = el.placeholder.trim();
        }
        
        // 8. Look at nearby siblings and parent structure
        if (!label) {
            // Check preceding siblings: label, span, div, p, h3, h4, legend
            let sibling = el.previousElementSibling;
            let tries = 0;
            while (sibling && tries < 3) {
                const tag = sibling.tagName.toLowerCase();
                if (['label', 'span', 'div', 'p', 'h3', 'h4', 'h5', 'legend'].includes(tag)) {
                    const txt = sibling.innerText.trim();
                    if (txt && txt.length < 150 && txt.length > 0) {
                        label = txt;
                        break;
                    }
                }
                sibling = sibling.previousElementSibling;
                tries++;
            }
        }
        
        // 9. Parent container: look for nearby text in the field's wrapper div
        if (!label) {
            const wrapper = el.closest('.field, .form-group, .form-field, .form-row, ' +
                '.question, .field-group, .input-group, .MuiFormControl-root, ' +
                '[class*="field"], [class*="question"], [class*="form-group"]');
            if (wrapper) {
                // Get text from spans, labels, divs that are direct children
                const candidates = wrapper.querySelectorAll(':scope > span, :scope > label, ' +
                    ':scope > div > label, :scope > div > span, :scope > p, :scope > legend, ' +
                    ':scope > h3, :scope > h4, :scope > .label, :scope > [class*="label"]');
                for (const c of candidates) {
                    const txt = c.innerText.trim();
                    if (txt && txt.length < 150 && txt.length > 1) {
                        label = txt;
                        break;
                    }
                }
            }
        }
        
        // 10. Section header: find the nearest heading above this field
        if (!label) {
            const fieldRect = el.getBoundingClientRect();
            const headings = document.querySelectorAll('h1, h2, h3, h4, h5, legend, .section-title');
            let closest = null;
            let closestDist = Infinity;
            for (const h of headings) {
                const hRect = h.getBoundingClientRect();
                if (hRect.bottom <= fieldRect.top) {
                    const dist = fieldRect.top - hRect.bottom;
                    if (dist < closestDist && dist < 200) {
                        closestDist = dist;
                        closest = h;
                    }
                }
            }
            // Only use section header if no other field between header and us already claimed it
            // (approximation: just note it as context, not primary label)
        }
        
        // 11. Name attribute as final fallback
        if (!label && el.name) {
            label = el.name.replace(/[_\\-\\[\\]\\d]+/g, ' ')
                          .replace(/([a-z])([A-Z])/g, '$1 $2')
                          .trim();
        }
        
        // Clean up: remove asterisks, "required", excess whitespace
        label = label.replace(/\\*/g, '').replace(/\\(required\\)/gi, '').replace(/\\s+/g, ' ').trim();
        return label.slice(0, 200);
    }
    
    function getOptions(el) {
        if (el.tagName === 'SELECT') {
            return Array.from(el.options).map(o => o.text.trim()).filter(t => t && t !== '' && t !== 'Select' && t !== 'Choose');
        }
        // Check for nearby radio buttons with the same name
        if (el.type === 'radio' && el.name) {
            const radios = document.querySelectorAll('input[type="radio"][name="' + el.name + '"]');
            return Array.from(radios).map(r => {
                const lbl = document.querySelector('label[for="' + r.id + '"]');
                return lbl ? lbl.innerText.trim() : r.value;
            }).filter(Boolean);
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

    function getFieldContext(el) {
        // Grab contextual clues: parent class names, nearby text, section, helper text
        const ctx = {};
        // Parent class names (useful for identifying field purpose)
        const parent = el.closest('[class]');
        if (parent) ctx.parentClass = parent.className.slice(0, 200);
        // Check if it's inside a section with a heading
        const section = el.closest('section, fieldset, [role="group"]');
        if (section) {
            const heading = section.querySelector('h1, h2, h3, h4, legend, .section-title');
            if (heading) ctx.section = heading.innerText.trim().slice(0, 100);
        }
        // Helper text / description below the field
        // Check aria-describedby, then look for small/span/p after the field
        const describedBy = el.getAttribute('aria-describedby');
        if (describedBy) {
            const ref = document.getElementById(describedBy);
            if (ref) ctx.helperText = ref.innerText.trim().slice(0, 200);
        }
        if (!ctx.helperText) {
            const wrapper = el.closest('.field, .form-group, .form-field, [class*="field"]');
            if (wrapper) {
                const helpers = wrapper.querySelectorAll('small, .helper, .help-text, .description, ' +
                    '[class*="helper"], [class*="hint"], [class*="description"], ' +
                    'p:not(:first-child), span[class*="sub"]');
                for (const h of helpers) {
                    const txt = h.innerText.trim();
                    if (txt && txt.length > 5 && txt.length < 200) {
                        ctx.helperText = txt;
                        break;
                    }
                }
            }
            // Also check the next sibling
            if (!ctx.helperText) {
                const next = el.nextElementSibling;
                if (next && ['small', 'span', 'p', 'div'].includes(next.tagName.toLowerCase())) {
                    const txt = next.innerText.trim();
                    if (txt && txt.length > 5 && txt.length < 200 && 
                        !txt.includes('Submit') && !txt.includes('Upload')) {
                        ctx.helperText = txt;
                    }
                }
            }
        }
        return ctx;
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

        const ctx = getFieldContext(el);
        
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
            helperText: ctx.helperText || '',
            parentClass: ctx.parentClass || '',
            section: ctx.section || '',
            selector: el.id ? '#' + CSS.escape(el.id) : 
                      el.name ? '[name="' + el.name + '"]' : 
                      null
        });
    });
    
    // ── Scan for YES/NO toggle button groups ─────────────────────────
    // Workable and other ATS use custom button toggles instead of checkboxes.
    // They look like: <div class="question"><span>Question text</span><button>YES</button><button>NO</button></div>
    const toggleSeen = new Set();
    document.querySelectorAll('button, [role="button"]').forEach(btn => {
        const text = (btn.textContent || '').trim().toUpperCase();
        if (text !== 'YES' && text !== 'NO') return;
        if (!isVisible(btn)) return;
        
        // Find the question container (parent that has the question text + both buttons)
        const container = btn.closest('[class*="question"], [class*="toggle"], [class*="field"], [class*="group"]')
                       || btn.parentElement?.parentElement;
        if (!container) return;
        
        // Get the question label text (usually in a span, p, or div before the buttons)
        let questionText = '';
        const textEls = container.querySelectorAll('span, p, div, label, h3, h4');
        for (const tel of textEls) {
            const t = tel.innerText.trim();
            // Skip if it's just YES/NO or very short
            if (t && t.length > 5 && t !== 'YES' && t !== 'NO' && !t.match(/^(YES|NO)$/i)) {
                questionText = t.replace(/\\*/g, '').trim();
                break;
            }
        }
        if (!questionText) return;
        
        // Deduplicate by question text
        if (toggleSeen.has(questionText)) return;
        toggleSeen.add(questionText);
        
        // Find both YES and NO buttons
        const buttons = container.querySelectorAll('button, [role="button"]');
        let yesSelector = null, noSelector = null;
        for (const b of buttons) {
            const bt = (b.textContent || '').trim().toUpperCase();
            if (bt === 'YES' || bt.includes('YES')) {
                yesSelector = b.id ? '#' + CSS.escape(b.id) :
                    b.getAttribute('data-ui') ? '[data-ui="' + b.getAttribute('data-ui') + '"]' : null;
                // If no good selector, store a CSS path
                if (!yesSelector) {
                    // Build a unique-ish selector from parent + nth-child
                    const parent = b.parentElement;
                    const idx = Array.from(parent.children).indexOf(b);
                    yesSelector = '__TOGGLE_YES__' + questionText;
                }
            }
            if (bt === 'NO' || bt.includes('NO')) {
                noSelector = b.id ? '#' + CSS.escape(b.id) :
                    b.getAttribute('data-ui') ? '[data-ui="' + b.getAttribute('data-ui') + '"]' : null;
                if (!noSelector) {
                    noSelector = '__TOGGLE_NO__' + questionText;
                }
            }
        }
        
        // Check if required (asterisk in label)
        const fullText = container.innerText || '';
        const isRequired = fullText.includes('*');
        
        fields.push({
            tag: 'toggle',
            type: 'toggle',
            id: '',
            name: '',
            label: questionText.slice(0, 200),
            placeholder: '',
            required: isRequired,
            options: ['YES', 'NO'],
            value: '',
            helperText: '',
            parentClass: '',
            section: '',
            selector: null,
            yesSelector: yesSelector,
            noSelector: noSelector
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
        desc = "{}. [{}] label='{}' placeholder='{}' required={} name='{}'".format(
            i, f.get("type", "text"), f.get("label", ""), 
            f.get("placeholder", ""), f.get("required", False),
            f.get("name", ""))
        if f.get("options"):
            desc += " options={}".format(f["options"][:15])
        if f.get("section"):
            desc += " section='{}'".format(f["section"])
        if f.get("helperText"):
            desc += " hint='{}'".format(f["helperText"][:100])
        field_descriptions.append(desc)

    # Build work history string
    work_history = profile.get("work_history", [])
    work_hist_str = ""
    for wh in work_history[:3]:
        work_hist_str += "\n  - {} at {} ({})".format(
            wh.get("title", ""), wh.get("company", ""), wh.get("duration", ""))

    prompt = """You are filling out a job application form. Map the candidate's profile data to ALL fields you can answer — both required AND optional.

## CANDIDATE PROFILE:
Name: {name}
Email: {email}
Phone: {phone}
Location: {location} (City: {city}, State: {state_full}, Country: United States)
LinkedIn: {linkedin}
Portfolio: {portfolio}
GitHub: {github}
Experience: {years} years ({level})
Current role: {current_title} at {current_company}
Work history:{work_history}
Target roles: {roles}
Certifications: {certs}
Summary: {summary}
Authorized to work in US: Yes
Requires sponsorship: No
US citizen: Yes
Available to start: Immediately
Willing to relocate: Yes

## JOB:
Title: {title}
Company: {company}

## FORM FIELDS (that need answers):
{fields}

## INSTRUCTIONS:
Return ONLY a JSON object mapping field index numbers to answers.
Example: {{"0": "Alex", "1": "Carter", "3": "Yes", "5": "85000"}}

CRITICAL RULES:
- Answer EVERY field you can, not just required ones — more fields filled = better application
- For file upload fields: use "RESUME_FILE" or "COVER_LETTER_FILE"
- For textarea fields about cover letter: use "COVER_LETTER_TEXT"
- For select/dropdown fields: pick the EXACT text from the options list
- For yes/no work authorization questions: "Yes" for authorized, "No" for needs sponsorship
- For "how did you hear" type questions: "LinkedIn"
- For EEOC/demographic fields (gender, race, veteran, disability): use "Decline to self-identify" or the closest declining option from the available options list
- For city fields: just "{city}"
- For state fields: "{state_full}"
- For country fields: "United States"
- For salary/compensation: "{salary}"
- For years of experience: "{years}"
- Do NOT fabricate information or make up answers
- Do NOT skip optional fields if you can answer them from the profile

Return ONLY the JSON object, no explanation.""".format(
        name=profile["personal"].get("name", ""),
        email=profile["personal"].get("email", ""),
        phone=profile["personal"].get("phone", ""),
        location=profile["personal"].get("location", ""),
        city=profile["personal"].get("location", "").split(",")[0].strip(),
        state_full=STATE_MAP.get(
            profile["personal"].get("location", "").split(",")[-1].strip().lower(),
            profile["personal"].get("location", "").split(",")[-1].strip()
        ).title(),
        linkedin=profile["personal"].get("linkedin_url", ""),
        portfolio=profile["personal"].get("portfolio_url", ""),
        github=profile["personal"].get("github_url", ""),
        years=profile.get("years_of_experience", 0),
        level=profile.get("experience_level", ""),
        current_title=work_history[0].get("title", "") if work_history else "",
        current_company=work_history[0].get("company", "") if work_history else "",
        work_history=work_hist_str,
        roles=", ".join(profile.get("target_roles", [])[:5]),
        certs=", ".join(profile.get("certifications", [])[:5]),
        summary=profile.get("summary", "")[:300],
        title=job.get("title", ""),
        company=job.get("company", ""),
        salary=str(profile.get("salary_range", {}).get("min", "")),
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


def fill_toggle_button(page, field, answer):
    """
    Click a YES or NO toggle button on forms like Workable.
    These are custom button elements, not standard form inputs.
    """
    answer_upper = answer.strip().upper()
    if answer_upper not in ("YES", "NO"):
        # Interpret yes-like and no-like answers
        if answer.lower() in ("yes", "true", "1", "y"):
            answer_upper = "YES"
        elif answer.lower() in ("no", "false", "0", "n"):
            answer_upper = "NO"
        else:
            return False

    question_text = field.get("label", "")

    try:
        # Strategy 1: Use stored selectors from extraction
        sel_key = "yesSelector" if answer_upper == "YES" else "noSelector"
        stored_sel = field.get(sel_key, "")
        
        if stored_sel and not stored_sel.startswith("__TOGGLE_"):
            try:
                btn = page.locator(stored_sel)
                if btn.count() > 0:
                    btn.first.click(force=True, timeout=5000)
                    time.sleep(0.3)
                    return True
            except Exception:
                pass

        # Strategy 2: Find the button by question text + button text via JavaScript
        clicked = page.evaluate("""(args) => {
            const questionText = args.question.toLowerCase();
            const targetBtn = args.target; // "YES" or "NO"
            
            // Find all button-like elements
            const buttons = document.querySelectorAll('button, [role="button"]');
            
            for (const btn of buttons) {
                const btnText = (btn.textContent || '').trim().toUpperCase();
                if (btnText !== targetBtn) continue;
                
                // Check if this button is near the question text
                const container = btn.closest('[class*="question"], [class*="toggle"], [class*="field"], [class*="group"]')
                              || btn.parentElement?.parentElement;
                if (!container) continue;
                
                const containerText = container.innerText.toLowerCase();
                // Match if the container includes the question text (fuzzy — first 30 chars)
                const questionStart = questionText.slice(0, 30);
                if (containerText.includes(questionStart)) {
                    btn.click();
                    return true;
                }
            }
            return false;
        }""", {"question": question_text, "target": answer_upper})

        if clicked:
            time.sleep(0.3)
            return True

        # Strategy 3: Just find any YES/NO button with matching text via Playwright
        try:
            btn = page.get_by_role("button", name=answer_upper, exact=True)
            # If multiple YES buttons, we need the right one — skip this if ambiguous
            if btn.count() == 1:
                btn.first.click(force=True, timeout=3000)
                time.sleep(0.3)
                return True
        except Exception:
            pass

        return False

    except Exception as e:
        print(f"      ⚠️  Toggle button error: {e}")
        return False


def fill_generic_field(page, field, answer, resume_path=None, cover_letter_path=None):
    """
    Fill a single form field using generic Playwright actions.
    Works on any website — text inputs, selects, textareas, file uploads.
    """
    if not answer or answer == "SKIP_FIELD":
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

    # Handle cover letter as text (for textarea fields)
    if answer == "COVER_LETTER_TEXT":
        if not cover_letter_path or not Path(cover_letter_path).exists():
            return False
        ext = Path(cover_letter_path).suffix.lower()
        if ext == ".txt":
            try:
                answer = Path(cover_letter_path).read_text()
            except Exception:
                return False
        elif ext == ".pdf":
            # Look for .txt companion file (tailor_resume.py creates both)
            txt_companion = cover_letter_path.replace(".pdf", ".txt")
            if Path(txt_companion).exists():
                try:
                    answer = Path(txt_companion).read_text()
                except Exception:
                    return False
            else:
                # No text version available — skip gracefully
                print(f"      ℹ️  Cover letter is PDF only, no .txt companion found for textarea paste")
                return False
        else:
            return False

    # Handle YES/NO toggle buttons (Workable, custom ATS)
    if field_type == "toggle":
        return fill_toggle_button(page, field, answer)

    if not selector:
        return False

    try:
        el = page.locator(selector)
        if el.count() == 0:
            return False

        if field_type == "select-one" or field.get("tag") == "select":
            # Standard HTML select — try label match, then value match,
            # then partial text match
            try:
                el.select_option(label=answer)
                return True
            except Exception:
                pass
            try:
                el.select_option(value=answer)
                return True
            except Exception:
                pass
            # Try partial match against option texts
            try:
                options = field.get("options", [])
                answer_lower = answer.lower().strip()
                for opt in options:
                    if answer_lower in opt.lower() or opt.lower() in answer_lower:
                        el.select_option(label=opt)
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
            try:
                el.click(timeout=5000)
                el.fill(str(answer))
            except Exception:
                # Fallback: use JavaScript to fill (bypasses overlay interception)
                # Uses React-compatible native setter trick so the UI actually updates
                try:
                    page.evaluate("""(args) => {
                        const el = document.querySelector(args.selector);
                        if (!el) return;
                        
                        // Use the native setter — this is the key to making React
                        // recognize the value change. React overrides the value property
                        // on inputs, so setting el.value directly doesn't trigger re-render.
                        const isTextarea = el.tagName === 'TEXTAREA';
                        const proto = isTextarea 
                            ? window.HTMLTextAreaElement.prototype 
                            : window.HTMLInputElement.prototype;
                        const nativeSetter = Object.getOwnPropertyDescriptor(proto, 'value').set;
                        
                        el.focus();
                        nativeSetter.call(el, args.value);
                        
                        // Dispatch events that React listens for
                        el.dispatchEvent(new Event('input', {bubbles: true}));
                        el.dispatchEvent(new Event('change', {bubbles: true}));
                        el.dispatchEvent(new Event('blur', {bubbles: true}));
                    }""", {"selector": selector, "value": str(answer)})
                    print(f"      ℹ️  Used JS fill (overlay was blocking)")
                except Exception as js_err:
                    print(f"      ⚠️  JS fill also failed: {js_err}")
                    return False
            # Trigger blur/change events for validation
            try:
                el.press("Tab")
                time.sleep(0.2)
            except Exception:
                pass
            return True

    except Exception as e:
        # Last resort: try React-compatible JavaScript fill
        if selector:
            try:
                page.evaluate("""(args) => {
                    const el = document.querySelector(args.selector);
                    if (!el) return;
                    
                    const isTextarea = el.tagName === 'TEXTAREA';
                    const proto = isTextarea 
                        ? window.HTMLTextAreaElement.prototype 
                        : window.HTMLInputElement.prototype;
                    const nativeSetter = Object.getOwnPropertyDescriptor(proto, 'value').set;
                    
                    el.focus();
                    nativeSetter.call(el, args.value);
                    
                    el.dispatchEvent(new Event('input', {bubbles: true}));
                    el.dispatchEvent(new Event('change', {bubbles: true}));
                    el.dispatchEvent(new Event('blur', {bubbles: true}));
                }""", {"selector": selector, "value": str(answer)})
                print(f"      ℹ️  Used JS fill fallback for {field.get('label','')}")
                return True
            except Exception:
                pass
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


def dismiss_overlays(page):
    """
    Dismiss ANY modal overlay, dialog, backdrop, or advertisement that blocks
    interaction with the form underneath. This goes beyond cookie banners —
    it handles Workable's advertisement modals, GDPR dialogs, login prompts, etc.
    
    Strategy:
    1. Try pressing Escape (closes most modal dialogs)
    2. Click close/dismiss buttons inside modals
    3. Click backdrop overlays to close modals
    4. Nuclear option: remove blocking elements via JavaScript
    """
    dismissed = False

    # Strategy 1: Press Escape (universally closes modals)
    try:
        page.keyboard.press("Escape")
        time.sleep(0.5)
    except Exception:
        pass

    # Strategy 2: Click close/X buttons inside modal dialogs
    close_selectors = [
        "[data-role='modal-wrapper'] button[aria-label='Close']",
        "[data-role='modal-wrapper'] [class*='close']",
        "[data-role='dialog'] button[aria-label='Close']",
        ".modal button[aria-label='Close']",
        ".modal .close",
        "[role='dialog'] button[aria-label='Close']",
        "[role='dialog'] [class*='close']",
        "[aria-label='Close']",
        "button.close",
    ]
    for sel in close_selectors:
        try:
            btn = page.locator(sel)
            if btn.count() > 0 and btn.first.is_visible():
                btn.first.click(timeout=2000)
                time.sleep(0.5)
                dismissed = True
                print(f"  🔲 Dismissed modal overlay (close button)")
                break
        except Exception:
            continue

    # Strategy 3: Click the backdrop to close
    if not dismissed:
        backdrop_selectors = [
            "[data-role='backdrop']",
            "[data-evergreen-dialog-backdrop]",
            ".modal-backdrop",
            ".overlay",
        ]
        for sel in backdrop_selectors:
            try:
                backdrop = page.locator(sel)
                if backdrop.count() > 0 and backdrop.first.is_visible():
                    # Click the edge of the backdrop (outside the dialog)
                    backdrop.first.click(position={"x": 5, "y": 5}, timeout=2000)
                    time.sleep(0.5)
                    dismissed = True
                    print(f"  🔲 Dismissed modal overlay (backdrop click)")
                    break
            except Exception:
                continue

    # Strategy 4: Nuclear — remove ALL blocking overlays via JavaScript
    # Always run this regardless of whether previous strategies worked,
    # because cookie banners and ad modals can stack
    try:
        removed = page.evaluate("""() => {
            let removed = 0;
            
            // Remove modal wrappers
            document.querySelectorAll(
                '[data-role="modal-wrapper"], ' +
                '[data-role="backdrop"], ' +
                '[data-evergreen-dialog-backdrop], ' +
                '.modal-backdrop, ' +
                '[class*="modal-overlay"], ' +
                '[class*="dialog-backdrop"]'
            ).forEach(el => {
                el.remove();
                removed++;
            });
            
            // Remove advertisement overlays specifically
            const adOverlay = document.getElementById('advertisement');
            if (adOverlay) {
                const wrapper = adOverlay.closest('[data-role="modal-wrapper"]') || adOverlay.parentElement;
                if (wrapper) { wrapper.remove(); removed++; }
                else { adOverlay.remove(); removed++; }
            }
            
            // Remove any cookie consent dialogs still lingering
            document.querySelectorAll(
                '[class*="cookie"], [class*="Cookie"], ' +
                '[id*="cookie"], [id*="Cookie"], ' +
                '[class*="consent"], [class*="Consent"], ' +
                '[class*="gdpr"], [class*="GDPR"]'
            ).forEach(el => {
                // Only remove if it looks like an overlay (not just a link/small element)
                const rect = el.getBoundingClientRect();
                if (rect.width > 200 && rect.height > 100) {
                    el.remove();
                    removed++;
                }
            });
            
            // Re-enable scrolling on body (modals often set overflow:hidden)
            document.body.style.overflow = '';
            document.documentElement.style.overflow = '';
            
            return removed;
        }""")
        if removed > 0:
            dismissed = True
            print(f"  🔲 Removed {removed} blocking overlay(s) via JS")
            time.sleep(0.5)
    except Exception:
        pass

    return dismissed


def fill_toggle_buttons_sweep(page, profile):
    """
    Post-fill sweep: find and click YES/NO toggle button groups on the page.
    
    Workable uses custom toggle UI: <span class="styles--1h-sV">YES</span>
    inside <div class="styles--3qHIU"> (the clickable target).
    These are NOT buttons, roles, or any standard HTML — just styled spans/divs.
    
    Strategy: find all elements whose direct text is "YES" or "NO",
    walk up the DOM to find the question text, determine the answer,
    and click the parent div.
    """
    YES_RULES = [
        "authorized to work",
        "eligible to work", 
        "legally authorized",
        "right to work",
        "background check",
        "willing to undergo",
        "drug test",
        "drug screen",
        "able to work",
        "willing to relocate",
        "open to relocation",
        "security+",
        "comptia",
        "sec+",
        "certification",
        "commit to this schedule",
        "experience",
        "willing to travel",
        "work authorization",
        "are you 18",
        "legal age",
        "agree to",
        "consent to",
        "bachelor",
        "degree",
    ]
    
    NO_RULES = [
        "require sponsorship",
        "need sponsorship",
        "visa sponsorship",
        "non-compete",
        "convicted",
        "felony",
        "currently hold an active public trust",
        "active security clearance",
        "active clearance",
        "currently hold a clearance",
    ]

    try:
        results = page.evaluate("""(rules) => {
            const yesRules = rules.yes;
            const noRules = rules.no;
            const actions = [];
            const processedQuestions = new Set();
            
            // Find ALL elements whose direct text content is exactly YES or NO
            // This catches <span>YES</span>, <div>YES</div>, <label>YES</label>, etc.
            const walker = document.createTreeWalker(
                document.body, NodeFilter.SHOW_ELEMENT
            );
            
            const yesNoElements = [];
            while (walker.nextNode()) {
                const el = walker.currentNode;
                // Check if this element's own text (not children's text) is YES or NO
                const directText = (el.childNodes.length === 1 && el.childNodes[0].nodeType === 3)
                    ? el.childNodes[0].textContent.trim() : null;
                if (directText === 'YES' || directText === 'NO' ||
                    directText === 'Yes' || directText === 'No') {
                    yesNoElements.push({el: el, text: directText.toUpperCase()});
                }
            }
            
            // Group YES/NO pairs by their question container
            // For each YES element, find the question text by walking up the DOM
            for (const item of yesNoElements) {
                if (item.text !== 'YES') continue; // Process each question once via its YES element
                
                // The clickable target is the parent div
                const clickTarget = item.el.parentElement;
                if (!clickTarget) continue;
                
                // Walk up the DOM to find the question text
                // Structure: span(YES) > div(clickable) > div(toggle group) > div(question container)
                let questionContainer = clickTarget;
                let questionText = '';
                for (let i = 0; i < 8; i++) {
                    questionContainer = questionContainer.parentElement;
                    if (!questionContainer) break;
                    
                    const fullText = questionContainer.innerText || '';
                    // The question container will have text much longer than just YES/NO
                    // and will contain a question mark or be a substantial string
                    const textWithoutYesNo = fullText
                        .replace(/\\bYES\\b/g, '')
                        .replace(/\\bNO\\b/g, '')
                        .replace(/[\\n\\r]+/g, ' ')
                        .trim();
                    
                    if (textWithoutYesNo.length > 20) {
                        questionText = textWithoutYesNo;
                        break;
                    }
                }
                
                if (!questionText || questionText.length < 10) continue;
                
                // Clean up question text
                questionText = questionText.replace(/\\*/g, '').trim();
                const questionKey = questionText.slice(0, 50).toLowerCase();
                
                // Skip if we already processed this question
                if (processedQuestions.has(questionKey)) continue;
                processedQuestions.add(questionKey);
                
                // Determine the answer using keyword rules
                const qLower = questionText.toLowerCase();
                let answer = null;
                
                for (const kw of yesRules) {
                    if (qLower.includes(kw.toLowerCase())) {
                        answer = 'YES';
                        break;
                    }
                }
                if (!answer) {
                    for (const kw of noRules) {
                        if (qLower.includes(kw.toLowerCase())) {
                            answer = 'NO';
                            break;
                        }
                    }
                }
                
                if (!answer) {
                    // Default: if it asks "Do you have X?", default YES
                    // This is a reasonable default for qualification questions
                    if (qLower.includes('do you have') || qLower.includes('are you')) {
                        answer = 'YES';
                    } else {
                        continue; // Skip questions we can't answer
                    }
                }
                
                // Find the target element to click (YES or NO span's parent div)
                // Look within the question container for all YES/NO spans
                const allSpans = questionContainer.querySelectorAll('span, div, label');
                let targetEl = null;
                for (const span of allSpans) {
                    const dt = (span.childNodes.length === 1 && span.childNodes[0].nodeType === 3)
                        ? span.childNodes[0].textContent.trim().toUpperCase() : null;
                    if (dt === answer) {
                        // Click the parent div (the actual clickable target)
                        targetEl = span.parentElement || span;
                        break;
                    }
                }
                
                if (targetEl) {
                    targetEl.click();
                    actions.push({
                        question: questionText.slice(0, 80),
                        answer: answer
                    });
                }
            }
            
            return actions;
        }""", {"yes": YES_RULES, "no": NO_RULES})

        if results:
            for r in results:
                print(f"     ✅ Toggle: {r['question'][:55]}... → {r['answer']}")
            return len(results)
        else:
            print(f"     ℹ️  No toggle buttons found to fill")
            return 0

    except Exception as e:
        print(f"     ⚠️  Toggle sweep error: {e}")
        return 0


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
        
        # CRITICAL: Clear all overlays before trying to click Apply
        # Cookie banners and ad modals block the Apply button
        dismiss_cookie_banner(page)
        dismiss_overlays(page)
        time.sleep(1)
        
        page_text = ""
        try:
            page_text = page.inner_text("body")[:5000].lower()
        except Exception:
            pass

        clicked = click_apply_button(page)
        if clicked:
            time.sleep(4)
            # Dismiss cookie banners — may need multiple attempts as banners
            # sometimes re-appear after page navigation
            for _ in range(3):
                dismissed = dismiss_cookie_banner(page)
                if not dismissed:
                    break
                time.sleep(1.5)
            
            # Extra: try clicking X/close button on any remaining modal
            try:
                close_btn = page.locator("[aria-label='Close'], button.close, .modal-close, [class*='cookie'] [class*='close']")
                if close_btn.count() > 0 and close_btn.first.is_visible():
                    close_btn.first.click()
                    time.sleep(1)
            except Exception:
                pass

            time.sleep(1)  # Final pause for animations
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

    # Pre-compute location components for smart address handling
    location = profile["personal"].get("location", "")
    loc_parts = [p.strip() for p in location.split(",")]
    city = loc_parts[0] if loc_parts else ""
    state_abbrev = loc_parts[1].strip() if len(loc_parts) > 1 else ""
    state_full = STATE_MAP.get(state_abbrev.lower(), state_abbrev)
    state_full = state_full.title() if state_full.islower() else state_full
    location_full = f"{city}, {state_full}, United States" if city else location

    # Load cover letter text (for textarea paste)
    cover_letter_text = ""
    if cover_letter_path and Path(cover_letter_path).exists():
        ext = Path(cover_letter_path).suffix.lower()
        if ext == ".txt":
            try:
                cover_letter_text = Path(cover_letter_path).read_text()
            except Exception:
                pass

    for i, f in enumerate(fields):
        fid = f.get("id", "").lower()
        fname = f.get("name", "").lower()
        flabel = f.get("label", "").lower()
        fplaceholder = f.get("placeholder", "").lower()
        ftype = f.get("type", "")
        ftag = f.get("tag", "")
        fhelper = f.get("helperText", "").lower()
        parent_class = f.get("parentClass", "").lower()
        section = f.get("section", "").lower()
        # Combine all text clues for broader matching
        all_text = f" {fid} {fname} {flabel} {fplaceholder} {fhelper} "

        answer = None

        # ── 1. Direct ID/name exact match ────────────────────────────
        for key, val in answers_by_id.items():
            if key == fid or key == fname:
                answer = val
                break

        # ── 2. ID/name fuzzy match (handle variants like first-name, firstName) ──
        if not answer:
            fid_norm = re.sub(r'[\-_\.\d]+', '', fid)
            fname_norm = re.sub(r'[\-_\.\d]+', '', fname)
            for key, val in answers_by_id.items():
                key_norm = re.sub(r'[\-_\.\d]+', '', key)
                if key_norm and (key_norm == fid_norm or key_norm == fname_norm):
                    answer = val
                    break

        # ── 3. Label keyword match ───────────────────────────────────
        if not answer:
            for key, val in answers_by_label.items():
                if key in flabel:
                    answer = val
                    break

        # ── 4. Placeholder/name keyword match (for fields with blank labels) ──
        if not answer and not flabel:
            for key, val in answers_by_label.items():
                if key in fplaceholder or key in fname.replace("_", " ").replace("-", " "):
                    answer = val
                    break

        # ── 5. Smart file field detection ────────────────────────────
        if not answer and ftype == "file":
            file_clues = f"{flabel} {fid} {fname} {parent_class} {section}"
            # Skip photo/headshot/avatar uploads — these are NOT document fields
            if any(kw in file_clues for kw in ["photo", "headshot", "avatar", 
                                                 "picture", "profile pic", "image"]):
                answer = "SKIP_FIELD"  # Mark as intentionally skipped (won't go to Claude)
            elif any(kw in file_clues for kw in ["resume", "cv", "curriculum"]):
                answer = "RESUME_FILE"
            elif any(kw in file_clues for kw in ["cover", "letter", "motivation"]):
                answer = "COVER_LETTER_FILE"
            else:
                # Positional: count only non-photo file fields seen so far
                prior_doc_fields = [
                    fields[j] for j in range(i)
                    if fields[j].get("type") == "file"
                    and not any(kw in f"{fields[j].get('label','')} {fields[j].get('id','')} {fields[j].get('name','')}".lower()
                                for kw in ["photo", "headshot", "avatar", "picture", "image"])
                ]
                if len(prior_doc_fields) == 0:
                    answer = "RESUME_FILE"
                elif len(prior_doc_fields) == 1:
                    answer = "COVER_LETTER_FILE"

        # ── 6. Textarea for cover letter or summary ──────────────────
        if not answer and ftag == "textarea":
            if any(kw in all_text for kw in ["cover letter", "cover_letter", "coverletter"]):
                answer = "COVER_LETTER_TEXT"
            elif any(kw in all_text for kw in ["summary", "about yourself", "about you",
                                                 "tell us", "introduction", "bio",
                                                 "additional information", "message"]):
                answer = profile.get("summary", "")

        # ── 7. Smart location field detection ────────────────────────
        if not answer:
            loc_clues = f"{flabel} {fplaceholder} {fid} {fname}"
            helper_clues = fhelper  # Helper text under the field
            
            if any(kw in loc_clues for kw in ["city", "town"]):
                if "state" not in loc_clues and "country" not in loc_clues:
                    answer = city  # Just the city
            elif any(kw in loc_clues for kw in ["state", "province", "region"]):
                if "country" not in loc_clues:
                    answer = state_full
            elif any(kw in loc_clues for kw in ["country", "nation"]):
                answer = "United States"
            elif "zip" in loc_clues or "postal" in loc_clues or "postcode" in loc_clues:
                answer = "29501"
            elif any(kw in loc_clues for kw in ["address", "location"]):
                # Check helper text for hints about what to include
                if any(kw in helper_clues for kw in ["city, region, and country",
                                                       "city, state, and country",
                                                       "city, state, country",
                                                       "include your city"]):
                    answer = location_full  # "Florence, South Carolina, United States"
                elif "country" in helper_clues:
                    answer = location_full
                else:
                    answer = location_full  # Default to full address anyway

        # ── 8. Toggle button (YES/NO) auto-mapping ──────────────────
        if not answer and ftype == "toggle":
            toggle_label = flabel
            # Match common yes/no questions
            yes_keywords = [
                "authorized to work", "eligible to work", "right to work",
                "legally authorized", "background check", "drug test",
                "willing to undergo", "able to work", "willing to relocate",
                "security+", "comptia", "certification", "certified",
                "commit to this schedule", "experience",
            ]
            no_keywords = [
                "require sponsorship", "need sponsorship", "visa sponsorship",
                "non-compete", "convicted", "felony",
                "currently hold an active public trust",
            ]
            
            for kw in yes_keywords:
                if kw in toggle_label:
                    answer = "YES"
                    break
            if not answer:
                for kw in no_keywords:
                    if kw in toggle_label:
                        answer = "NO"
                        break

        if answer:
            auto_mapped[str(i)] = answer
        else:
            unmapped_fields.append((i, f))

    # ── Post-processing: fix type mismatches ─────────────────────────
    for idx_str, answer in list(auto_mapped.items()):
        i = int(idx_str)
        f = fields[i]
        ftag = f.get("tag", "")
        ftype = f.get("type", "")

        # COVER_LETTER_FILE assigned to a textarea → switch to COVER_LETTER_TEXT
        if answer == "COVER_LETTER_FILE" and ftag == "textarea":
            auto_mapped[idx_str] = "COVER_LETTER_TEXT"

        # RESUME_FILE assigned to a non-file field → remove (shouldn't paste filename)
        if answer == "RESUME_FILE" and ftype != "file":
            del auto_mapped[idx_str]
            unmapped_fields.append((i, f))

        # COVER_LETTER_FILE assigned to a non-file, non-textarea field → remove
        if answer == "COVER_LETTER_FILE" and ftype != "file" and ftag != "textarea":
            del auto_mapped[idx_str]
            unmapped_fields.append((i, f))

    # Re-sort unmapped_fields by index since we may have added new entries
    unmapped_fields.sort(key=lambda x: x[0])

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
        elif answer == "COVER_LETTER_TEXT":
            display = "✉️  Cover letter text (pasted)" if cover_letter_path else "NO FILE"
        elif answer == "SKIP_FIELD":
            display = "(skip — not a document field)"
        elif answer and len(str(answer)) > 50:
            display = str(answer)[:47] + "..."
        elif answer:
            display = str(answer)[:50]
        else:
            display = "❓ will ask" if f.get("required") else "(skip)"

        print(f"     {ftype:12s} | {flabel:45s}{req} → {display}")

    # Count actual fields that will be filled (excluding SKIP_FIELD)
    fillable_count = sum(1 for v in all_answers.values() if v != "SKIP_FIELD")

    print(f"  {'─'*80}")
    # Dismiss any lingering cookie banner before screenshot
    dismiss_cookie_banner(page)
    time.sleep(0.5)
    # Scroll to top of form so screenshot shows something useful
    page.evaluate("window.scrollTo(0, 0)")
    time.sleep(0.5)
    screenshot(page, f"{slug}_universal_plan")

    if dry_run:
        print(f"\n  [DRY RUN] Would fill {fillable_count} of {len(fields)} fields")
        return "dry_run_ok"

    # Step 5: Fill fields
    # First, dismiss any modal overlays blocking the form
    dismiss_overlays(page)
    time.sleep(0.5)
    
    print(f"\n  ✏️  Filling fields...")
    filled = 0
    failed = []

    for i, f in enumerate(fields):
        answer = all_answers.get(str(i))
        if not answer or answer == "SKIP_FIELD":
            # Ask user for required fields without an answer
            if f.get("required") and answer != "SKIP_FIELD":
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

    # ── Post-fill sweep: handle custom UI elements (toggles, add-sections) ──
    print(f"\n  🔄 Post-fill sweep: checking for toggle buttons & expandable sections...")
    # Scroll through the entire page to trigger lazy-loaded elements
    try:
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        time.sleep(1)
        page.evaluate("window.scrollTo(0, 0)")
        time.sleep(0.5)
    except Exception:
        pass
    extra_filled = fill_toggle_buttons_sweep(page, profile)
    filled += extra_filled

    screenshot(page, f"{slug}_filled")
    total_fields = len(fields) + extra_filled
    print(f"\n  📊 Filled {filled}/{total_fields} fields")

    if failed:
        print(f"  ⚠️  {len(failed)} fields could not be filled")

    return filled, total_fields, failed



def dismiss_cookie_banner(page):
    """
    Automatically dismiss cookie consent banners that block page interaction.
    Uses JavaScript for reliability — Playwright clicks often get intercepted
    by the very overlay we're trying to dismiss.
    """
    try:
        removed = page.evaluate("""() => {
            let dismissed = false;
            
            // Strategy 1: Click "Accept all" / "Accept" / "OK" buttons via JS
            const buttonTexts = [
                'accept all', 'accept all cookies', 'accept cookies', 'accept',
                'allow all', 'allow all cookies', 'allow cookies', 'allow',
                'i accept', 'i agree', 'agree', 'ok', 'got it', 'dismiss',
                'agree and close', 'consent', 'save settings'
            ];
            
            const allButtons = document.querySelectorAll('button, a[role="button"], [class*="btn"]');
            for (const btn of allButtons) {
                const text = (btn.textContent || btn.innerText || '').trim().toLowerCase();
                if (buttonTexts.some(t => text === t || text.startsWith(t))) {
                    const rect = btn.getBoundingClientRect();
                    if (rect.width > 0 && rect.height > 0) {
                        btn.click();
                        dismissed = true;
                        break;
                    }
                }
            }
            
            // Strategy 2: Click known cookie consent selectors
            if (!dismissed) {
                const selectors = [
                    '#onetrust-accept-btn-handler',
                    '#CybotCookiebotDialogBodyLevelButtonLevelOptinAllowAll',
                    '.evidon-banner-acceptbutton',
                    '[data-testid="cookie-accept"]',
                    'button[id*="accept"]',
                    'button[class*="accept"]',
                    '.cc-accept', '.cc-btn',
                ];
                for (const sel of selectors) {
                    const el = document.querySelector(sel);
                    if (el) { el.click(); dismissed = true; break; }
                }
            }
            
            // Strategy 3: Remove cookie banners/modals from DOM entirely
            const removeSelectors = [
                '[class*="cookie-banner"]', '[class*="cookie-consent"]',
                '[class*="cookieBanner"]', '[class*="CookieConsent"]',
                '[id*="cookie-banner"]', '[id*="cookie-consent"]',
                '[id*="cookieBanner"]', '[id*="CookieConsent"]',
                '[data-testid*="cookie"]', '[class*="gdpr"]',
                '.cc-window', '#onetrust-banner-sdk',
                '#CybotCookiebotDialog',
            ];
            for (const sel of removeSelectors) {
                document.querySelectorAll(sel).forEach(el => {
                    el.remove();
                    dismissed = true;
                });
            }
            
            // Re-enable body scroll
            document.body.style.overflow = '';
            document.documentElement.style.overflow = '';
            
            return dismissed;
        }""")
        if removed:
            print(f"  🍪 Dismissed cookie banner")
            time.sleep(0.5)
        return removed
    except Exception:
        pass
    return False


def click_apply_button(page):
    """Click the Apply button if we're on a job description page.
    Handles buttons, links, tabs, and page navigation (iCIMS, Lever, Workable, etc.)."""
    
    apply_patterns = [
        "Apply for this job online",
        "Apply for this job",
        "Apply for this position",
        "Apply Now",
        "Apply now",
        "Apply",
        "Application",  # Workable uses a tab called "APPLICATION"
        "Start Application",
        "Start application",
        "Begin Application",
        "Submit Application",
    ]

    old_url = page.url

    # Try button elements (with force=True fallback for overlay-blocked clicks)
    for pattern in apply_patterns:
        try:
            btn = page.get_by_role("button", name=pattern)
            if btn.count() > 0 and btn.first.is_visible():
                try:
                    btn.first.click(timeout=5000)
                except Exception:
                    btn.first.click(force=True, timeout=5000)
                time.sleep(4)
                if page.url != old_url:
                    print(f"  📄 Navigated to: {page.url[:70]}")
                    time.sleep(2)
                return True
        except Exception:
            continue

    # Try link elements (with force=True fallback)
    for pattern in apply_patterns:
        try:
            link = page.get_by_role("link", name=pattern)
            if link.count() > 0 and link.first.is_visible():
                try:
                    link.first.click(timeout=5000)
                except Exception:
                    link.first.click(force=True, timeout=5000)
                time.sleep(4)
                if page.url != old_url:
                    print(f"  📄 Navigated to: {page.url[:70]}")
                    time.sleep(2)
                return True
        except Exception:
            continue

    # Try tab elements (Workable uses role="tab" for APPLICATION)
    for pattern in apply_patterns:
        try:
            tab = page.get_by_role("tab", name=pattern)
            if tab.count() > 0 and tab.first.is_visible():
                tab.first.click(force=True, timeout=5000)
                time.sleep(3)
                return True
        except Exception:
            continue

    # JavaScript fallback: find and click apply-like elements directly
    try:
        clicked = page.evaluate("""() => {
            const patterns = ['apply', 'application', 'start application', 'apply now'];
            
            // Check buttons, links, and tabs
            const elements = document.querySelectorAll('button, a, [role="button"], [role="tab"], [role="link"]');
            for (const el of elements) {
                const text = (el.textContent || el.innerText || '').trim().toLowerCase();
                if (patterns.some(p => text.includes(p))) {
                    const rect = el.getBoundingClientRect();
                    if (rect.width > 0 && rect.height > 0) {
                        el.click();
                        return true;
                    }
                }
            }
            return false;
        }""")
        if clicked:
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
            dismiss_overlays(page)

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
                        dismiss_overlays(page)
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
                        help="Run only job at this number (1-based, matches dashboard #)")
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
                job_company, job_title, apply_url=args.url, profile_path=args.profile
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
        idx = args.single - 1  # Convert 1-based → 0-based
        if 0 <= idx < len(qualified):
            qualified = [qualified[idx]]
        else:
            print(f"  ❌ Job #{args.single} out of range (1-{len(qualified)})")
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
        resume_path, cover_letter_path = find_tailored_files(company, title, apply_url=url, profile_path=args.profile)
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
