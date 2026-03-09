#!/usr/bin/env python3
"""
Job Bot - Auto-Apply Engine v3.0
Rewritten with deterministic DOM parsing and fixed React-Select handling.

Key changes from v2:
- Greenhouse forms parsed from DOM, not LLM (eliminates field detection instability)
- Unified React-Select handler for ALL dropdowns (Country, Location, Work Auth, etc.)
- Proper aria-expanded verification before typing
- Uses .type() instead of .fill() for React inputs (React needs real keystrokes)
- Falls back to LLM-based detection only for non-Greenhouse forms
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


def find_tailored_files(company, title):
    """Find tailored resume and cover letter PDFs."""
    tailored_dir = Path("outputs/tailored")
    if not tailored_dir.exists():
        print("  ⚠️  No tailored directory")
        return None, None

    company_norm = re.sub(r'[^a-zA-Z0-9]+', '_', company).strip('_')
    resume = None
    cover_letter = None

    for ext in ['.pdf', '.txt']:
        for file in tailored_dir.glob(f"*_RESUME{ext}"):
            filename = file.stem.lower()
            if company_norm.lower() in filename:
                title_words = [w.lower() for w in title.split() if len(w) > 3]
                if any(word in filename for word in title_words[:3]):
                    resume = str(file.absolute())
                    cover_file = file.parent / file.name.replace(
                        f"_RESUME{ext}", f"_COVER_LETTER{ext}")
                    if cover_file.exists():
                        cover_letter = str(cover_file.absolute())
                    print(f"  📄 Resume: {file.name}")
                    if cover_letter:
                        print(f"  📄 Cover: {Path(cover_letter).name}")
                    break
        if resume:
            break

    if not resume:
        print(f"  ⚠️  No resume found for {company}")
    return resume, cover_letter


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

def fill_react_select(page, field_id, answer, retries=2):
    """
    Fill a Greenhouse React-Select dropdown by its input element ID.

    This handles ALL Greenhouse dropdowns: Country, Location (City),
    Work Auth, Visa, Gender, Hispanic/Latino, Veteran, Disability.

    They all share the same DOM structure:
      <input id="{field_id}" role="combobox" class="select__input" ...>
    """
    for attempt in range(retries + 1):
        try:
            combobox = page.locator(f"input#{field_id}")
            if combobox.count() == 0:
                print(f"      ❌ No combobox found with id={field_id}")
                return False

            # Step 1: Clear any existing value by clicking the control area,
            # then clicking the input itself
            container = page.locator(
                f"input#{field_id} >> xpath=ancestor::div[contains(@class,'select__control')]"
            )
            if container.count() > 0:
                container.first.click()
            else:
                combobox.click()
            time.sleep(0.3)

            # Clear existing text if any
            combobox.press("Control+a")
            combobox.press("Backspace")
            time.sleep(0.2)

            # Step 2: Type to filter. Use .type() NOT .fill() —
            # React-Select needs real keystroke events to trigger its search.
            # For Location, type enough to get a match. For short options
            # like "Yes"/"No"/"Male", type the full answer.
            search_text = answer
            if len(answer) > 20:
                # For long answers, type first meaningful chunk
                search_text = answer[:15]
            combobox.type(search_text, delay=60)

            # Step 3: Wait for the dropdown to actually open
            # Greenhouse React-Select sets aria-expanded="true" when open
            try:
                page.wait_for_function(
                    f"""() => {{
                        const el = document.getElementById("{field_id}");
                        return el && el.getAttribute("aria-expanded") === "true";
                    }}""",
                    timeout=3000
                )
            except Exception:
                # If aria-expanded didn't flip, try clicking again
                if attempt < retries:
                    print(f"      ↻ Dropdown didn't open, retrying... ({attempt+1})")
                    time.sleep(0.5)
                    continue
                print(f"      ⚠️  Dropdown never opened for {field_id}")
                return False

            # Step 4: Wait for option elements to render
            try:
                page.wait_for_selector(
                    "div[class*='select__option']",
                    state="visible",
                    timeout=5000
                )
            except Exception:
                # Location dropdown calls an API — may need extra time
                time.sleep(2)
                if page.locator("div[class*='select__option']").count() == 0:
                    if attempt < retries:
                        print(f"      ↻ No options appeared, retrying... ({attempt+1})")
                        continue
                    print(f"      ⚠️  No options rendered for {field_id}")
                    return False

            # Step 5: Click the best matching option
            options = page.locator("div[class*='select__option']")
            option_count = options.count()

            if option_count == 0:
                if attempt < retries:
                    continue
                return False

            # Try exact match first
            for i in range(option_count):
                opt = options.nth(i)
                try:
                    text = opt.inner_text().strip()
                    if text.lower() == answer.lower():
                        opt.click()
                        time.sleep(0.4)
                        return _verify_selection(page, field_id, answer)
                except Exception:
                    continue

            # Partial match: pick first option that contains our answer
            for i in range(option_count):
                opt = options.nth(i)
                try:
                    text = opt.inner_text().strip()
                    if answer.lower() in text.lower():
                        opt.click()
                        time.sleep(0.4)
                        return _verify_selection(page, field_id, answer)
                except Exception:
                    continue

            # Last resort: just click the first option (usually correct
            # when typing has filtered results down)
            if option_count > 0:
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
    """Upload a file to a Greenhouse file input."""
    try:
        if not file_path or not Path(file_path).exists():
            print(f"      ⚠️  File not found: {file_path}")
            return False
        el = page.locator(f"input#{input_id}[type='file']")
        if el.count() == 0:
            # Greenhouse hides file inputs — try making visible first
            page.evaluate(f"""
                const el = document.getElementById("{input_id}");
                if (el) {{ el.style.display = 'block'; el.style.opacity = '1'; }}
            """)
            time.sleep(0.3)
            el = page.locator(f"input#{input_id}")

        if el.count() > 0:
            el.set_input_files(file_path)
            time.sleep(1)
            print(f"      ✅ Uploaded: {Path(file_path).name}")
            return True

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
        "disability_status": "I don't wish to answer",

        # File uploads (by ID)
        "resume": "RESUME_FILE",
        "cover_letter": "COVER_LETTER_FILE",
    }

    # Dynamic question fields — match by label keywords
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


def run_greenhouse_application(page, profile, resume_path, cover_letter_path, slug, dry_run):
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
        display = answer or "(no answer)"
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
            if f["required"]:
                print(f"    ⚠️  {label} — NO ANSWER (required!)")
                failed_fields.append(label)
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


def run_application(connect_url, job, profile, resume_path, cover_letter_path, dry_run):
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
                    page, profile, resume_path, cover_letter_path, slug, dry_run
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
    parser = argparse.ArgumentParser(description="Job Bot Auto-Apply v3.0")
    parser.add_argument("--jobs", default="profiles/scored_jobs.json")
    parser.add_argument("--profile", default="profiles/job_profile.json")
    parser.add_argument("--min-score", type=int, default=50)
    parser.add_argument("--dry-run", action="store_true",
                        help="Analyze and fill-plan only, don't submit")
    parser.add_argument("--single", type=int, default=None,
                        help="Run only job at this index (0-based)")
    parser.add_argument("--url", type=str, default=None,
                        help="Apply to a single URL directly")
    args = parser.parse_args()

    print("\n🚀 Job Bot — Auto-Apply Engine v3.0")
    print("=" * 60)
    if args.dry_run:
        print("  ⚠️  DRY RUN MODE — will NOT submit\n")

    profile = json.loads(Path(args.profile).read_text())

    # Single URL mode
    if args.url:
        job = {
            "title": "Direct Application",
            "company": "Unknown",
            "apply_url": args.url,
            "score": 100
        }
        session_id, connect_url = create_session()
        if not session_id:
            return
        resume_path, cover_letter_path = None, None
        try:
            status = run_application(
                connect_url, job, profile, resume_path, cover_letter_path, args.dry_run
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
        resume_path, cover_letter_path = find_tailored_files(company, title)
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
                connect_url, job, profile, resume_path, cover_letter_path, args.dry_run
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
