"""Application orchestration: Greenhouse + universal form filling."""

from __future__ import annotations

import logging
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

from job_bot.config import OPENROUTER_API_KEY
from job_bot.browser import (
    detect_ats_platform, get_session_path, has_saved_session,
    save_browser_session, screenshot, dismiss_cookie_banner, dismiss_overlays,
)
from job_bot.utils import build_location_strings, _normalize_field_id

logger = logging.getLogger(__name__)
from job_bot.profile import (
    build_answer_map, resolve_answer, prompt_for_answer, save_answer_to_profile,
)
from job_bot.fields import (
    EXTRACT_FIELDS_JS, extract_page_fields, is_greenhouse_form,
    parse_greenhouse_fields, claude_map_fields,
)
from job_bot.react_select import fill_react_select
from job_bot.form_filler import (
    fill_text_field, upload_file, fill_generic_field,
    fill_toggle_buttons_sweep, fill_dropdowns_sweep,
    fix_country_react_select, fix_paylocity_react_selects,
    fix_email_validation, prescan_page_with_scrapling,
)


@dataclass
class ApplicationResult:
    """Standardized result from any application attempt."""
    status: str  # "submitted", "dry_run_ok", "user_skipped", "no_form_found", "error"
    filled: int = 0
    total: int = 0
    failed_fields: list = field(default_factory=list)


def click_apply_button(page) -> bool:
    """Click the Apply button if we're on a job description page."""
    apply_patterns = [
        "Apply for this job online",
        "Apply for this job",
        "Apply for this position",
        "Apply Now",
        "Apply now",
        "Apply",
        "Application",
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
                try:
                    btn.first.click(timeout=5000)
                except Exception:
                    btn.first.click(force=True, timeout=5000)
                time.sleep(4)
                if page.url != old_url:
                    print(f"  >> Navigated to: {page.url[:70]}")
                    time.sleep(2)
                return True
        except Exception:
            continue

    # Try link elements
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
                    print(f"  >> Navigated to: {page.url[:70]}")
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

    # JavaScript fallback
    try:
        clicked = page.evaluate("""() => {
            const patterns = ['apply', 'application', 'start application', 'apply now'];
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
                print(f"  >> Navigated to: {page.url[:70]}")
                time.sleep(2)
            return True
    except Exception:
        pass

    return False


def _extract_fields_with_iframes(page, fields_js: str) -> list[dict]:
    """Extract fields from main page and iframes."""
    fields = extract_page_fields(page)

    if not fields:
        for frame in page.frames[1:]:
            try:
                frame_fields = frame.evaluate(fields_js)
                frame_fields = [f for f in frame_fields if f.get("label") or f.get("id") or f.get("name")]
                if len(frame_fields) > len(fields):
                    fields = frame_fields
                    print(f"  >> Found {len(fields)} fields inside iframe")
            except Exception:
                continue

    return fields


def run_greenhouse_application(page, profile: dict, profile_path: str, resume_path: str | None, cover_letter_path: str | None, slug: str, dry_run: bool) -> ApplicationResult:
    """
    Fill a Greenhouse application form using deterministic DOM parsing.
    No LLM calls needed.
    """
    print("\n  >> Greenhouse form detected -- using deterministic DOM parser")

    fields = parse_greenhouse_fields(page)
    print(f"  >> Found {len(fields)} fields from DOM")

    answers_by_id, answers_by_label = build_answer_map(profile, slug)

    # Show fill plan
    print(f"\n  Fill plan:")
    for f in fields:
        answer = resolve_answer(f, answers_by_id, answers_by_label)
        display = answer or ("? will ask" if f["required"] else "(no answer)")
        if answer == "RESUME_FILE":
            display = f"[resume] {Path(resume_path).name}" if resume_path else "NO FILE"
        elif answer == "COVER_LETTER_FILE":
            display = f"[cover] {Path(cover_letter_path).name}" if cover_letter_path else "NO FILE"
        req = "*" if f["required"] else ""
        print(f"     {f['type']:14s} | {f['label'][:45]:45s}{req} -> {str(display)[:50]}")
    print(f"  {'~'*80}")

    if dry_run:
        screenshot(page, f"{slug}_dryrun_preview")
        print(f"\n  [DRY RUN] Would fill {len(fields)} fields")
        return ApplicationResult(status="dry_run_ok", total=len(fields))

    # Fill each field
    print(f"\n  Filling fields...")
    filled_count = 0
    failed_fields = []

    for f in fields:
        field_id = f["id"]
        field_type = f["type"]
        label = f["label"]
        answer = resolve_answer(f, answers_by_id, answers_by_label)

        if not answer:
            if f["required"] or f["type"] == "react-select":
                answer = prompt_for_answer(f)
                if answer:
                    save_answer_to_profile(profile, profile_path, label, answer)
                    answers_by_label[label.lower()] = answer
                else:
                    if f["required"]:
                        print(f"    !! {label} -- SKIPPED (required!)")
                        failed_fields.append(label)
                    continue
            else:
                continue

        if answer == "RESUME_FILE" and not resume_path:
            continue
        if answer == "COVER_LETTER_FILE" and not cover_letter_path:
            continue

        print(f"    -> {label[:50]}...", end=" ")

        success = False

        if field_type == "file":
            file_path = resume_path if answer == "RESUME_FILE" else cover_letter_path
            success = upload_file(page, field_id, file_path)
        elif field_type == "react-select":
            success = fill_react_select(page, field_id, answer)
        elif field_type in ("text", "tel"):
            success = fill_text_field(page, field_id, answer)

        if success:
            print(f"OK")
            filled_count += 1
        else:
            print(f"FAIL")
            failed_fields.append(label)

        time.sleep(0.3)

    screenshot(page, f"{slug}_filled")

    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
    time.sleep(1)
    screenshot(page, f"{slug}_filled_bottom")

    total = len([f for f in fields if resolve_answer(f, answers_by_id, answers_by_label)])
    print(f"\n  Results: {filled_count}/{total} fields filled")
    if failed_fields:
        print(f"  !! Failed: {', '.join(failed_fields)}")

    return ApplicationResult(
        status="filled",
        filled=filled_count,
        total=total,
        failed_fields=failed_fields,
    )


def run_universal_application(page, job: dict, profile: dict, profile_path: str, resume_path: str | None,
                               cover_letter_path: str | None, slug: str, dry_run: bool,
                               browser_ctx=None, platform: str = "unknown") -> ApplicationResult:
    """
    Fill a job application form on ANY website using AI-assisted field mapping.
    """
    print(f"\n  >> Universal form filler -- analyzing page...")

    # Step 1: Extract all form fields
    fields = _extract_fields_with_iframes(page, EXTRACT_FIELDS_JS)

    # Filter out navigation-only fields
    NAV_KEYWORDS = ["search", "filter", "sort", "region", "language", "locale", "country-selector"]
    meaningful = [f for f in fields if not any(
        kw in (f.get("label", "") + f.get("id", "") + f.get("name", "")).lower()
        for kw in NAV_KEYWORDS
    )]
    if len(meaningful) < 3 and len(fields) <= 5:
        fields = []

    if not fields:
        print(f"\n  >> No form fields yet -- trying to find and click Apply button...")
        dismiss_cookie_banner(page)
        dismiss_overlays(page)
        time.sleep(1)

        clicked = click_apply_button(page)
        if clicked:
            time.sleep(4)
            for _ in range(3):
                dismissed = dismiss_cookie_banner(page)
                if not dismissed:
                    break
                time.sleep(1.5)

            try:
                close_btn = page.locator("[aria-label='Close'], button.close, .modal-close, [class*='cookie'] [class*='close']")
                if close_btn.count() > 0 and close_btn.first.is_visible():
                    close_btn.first.click()
                    time.sleep(1)
            except Exception:
                pass

            time.sleep(1)
            screenshot(page, f"{slug}_02_after_apply_click")
            fields = _extract_fields_with_iframes(page, EXTRACT_FIELDS_JS)
            if fields:
                print(f"  >> Found {len(fields)} fields after clicking Apply")

    if not fields:
        print(f"\n  !! No form fields found yet.")
        print(f"     Current page: {page.url[:70]}")
        print(f"\n  The application form might require you to:")
        print(f"    - Log in or create an account")
        print(f"    - Solve a CAPTCHA")
        print(f"    - Navigate to the form manually")
        print(f"\n  Use the browser to get to the actual application FORM.")

        user_input = input("\n  Press Enter when on the form (or SKIP): ").strip()
        if user_input.upper() == "SKIP":
            return ApplicationResult(status="user_skipped")

        if browser_ctx and platform != "unknown":
            save_browser_session(browser_ctx, platform)

        time.sleep(2)
        fields = _extract_fields_with_iframes(page, EXTRACT_FIELDS_JS)

        if not fields:
            print(f"  !! Still no form fields found. Skipping this job.")
            screenshot(page, f"{slug}_no_fields")
            return ApplicationResult(status="no_form_found")

    print(f"  >> Found {len(fields)} form fields")

    # Step 2: Auto-map using profile answer map
    answers_by_id, answers_by_label = build_answer_map(profile, slug)
    auto_mapped = {}
    unmapped_fields = []

    loc = build_location_strings(profile)
    city = loc["city"]
    state_full = loc["state_full"]
    location_full = loc["location_full"]
    zip_code = loc["zip_code"]

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
        all_text = f" {fid} {fname} {flabel} {fplaceholder} {fhelper} "

        answer = None

        # 1. Direct ID/name exact match
        for key, val in answers_by_id.items():
            if key == fid or key == fname:
                answer = val
                break

        # 2. ID/name fuzzy match (word-boundary-aware normalization)
        if not answer:
            fid_norm = _normalize_field_id(fid)
            fname_norm = _normalize_field_id(fname)
            for key, val in answers_by_id.items():
                key_norm = _normalize_field_id(key)
                if key_norm and (key_norm == fid_norm or key_norm == fname_norm):
                    answer = val
                    break

        # 3. Label keyword match
        if not answer:
            for key, val in answers_by_label.items():
                if key in flabel:
                    answer = val
                    break

        # 4. Placeholder/name keyword match
        if not answer and not flabel:
            for key, val in answers_by_label.items():
                if key in fplaceholder or key in fname.replace("_", " ").replace("-", " "):
                    answer = val
                    break

        # 5. Smart file field detection
        if not answer and ftype == "file":
            file_clues = f"{flabel} {fid} {fname} {parent_class} {section}"
            if any(kw in file_clues for kw in ["photo", "headshot", "avatar",
                                                 "picture", "profile pic", "image"]):
                answer = "SKIP_FIELD"
            elif any(kw in file_clues for kw in ["resume", "cv", "curriculum"]):
                answer = "RESUME_FILE"
            elif any(kw in file_clues for kw in ["cover", "letter", "motivation"]):
                answer = "COVER_LETTER_FILE"
            else:
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

        # 6. Textarea for cover letter or summary
        if not answer and ftag == "textarea":
            if any(kw in all_text for kw in ["cover letter", "cover_letter", "coverletter"]):
                answer = "COVER_LETTER_TEXT"
            elif any(kw in all_text for kw in ["summary", "about yourself", "about you",
                                                 "tell us", "introduction", "bio",
                                                 "additional information", "message"]):
                answer = profile.get("summary", "")

        # 7. Smart location field detection
        if not answer:
            loc_clues = f"{flabel} {fplaceholder} {fid} {fname}"
            helper_clues = fhelper
            street_address = profile["personal"].get("street_address", "")
            county = profile["personal"].get("county", city)

            if "address line" in loc_clues or "street" in loc_clues:
                if "2" in loc_clues or "apt" in loc_clues or "suite" in loc_clues:
                    answer = ""  # Address Line 2 — leave blank unless user has apt/suite
                else:
                    answer = street_address
            elif "county" in loc_clues and "country" not in loc_clues:
                answer = county
            elif any(kw in loc_clues for kw in ["country", "nation"]):
                answer = "United States"
            elif any(kw in loc_clues for kw in ["city", "town"]):
                if "state" not in loc_clues and "country" not in loc_clues:
                    answer = city
            elif any(kw in loc_clues for kw in ["state", "province", "region"]):
                if "country" not in loc_clues:
                    answer = state_full
            elif "zip" in loc_clues or "postal" in loc_clues or "postcode" in loc_clues:
                answer = zip_code
            elif any(kw in loc_clues for kw in ["address", "location"]):
                answer = street_address or location_full

        # 8. Toggle button auto-mapping
        if not answer and ftype == "toggle":
            toggle_label = flabel
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

    # Post-processing: fix type mismatches
    for idx_str, answer in list(auto_mapped.items()):
        idx = int(idx_str)
        f = fields[idx]
        ftag = f.get("tag", "")
        ftype = f.get("type", "")

        if answer == "COVER_LETTER_FILE" and ftag == "textarea":
            auto_mapped[idx_str] = "COVER_LETTER_TEXT"
        if answer == "RESUME_FILE" and ftype != "file":
            del auto_mapped[idx_str]
            unmapped_fields.append((idx, f))
        if answer == "COVER_LETTER_FILE" and ftype != "file" and ftag != "textarea":
            del auto_mapped[idx_str]
            unmapped_fields.append((idx, f))

    unmapped_fields.sort(key=lambda x: x[0])
    print(f"  >> Auto-mapped: {len(auto_mapped)} | Unmapped: {len(unmapped_fields)}")

    # Step 3: Ask Claude to map remaining fields
    claude_mapped = {}
    if unmapped_fields and OPENROUTER_API_KEY:
        print(f"  >> Asking Claude to map {len(unmapped_fields)} remaining fields...")
        unmapped_for_claude = [f for _, f in unmapped_fields]
        raw_mapping = claude_map_fields(unmapped_for_claude, profile, job)

        for local_idx_str, answer in raw_mapping.items():
            try:
                local_idx = int(local_idx_str)
                if 0 <= local_idx < len(unmapped_fields):
                    global_idx = unmapped_fields[local_idx][0]
                    claude_mapped[str(global_idx)] = answer
            except (ValueError, IndexError):
                continue

        print(f"  >> Claude mapped {len(claude_mapped)} additional fields")

    # Merge all mappings
    all_answers = {}
    all_answers.update(auto_mapped)
    all_answers.update(claude_mapped)

    # Step 4: Show fill plan
    print(f"\n  Fill plan ({len(all_answers)}/{len(fields)} fields):")
    for i, f in enumerate(fields):
        answer = all_answers.get(str(i))
        ftype = f.get("type", "?")[:12]
        flabel = f.get("label", f.get("name", "unknown"))[:45]
        req = "*" if f.get("required") else " "

        if answer == "RESUME_FILE":
            display = "[resume] {}".format(Path(resume_path).name) if resume_path else "NO FILE"
        elif answer == "COVER_LETTER_FILE":
            display = "[cover] {}".format(Path(cover_letter_path).name) if cover_letter_path else "NO FILE"
        elif answer == "COVER_LETTER_TEXT":
            display = "Cover letter text (pasted)" if cover_letter_path else "NO FILE"
        elif answer == "SKIP_FIELD":
            display = "(skip -- not a document field)"
        elif answer and len(str(answer)) > 50:
            display = str(answer)[:47] + "..."
        elif answer:
            display = str(answer)[:50]
        else:
            display = "? will ask" if f.get("required") else "(skip)"

        print(f"     {ftype:12s} | {flabel:45s}{req} -> {display}")

    fillable_count = sum(1 for v in all_answers.values() if v != "SKIP_FIELD")

    print(f"  {'~'*80}")
    dismiss_cookie_banner(page)
    time.sleep(0.5)
    page.evaluate("window.scrollTo(0, 0)")
    time.sleep(0.5)
    screenshot(page, f"{slug}_universal_plan")

    if dry_run:
        print(f"\n  [DRY RUN] Would fill {fillable_count} of {len(fields)} fields")
        return ApplicationResult(status="dry_run_ok", total=len(fields))

    # Step 5: Fill fields
    # DO NOT dismiss_overlays here — the page may have a resume upload modal
    # that contains file inputs.  File uploads must happen FIRST so the modal
    # dismisses itself naturally.  We dismiss non-form overlays AFTER uploads.

    print(f"\n  Filling fields...")
    filled = 0
    failed = []

    # Phase A: Upload files first (resume / cover letter).
    # These may be inside a modal dialog that dismiss_overlays would destroy.
    file_indices = []
    for i, f in enumerate(fields):
        answer = all_answers.get(str(i))
        if answer in ("RESUME_FILE", "COVER_LETTER_FILE"):
            file_indices.append(i)
            success = fill_generic_field(page, f, answer, resume_path, cover_letter_path)
            if success:
                filled += 1
                label = f.get("label", f.get("name", ""))[:40]
                print(f"     >> {label}")
            else:
                failed.append(f)
                label = f.get("label", f.get("name", ""))[:40]
                print(f"     !! {label}")
            time.sleep(1)  # Let the page process the upload

    # After file uploads, wait for any modal to close and the form to populate
    if file_indices:
        time.sleep(2)
        print(f"  >> File uploads done, waiting for form to populate...")
        time.sleep(3)

    # Dismiss cookie banners and non-form overlays that may have (re)appeared
    dismiss_cookie_banner(page)
    time.sleep(0.3)
    dismiss_overlays(page)
    time.sleep(0.5)

    # Pre-scan the page with scrapling to detect pre-filled react-selects
    # and other component structures before any interaction.
    # This must happen AFTER file uploads since resume upload may auto-fill fields.
    prescan = prescan_page_with_scrapling(page)

    # Fix Country react-select if resume parser flipped it (e.g. to Seychelles).
    # Must run before Phase B so the form shows US address fields.
    if fix_country_react_select(page):
        # Re-scan since the form layout may have changed (US vs international)
        prescan = prescan_page_with_scrapling(page)

    # Phase B: Fill remaining (non-file) fields
    for i, f in enumerate(fields):
        if i in file_indices:
            continue  # already handled in Phase A

        answer = all_answers.get(str(i))
        if not answer or answer == "SKIP_FIELD":
            if f.get("required") and answer != "SKIP_FIELD":
                label = f.get("label", f.get("name", "unknown field"))
                user_answer = input(f"\n  ? {label}: ").strip()
                if user_answer:
                    answer = user_answer
                    save_answer_to_profile(profile, profile_path, label, user_answer)
                else:
                    continue
            else:
                continue

        # Dismiss any modals that may have appeared during filling
        if i > 0 and i % 5 == 0:
            dismiss_overlays(page)
            time.sleep(0.2)

        success = fill_generic_field(page, f, answer, resume_path, cover_letter_path, prescan=prescan)
        if success:
            filled += 1
            label = f.get("label", f.get("name", ""))[:40]
            print(f"     >> {label}")
        else:
            failed.append(f)
            label = f.get("label", f.get("name", ""))[:40]
            print(f"     !! {label}")

        time.sleep(0.3)

    # Post-fill sweep for toggle buttons and dropdowns
    print(f"\n  >> Post-fill sweep: checking for toggle buttons, dropdowns & expandable sections...")
    try:
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        time.sleep(1)
        page.evaluate("window.scrollTo(0, 0)")
        time.sleep(0.5)
    except Exception:
        pass
    extra_filled = fill_toggle_buttons_sweep(page, profile)
    filled += extra_filled

    extra_dropdowns = fill_dropdowns_sweep(page, profile)
    filled += extra_dropdowns

    # Fix Paylocity react-selects (Country, State) that the fill loop
    # couldn't set via normal click/type/Enter — uses React fiber onChange.
    fix_paylocity_react_selects(page, profile)

    # Fix sticky email validation error (must run LAST — after all other
    # fills and react-select fixes so no re-renders can undo it).
    email_val = profile.get("personal", {}).get("email", profile.get("email", ""))
    if email_val:
        fix_email_validation(page, email_val)

    screenshot(page, f"{slug}_filled")
    total_fields = len(fields) + extra_filled
    print(f"\n  Results: {filled}/{total_fields} fields filled")

    if failed:
        print(f"  !! {len(failed)} fields could not be filled")

    # ── Post-fill verification: re-read fields and check for errors ──
    print(f"\n  >> Post-fill verification...")
    try:
        page.evaluate("window.scrollTo(0, 0)")
        time.sleep(0.5)
        verify_issues = page.evaluate("""() => {
            const issues = [];
            // Check for validation error messages
            const errorSels = [
                '[class*="error"]', '[class*="invalid"]',
                '[class*="validation"]', '[role="alert"]',
                '.field-error', '.input-error', '.form-error',
            ];
            for (const sel of errorSels) {
                for (const el of document.querySelectorAll(sel)) {
                    const text = (el.textContent || '').trim();
                    const rect = el.getBoundingClientRect();
                    if (text && text.length > 3 && text.length < 200
                        && rect.width > 0 && rect.height > 0) {
                        // Find which field this error belongs to
                        let fieldLabel = '';
                        let parent = el.parentElement;
                        for (let i = 0; i < 5 && parent; i++) {
                            const lbl = parent.querySelector('label');
                            if (lbl) { fieldLabel = lbl.textContent.trim(); break; }
                            parent = parent.parentElement;
                        }
                        issues.push({
                            type: 'validation_error',
                            field: fieldLabel.slice(0, 50),
                            message: text.slice(0, 100),
                        });
                    }
                }
            }
            // Check for required empty fields
            const required = document.querySelectorAll(
                'input[required], select[required], textarea[required], '
                + '[aria-required="true"]');
            for (const inp of required) {
                if (!inp.value || inp.value.trim() === '') {
                    let lbl = '';
                    if (inp.id) {
                        const l = document.querySelector('label[for="' + inp.id + '"]');
                        if (l) lbl = l.textContent.trim();
                    }
                    if (!lbl) lbl = inp.placeholder || inp.name || inp.id || '';
                    issues.push({
                        type: 'empty_required',
                        field: lbl.slice(0, 50),
                        message: 'Required field is empty',
                    });
                }
            }
            return issues;
        }""")

        if verify_issues:
            seen = set()
            unique_issues = []
            for issue in verify_issues:
                key = f"{issue['field']}|{issue['message']}"
                if key not in seen:
                    seen.add(key)
                    unique_issues.append(issue)
            print(f"  !! Found {len(unique_issues)} issue(s):")
            for issue in unique_issues:
                # Use ASCII fallback if terminal can't handle unicode
                try:
                    icon = "\u26a0" if issue['type'] == 'validation_error' else "\u25cb"
                    icon.encode(sys.stdout.encoding or 'utf-8')
                except (UnicodeEncodeError, LookupError):
                    icon = "!" if issue['type'] == 'validation_error' else "o"
                field = issue['field'] or '(unknown field)'
                print(f"     {icon} {field}: {issue['message']}")
        else:
            print(f"  >> No validation errors detected")

    except Exception as e:
        print(f"  >> Verification check failed: {e}")

    return ApplicationResult(
        status="filled",
        filled=filled,
        total=total_fields,
        failed_fields=[f.get("label", "") for f in failed],
    )


def run_application(job: dict, profile: dict, profile_path: str, resume_path: str | None,
                    cover_letter_path: str | None, dry_run: bool) -> ApplicationResult:
    """Run the full application flow for a single job."""
    title = job.get("title", "")
    company = job.get("company", "")
    url = job.get("apply_url", "")
    slug = re.sub(r'[^a-zA-Z0-9]+', '_', company).strip('_')

    platform = detect_ats_platform(url)
    session_path = get_session_path(platform)
    has_session = has_saved_session(platform)

    if platform != "unknown" and has_session:
        print(f"  >> Found saved session for {platform}")

    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            print(f"  >> Launching local browser...")
            browser = p.chromium.launch(headless=False)

            if has_session:
                try:
                    ctx = browser.new_context(storage_state=str(session_path))
                    print(f"  >> Loaded saved {platform} session")
                except Exception:
                    ctx = browser.new_context()
            else:
                ctx = browser.new_context()

            page = ctx.new_page()

            print(f"  >> Loading: {url[:70]}...")
            page.goto(url, wait_until="domcontentloaded", timeout=30000)
            time.sleep(3)

            dismiss_cookie_banner(page)
            dismiss_overlays(page)
            screenshot(page, f"{slug}_01_loaded")

            # Check if we need to click Apply first
            has_form_fields = page.locator("input:visible, select:visible, textarea:visible").count() > 3

            if not has_form_fields:
                page_text = page.inner_text("body")[:3000].lower()
                if any(kw in page_text for kw in ["apply for this", "apply now", "apply online",
                                                    "start application", "submit application"]):
                    print(f"  >> Clicking Apply...")
                    clicked = click_apply_button(page)
                    if clicked:
                        time.sleep(3)
                        dismiss_cookie_banner(page)
                        dismiss_overlays(page)
                        screenshot(page, f"{slug}_02_form_opened")
                    else:
                        print(f"  !! Could not find apply button")

            # Detect form type and run appropriate handler
            if is_greenhouse_form(page):
                result = run_greenhouse_application(
                    page, profile, profile_path, resume_path, cover_letter_path, slug, dry_run
                )
            else:
                result = run_universal_application(
                    page, job, profile, profile_path, resume_path, cover_letter_path, slug, dry_run,
                    browser_ctx=ctx, platform=platform
                )

            if dry_run:
                browser.close()
                return result

            if result.status in ("user_skipped", "no_form_found"):
                browser.close()
                return result

            # Prompt for submission
            print(f"\n  >> Review screenshots:")
            print(f"     open outputs/screenshots/{slug}_filled.png")

            if result.failed_fields:
                print(f"\n  !! {len(result.failed_fields)} fields failed -- review before submitting")

            confirm = input("\n  Type YES to submit, SKIP to skip: ").strip().upper()
            if confirm == "YES":
                submit_patterns = [
                    "Submit application", "Submit", "Apply", "Apply now",
                    "Submit Application", "Send Application", "Complete",
                ]
                for pattern in submit_patterns:
                    try:
                        btn = page.get_by_role("button", name=pattern)
                        if btn.count() > 0:
                            btn.first.click()
                            time.sleep(4)
                            screenshot(page, f"{slug}_submitted")
                            print(f"  >> Submitted!")
                            browser.close()
                            return ApplicationResult(
                                status="submitted",
                                filled=result.filled,
                                total=result.total,
                                failed_fields=result.failed_fields,
                            )
                    except Exception:
                        continue
                # Try input[type=submit]
                try:
                    submit = page.locator("input[type='submit']")
                    if submit.count() > 0:
                        submit.first.click()
                        time.sleep(4)
                        screenshot(page, f"{slug}_submitted")
                        print(f"  >> Submitted!")
                        browser.close()
                        return ApplicationResult(
                            status="submitted",
                            filled=result.filled,
                            total=result.total,
                            failed_fields=result.failed_fields,
                        )
                except Exception:
                    pass
                print(f"  !! Could not find submit button")
                browser.close()
                return ApplicationResult(
                    status="submit_error",
                    filled=result.filled,
                    total=result.total,
                    failed_fields=result.failed_fields,
                )
            else:
                browser.close()
                return ApplicationResult(
                    status="user_skipped",
                    filled=result.filled,
                    total=result.total,
                    failed_fields=result.failed_fields,
                )

    except Exception as e:
        print(f"  !! Error: {e}")
        import traceback
        traceback.print_exc()
        return ApplicationResult(status="error")
