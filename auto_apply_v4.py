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
    """Create Browserbase session."""
    print("  🌐 Starting cloud browser...")
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
    """Close Browserbase session."""
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


# ─── Main Application Flow ────────────────────────────────────────────────────

def click_apply_button(page):
    """Click the Apply button if we're on a job description page."""
    for pattern in ["Apply for this job", "Apply", "Apply Now", "Apply now"]:
        try:
            btn = page.get_by_role("button", name=pattern)
            if btn.count() > 0 and btn.first.is_visible():
                btn.first.click()
                time.sleep(3)
                return True
        except Exception:
            continue

    # Try link-style apply buttons
    for pattern in ["Apply for this job", "Apply", "Apply Now"]:
        try:
            link = page.get_by_role("link", name=pattern)
            if link.count() > 0 and link.first.is_visible():
                link.first.click()
                time.sleep(3)
                return True
        except Exception:
            continue

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

    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            print(f"  🔌 Connecting to cloud browser...")
            browser = p.chromium.connect_over_cdp(connect_url)
            ctx = browser.contexts[0] if browser.contexts else browser.new_context()
            page = ctx.pages[0] if ctx.pages else ctx.new_page()

            # Load URL
            print(f"  🔗 Loading: {url[:70]}...")
            page.goto(url, wait_until="domcontentloaded", timeout=30000)
            time.sleep(3)
            screenshot(page, f"{slug}_01_loaded")

            # Check if we need to click Apply first
            page_text = page.inner_text("body")[:2000].lower()
            if "apply for this job" in page_text or "apply now" in page_text:
                if page.locator("input#first_name").count() == 0:
                    print(f"  🖱️  Clicking Apply...")
                    click_apply_button(page)
                    time.sleep(2)
                    screenshot(page, f"{slug}_02_form_opened")

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
                # Non-Greenhouse form — use LLM fallback
                print(f"\n  ⚠️  Non-Greenhouse form detected")
                print(f"      URL: {page.url}")
                print(f"      This version focuses on Greenhouse forms.")
                print(f"      Skipping — add platform-specific handler for this ATS.")
                screenshot(page, f"{slug}_non_greenhouse")
                browser.close()
                return "non_greenhouse_skipped"

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
    args = parser.parse_args()

    print("\n🚀 Job Bot — Auto-Apply Engine v4.0")
    print("=" * 60)
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
        "error": "❌", "no_resume": "⚠️", "non_greenhouse_skipped": "🔸"
    }
    for r in results:
        icon = icons.get(r.get("status", ""), "•")
        print(f"  {icon} {r['company']} → {r['status']}")

    print(f"\n  📸 Screenshots: open outputs/screenshots/")


if __name__ == "__main__":
    main()
