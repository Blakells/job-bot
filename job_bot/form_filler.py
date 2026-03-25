"""Generic form filling: text fields, selects, toggles, file uploads."""

from __future__ import annotations

import logging
import time
from pathlib import Path
from scrapling import Selector

logger = logging.getLogger(__name__)


def _dismiss_blocking_modal(page) -> bool:
    """Remove any modal overlay blocking form interaction mid-fill.

    Paylocity shows a 'citrus-modal-wrapper' dialog that blocks clicks.
    This is called as a retry mechanism when a click times out.
    """
    try:
        removed = page.evaluate("""() => {
            let removed = 0;
            // Remove citrus-modal overlays ONLY if they don't contain form inputs
            document.querySelectorAll('[id*="citrus-modal"]').forEach(el => {
                if (el.querySelector('input, textarea, select, [role="combobox"]')) return;
                el.remove();
                removed++;
            });
            // Remove orphan backdrops only if no form-containing modal is open
            const hasFormModal = Array.from(document.querySelectorAll(
                '[role="dialog"], .modal, [data-role="modal-wrapper"]'
            )).some(m => m.getBoundingClientRect().height > 0
                && m.querySelector('input, textarea, select, [role="combobox"]'));
            if (!hasFormModal) {
                document.querySelectorAll('.modal-backdrop').forEach(el => {
                    el.remove();
                    removed++;
                });
            }
            if (removed > 0) {
                document.body.classList.remove('modal-open');
                document.body.style.overflow = '';
                document.documentElement.style.overflow = '';
            }
            return removed;
        }""")
        if removed > 0:
            logger.info("Dismissed %d blocking modal(s) mid-fill", removed)
            time.sleep(0.3)
            return True
    except Exception:
        pass
    # Also try Escape key
    try:
        page.keyboard.press("Escape")
        time.sleep(0.3)
    except Exception:
        pass
    return False


# ── Scrapling page pre-scan ──────────────────────────────────────────────────
# Captures the full DOM once and analyzes all form elements BEFORE any
# interaction.  This replaces fragile per-field JS queries that walk up the
# DOM and accidentally match unrelated elements.

def prescan_page_with_scrapling(page) -> dict[str, dict]:
    """
    Pre-scan the full page DOM with scrapling.

    Uses a TOP-DOWN approach: only inputs with role="combobox" or
    aria-autocomplete are react-select.  This avoids falsely tagging
    regular text inputs that happen to share a wrapper div.

    Returns a dict keyed by CSS selector with:
      - is_react_select: bool
      - displayed_value: str  (for react-select components)
      - input_value: str      (from the value attribute)
    """
    html = page.content()
    doc = Selector(html)

    # ── Step 1: Identify react-select inputs by their attributes ────────
    # Only inputs with role="combobox" or aria-autocomplete are part of
    # react-select / autocomplete components.  Walk up a few levels from
    # each to find the displayed value (in a sibling singleValue div).
    react_map = {}  # elem_id -> { displayed_value }

    for rs_input in doc.css('input[role="combobox"], input[aria-autocomplete]'):
        elem_id = rs_input.attrib.get('id', '')
        elem_name = rs_input.attrib.get('name', '')
        if not elem_id and not elem_name:
            continue

        displayed_value = ''
        ancestor = rs_input.parent
        for depth in range(5):  # react-select inputs are 2-4 levels deep
            if not ancestor or ancestor.tag in ('body', 'html', 'form'):
                break
            for pattern in [
                '[class*="singleValue"]', '[class*="single-value"]',
                '[class*="rw-input"]',
            ]:
                matches = ancestor.css(pattern)
                if matches:
                    text = matches[0].get_all_text(strip=True)
                    if text and text != '--' and len(text) > 1:
                        displayed_value = text
                        break
            if displayed_value:
                break
            ancestor = ancestor.parent

        info = {'displayed_value': displayed_value}
        if elem_id:
            react_map[elem_id] = info
        if elem_name:
            react_map[elem_name] = info

    # ── Step 2: Map ALL form inputs ─────────────────────────────────────
    field_info = {}
    for el in doc.css('input, textarea'):
        elem_id = el.attrib.get('id', '')
        elem_name = el.attrib.get('name', '')
        if not elem_id and not elem_name:
            continue

        selectors = set()
        if elem_id:
            selectors.add(f'#{elem_id}')
            selectors.add(f'{el.tag}#{elem_id}')
        if elem_name:
            selectors.add(f'[name="{elem_name}"]')
            selectors.add(f'{el.tag}[name="{elem_name}"]')

        # Check if this input was identified as react-select in Step 1
        rs_info = react_map.get(elem_id) or react_map.get(elem_name)

        info = {
            'is_react_select': bool(rs_info),
            'displayed_value': rs_info['displayed_value'] if rs_info else '',
            'input_value': el.attrib.get('value', ''),
            'tag': el.tag,
            'type': el.attrib.get('type', 'text'),
        }
        for sel in selectors:
            field_info[sel] = info

    # ── Print summary ───────────────────────────────────────────────────
    react_selects = [(s, v) for s, v in field_info.items()
                     if v['is_react_select'] and s.startswith('#')]
    print(f"\n  >> Scrapling pre-scan: {len(field_info)} selector(s), "
          f"{len(react_selects)} react-select(s)")
    for sel, info in react_selects:
        val = info['displayed_value'] or '(empty/placeholder)'
        print(f"       {sel} → '{val}'")

    return field_info


# ── React-compatible JS fill ─────────────────────────────────────────────────
# React overrides the value property on inputs, so el.value = x doesn't
# trigger re-renders. Using the native setter + dispatching events fixes this.

REACT_NATIVE_FILL_JS = """(args) => {
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
}"""

# JavaScript-based select filling — works even on hidden <select> elements
# and custom-styled dropdowns that overlay the native select.
SELECT_JS_FILL = """(args) => {
    const el = document.querySelector(args.selector);
    if (!el || el.tagName !== 'SELECT') return false;

    const answer = (args.answer || '').toLowerCase().trim();

    // Try exact match first, then fuzzy
    let bestOption = null;
    let bestScore = 0;
    for (const opt of el.options) {
        const text = opt.text.toLowerCase().trim();
        const val = opt.value.toLowerCase().trim();

        // Skip placeholder options
        if (val === '' || text === '--' || text === '' || text === 'select' || text === 'choose') continue;

        // Exact match
        if (text === answer || val === answer) { bestOption = opt; bestScore = 100; break; }

        // Containment match
        if (text.includes(answer) || answer.includes(text)) {
            const score = Math.min(text.length, answer.length) / Math.max(text.length, answer.length) * 50;
            if (score > bestScore) { bestOption = opt; bestScore = score; }
        }
        if (val.includes(answer) || answer.includes(val)) {
            const score = Math.min(val.length, answer.length) / Math.max(val.length, answer.length) * 40;
            if (score > bestScore) { bestOption = opt; bestScore = score; }
        }
    }

    if (bestOption) {
        el.value = bestOption.value;
        el.dispatchEvent(new Event('change', {bubbles: true}));
        el.dispatchEvent(new Event('input', {bubbles: true}));
        return bestOption.text;
    }
    return false;
}"""


def fill_text_field(page, field_id: str, answer: str) -> bool:
    """Fill a standard text input by ID."""
    try:
        el = page.locator(f"input#{field_id}")
        if el.count() == 0:
            return False
        el.click()
        el.fill("")
        el.type(str(answer), delay=30)
        el.press("Tab")
        time.sleep(0.2)
        return True
    except (TimeoutError, ValueError) as e:
        logger.warning("Text fill error (%s): %s", field_id, e)
        return False


def upload_file(page, input_id, file_path):
    """
    Upload a file to a Greenhouse file input.

    Strategy:
    1. Click the "Attach" button and intercept the file chooser
    2. Fall back to unhiding the <input type=file> and using set_input_files
    """
    try:
        if not file_path or not Path(file_path).exists():
            print(f"      !! File not found: {file_path}")
            return False

        abs_path = str(Path(file_path).absolute())

        # Strategy 1: Click the "Attach" button near this file input
        try:
            attach_btn = page.locator(
                f"input#{input_id} >> xpath=ancestor::div[contains(@class,'file-upload')]"
                f"//button[contains(text(),'Attach')]"
            )

            if attach_btn.count() == 0:
                attach_btn = page.locator(
                    f"input#{input_id} >> xpath=ancestor::div[contains(@class,'upload')]"
                    f"//a[contains(text(),'Attach')] | "
                    f"input#{input_id} >> xpath=ancestor::div[contains(@class,'upload')]"
                    f"//button[contains(text(),'Attach')]"
                )

            if attach_btn.count() == 0:
                attach_btn = page.locator(
                    f"input#{input_id} >> xpath=ancestor::div[contains(@class,'field')]"
                    f"//*[contains(text(),'Attach')]"
                )

            if attach_btn.count() > 0:
                with page.expect_file_chooser(timeout=5000) as fc_info:
                    attach_btn.first.click()
                file_chooser = fc_info.value
                file_chooser.set_files(abs_path)
                time.sleep(2)

                upload_group = page.locator(
                    f"input#{input_id} >> xpath=ancestor::div[contains(@class,'file-upload')]"
                )
                if upload_group.count() > 0:
                    group_text = upload_group.first.inner_text()
                    filename = Path(file_path).name
                    if filename.lower() in group_text.lower() or "remove" in group_text.lower():
                        print(f"      >> Uploaded via Attach: {filename}")
                        return True

                print(f"      >> Uploaded via Attach: {Path(file_path).name}")
                return True

        except (TimeoutError, ValueError) as e:
            logger.debug("Attach button method failed for %s: %s, trying direct input...", input_id, e)

        # Strategy 2: Direct set_input_files on the hidden file input
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

            page.evaluate(f"""() => {{
                const el = document.getElementById("{input_id}");
                if (el) {{
                    el.dispatchEvent(new Event('change', {{ bubbles: true }}));
                    el.dispatchEvent(new Event('input', {{ bubbles: true }}));
                }}
            }}""")
            time.sleep(1)

            print(f"      >> Uploaded via direct input: {Path(file_path).name}")
            return True

        print(f"      !! Could not find file input #{input_id}")
        return False

    except Exception as e:
        logger.error("Upload error (%s): %s", input_id, e)
        return False


def handle_file_upload(page, field, file_path):
    """Handle file upload for any form — tries multiple approaches."""
    file_path = str(Path(file_path).absolute())
    if not Path(file_path).exists():
        print(f"      !! File not found: {file_path}")
        return False

    try:
        selector = field.get("selector")
        if selector:
            el = page.locator(selector)
            if el.count() > 0:
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
        logger.error("File upload error for %s: %s", field.get('label', ''), e)
    return False


def fill_toggle_button(page, field, answer):
    """
    Click a YES or NO toggle button on forms like Workable.
    These are custom button elements, not standard form inputs.
    """
    answer_upper = answer.strip().upper()
    if answer_upper not in ("YES", "NO"):
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
            except (TimeoutError, ValueError) as e:
                logger.debug("Toggle stored selector click failed (%s): %s", stored_sel, e)

        # Strategy 2: Find the button by question text + button text via JavaScript
        clicked = page.evaluate("""(args) => {
            const questionText = args.question.toLowerCase();
            const targetBtn = args.target;

            const buttons = document.querySelectorAll('button, [role="button"]');

            for (const btn of buttons) {
                const btnText = (btn.textContent || '').trim().toUpperCase();
                if (btnText !== targetBtn) continue;

                const container = btn.closest('[class*="question"], [class*="toggle"], [class*="field"], [class*="group"]')
                              || btn.parentElement?.parentElement;
                if (!container) continue;

                const containerText = container.innerText.toLowerCase();
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

        # Strategy 3: Single unambiguous YES/NO button
        try:
            btn = page.get_by_role("button", name=answer_upper, exact=True)
            if btn.count() == 1:
                btn.first.click(force=True, timeout=3000)
                time.sleep(0.3)
                return True
        except (TimeoutError, ValueError) as e:
            logger.debug("Toggle get_by_role click failed for %s: %s", answer_upper, e)

        return False

    except Exception as e:
        logger.error("Toggle button error for '%s': %s", question_text[:50], e)
        return False


def fill_generic_field(page, field: dict, answer: str, resume_path: str | None = None, cover_letter_path: str | None = None, prescan: dict[str, dict] | None = None) -> bool:
    """
    Fill a single form field using generic Playwright actions.
    Works on any website — text inputs, selects, textareas, file uploads.

    prescan: optional dict from prescan_page_with_scrapling() —
             used to detect pre-filled react-select fields.
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
            except (OSError, UnicodeDecodeError) as e:
                logger.warning("Failed to read cover letter %s: %s", cover_letter_path, e)
                return False
        elif ext == ".pdf":
            txt_companion = cover_letter_path.replace(".pdf", ".txt")
            if Path(txt_companion).exists():
                try:
                    answer = Path(txt_companion).read_text()
                except (OSError, UnicodeDecodeError) as e:
                    logger.warning("Failed to read cover letter companion %s: %s", txt_companion, e)
                    return False
            else:
                print(f"      >> Cover letter is PDF only, no .txt companion found for textarea paste")
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

        if field_type in ("select-one", "select-multiple") or field.get("tag") == "select":
            # Strategy 1: Playwright select_option (standard visible selects)
            for attempt_fn in [
                lambda: el.select_option(label=answer),
                lambda: el.select_option(value=answer),
            ]:
                try:
                    attempt_fn()
                    return True
                except (TimeoutError, ValueError) as e:
                    logger.debug("select_option attempt failed for %s: %s", selector, e)

            # Strategy 2: Fuzzy option match via Playwright
            try:
                options = field.get("options", [])
                answer_lower = answer.lower().strip()
                for opt in options:
                    if answer_lower in opt.lower() or opt.lower() in answer_lower:
                        el.select_option(label=opt)
                        return True
            except (TimeoutError, ValueError) as e:
                logger.debug("Fuzzy select_option failed for %s: %s", selector, e)

            # Strategy 3: JavaScript direct set (works on hidden/custom selects)
            try:
                result = page.evaluate(SELECT_JS_FILL, {"selector": selector, "answer": answer})
                if result:
                    print(f"      >> Used JS select fill -> {result}")
                    return True
            except (TimeoutError, ValueError) as e:
                logger.debug("JS select fill failed for %s: %s", selector, e)

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
            answer_str = str(answer)
            field_label = field.get("label", "")

            # ── Tag-input / skills fields ──
            # Answer starts with "SKILLS:" — type each skill + Enter
            if answer_str.startswith("SKILLS:"):
                skills = [s.strip() for s in answer_str[7:].split(",") if s.strip()]
                if not skills:
                    return True
                try:
                    el = page.locator(selector) if selector else None
                    if el:
                        el.click(timeout=5000)
                        time.sleep(0.2)
                    for skill in skills:
                        page.keyboard.type(skill, delay=20)
                        time.sleep(0.2)
                        page.keyboard.press("Enter")
                        time.sleep(0.3)
                    # Tab out of the skills field
                    page.keyboard.press("Tab")
                    time.sleep(0.2)
                except Exception as e:
                    logger.warning("Skills tag-input fill failed: %s", e)
                    return False
                return True

            # ── Skip check: prescan (scrapling) + Playwright input_value ──
            # 1) Scrapling prescan: reliable react-select detection
            #    (the prescan analyzed the DOM once upfront, scoped to each
            #     component — no fragile parent-chain walking per field)
            if prescan and selector:
                scan = prescan.get(selector)
                if scan and scan.get('is_react_select') and scan.get('displayed_value'):
                    displayed = scan['displayed_value']
                    if displayed.strip().lower() == answer_str.strip().lower():
                        print(f"      >> Skipping react-select (prescan: '{displayed}')")
                        return True

            # 2) Playwright input_value: catches regular pre-filled fields
            try:
                current_value = el.input_value() or ""
                if current_value.strip().lower() == answer_str.strip().lower():
                    print(f"      >> Skipping (input already has: {current_value[:30]})")
                    return True
            except (TimeoutError, ValueError) as e:
                logger.debug("input_value check failed for %s: %s", selector, e)

            # Detect react-select / autocomplete inputs
            is_autocomplete = False
            if prescan and selector:
                scan = prescan.get(selector)
                if scan and scan.get('is_react_select'):
                    is_autocomplete = True
            if not is_autocomplete:
                try:
                    role = el.get_attribute("role") or ""
                    aria_auto = el.get_attribute("aria-autocomplete") or ""
                    parent_class = field.get("parentClass", "").lower()
                    if (role == "combobox" or aria_auto
                            or "react-select" in parent_class
                            or "autocomplete" in parent_class
                            or "combobox" in parent_class):
                        is_autocomplete = True
                except (TimeoutError, ValueError) as e:
                    logger.debug("Autocomplete attribute check failed for %s: %s", selector, e)

            # Detect email fields for special React-compatible fill
            is_email = (field_type == 'email' or
                        'email' in field.get('id', '').lower() or
                        'email' in field.get('name', '').lower() or
                        'email' in field.get('label', '').lower())

            try:
                try:
                    el.click(timeout=5000)
                except TimeoutError:
                    if is_autocomplete:
                        # React-select inputs are often hidden/zero-size; the
                        # visible element is the wrapper div.  Click the
                        # parent container instead.
                        logger.debug("Click blocked on %s, trying react-select container click", selector)
                        try:
                            page.evaluate("""(sel) => {
                                const input = document.querySelector(sel);
                                if (!input) return;
                                // Walk up to the react-select container
                                let parent = input;
                                for (let i = 0; i < 6; i++) {
                                    parent = parent.parentElement;
                                    if (!parent) break;
                                    if (parent.className && parent.className.includes('control')) {
                                        parent.click();
                                        return;
                                    }
                                }
                                // Fallback: click the direct parent
                                if (input.parentElement) input.parentElement.click();
                            }""", selector)
                            time.sleep(0.3)
                        except Exception:
                            pass
                    else:
                        # A modal/overlay may be blocking the click — try to dismiss it
                        logger.debug("Click blocked on %s, attempting overlay dismissal", selector)
                        _dismiss_blocking_modal(page)
                        el.click(timeout=5000)
                time.sleep(0.1)

                if is_autocomplete:
                    # Detect address autocomplete (Google Places) fields.
                    # These are street-address inputs where pressing Enter
                    # selects a Google Places suggestion, overwriting the
                    # entire address widget (Country, City, State, Zip).
                    # We must NOT press Enter on these — use Escape+Tab.
                    #
                    # IMPORTANT: Country, State, City, Zip, County fields
                    # are react-selects, NOT address autocompletes. Only
                    # "address-line" or "address-1" style fields (the
                    # street address) trigger Google Places.
                    field_id = field.get("id", "").lower()
                    is_street_address = (
                        ("address" in field_id and ("line" in field_id or "-1" in field_id))
                        and "country" not in field_id
                        and "city" not in field_id
                        and "state" not in field_id
                        and "zip" not in field_id
                        and "county" not in field_id
                        and "postal" not in field_id
                    )
                    # Also check for explicit Google Places aria-controls
                    aria_ctrl = el.get_attribute("aria-controls") or ""
                    if "autocomplete-list" in aria_ctrl and is_street_address:
                        is_street_address = True

                    # Focus the input via JS first — react-select inputs
                    # are often hidden/zero-size and el.click() may have
                    # failed above.  JS focus ensures we can type into it.
                    try:
                        page.evaluate("""(sel) => {
                            const input = document.querySelector(sel);
                            if (input) input.focus();
                        }""", selector)
                        time.sleep(0.1)
                    except Exception:
                        pass

                    el.fill("")
                    el.type(answer_str, delay=50)
                    time.sleep(0.5)

                    if is_street_address:
                        # Dismiss Google Places suggestions without selecting
                        el.press("Escape")
                        time.sleep(0.2)
                        el.press("Tab")
                        time.sleep(0.3)
                        logger.debug("Street address autocomplete: typed + Escape+Tab (no Enter)")
                    else:
                        # Standard react-select: Enter to confirm selection
                        el.press("Enter")
                        time.sleep(0.3)
                elif is_email and selector:
                    # Email: use fill("") + type() for now; the post-fill
                    # email cleanup (fix_email_validation) will fix any
                    # sticky React DebounceInput validation error.
                    el.fill("")
                    el.type(answer_str, delay=12)
                    time.sleep(0.5)
                elif len(answer_str) < 200:
                    # Short text: clear with fill("") then type() for real
                    # keyboard events (triggers React validation).
                    el.fill("")
                    el.type(answer_str, delay=12)
                    time.sleep(0.8)  # Let React process keystrokes / validation
                else:
                    # Long text: use fill() for speed
                    el.fill(answer_str)
            except (TimeoutError, ValueError) as e:
                if is_autocomplete:
                    # Don't force-fill autocomplete/react-select — the click
                    # failed but the value is likely already pre-filled.
                    logger.debug("Skipping autocomplete field (click blocked, likely pre-filled): %s", e)
                    return True
                try:
                    page.evaluate(REACT_NATIVE_FILL_JS, {"selector": selector, "value": answer_str})
                    print(f"      >> Used JS fill (overlay was blocking)")
                except (TimeoutError, ValueError) as js_err:
                    logger.warning("JS fill also failed for %s: %s", selector, js_err)
                    return False
            try:
                el.press("Tab")
                time.sleep(0.2)
            except (TimeoutError, ValueError) as e:
                logger.debug("Tab press failed for %s: %s", selector, e)
            return True

    except Exception as e:
        if selector:
            try:
                page.evaluate(REACT_NATIVE_FILL_JS, {"selector": selector, "value": str(answer)})
                print(f"      >> Used JS fill fallback for {field.get('label', '')}")
                return True
            except (TimeoutError, ValueError) as e2:
                logger.debug("JS fill fallback also failed for %s: %s", selector, e2)
        logger.error("Could not fill %s: %s", field.get('label', ''), e)
        return False


# ── Toggle button keyword rules ──────────────────────────────────────────────

YES_RULES = [
    "authorized to work", "eligible to work", "legally authorized",
    "right to work", "background check", "willing to undergo",
    "drug test", "drug screen", "able to work", "willing to relocate",
    "open to relocation", "security+", "comptia", "sec+", "certification",
    "commit to this schedule", "experience", "willing to travel",
    "work authorization", "are you 18", "legal age", "agree to",
    "consent to", "bachelor", "degree",
]

NO_RULES = [
    "require sponsorship", "need sponsorship", "visa sponsorship",
    "non-compete", "convicted", "felony",
    "currently hold an active public trust", "active security clearance",
    "active clearance", "currently hold a clearance",
]


def fill_toggle_buttons_sweep(page, profile: dict) -> int:
    """
    Post-fill sweep: find and click YES/NO toggle button groups on the page.

    Workable uses custom toggle UI: <span>YES</span> inside a parent div.
    These are NOT standard form elements — just styled spans/divs.
    """
    try:
        results = page.evaluate("""(rules) => {
            const yesRules = rules.yes;
            const noRules = rules.no;
            const actions = [];
            const processedQuestions = new Set();

            const walker = document.createTreeWalker(
                document.body, NodeFilter.SHOW_ELEMENT
            );

            const yesNoElements = [];
            while (walker.nextNode()) {
                const el = walker.currentNode;
                const directText = (el.childNodes.length === 1 && el.childNodes[0].nodeType === 3)
                    ? el.childNodes[0].textContent.trim() : null;
                if (directText === 'YES' || directText === 'NO' ||
                    directText === 'Yes' || directText === 'No') {
                    yesNoElements.push({el: el, text: directText.toUpperCase()});
                }
            }

            for (const item of yesNoElements) {
                if (item.text !== 'YES') continue;

                const clickTarget = item.el.parentElement;
                if (!clickTarget) continue;

                let questionContainer = clickTarget;
                let questionText = '';
                for (let i = 0; i < 8; i++) {
                    questionContainer = questionContainer.parentElement;
                    if (!questionContainer) break;

                    const fullText = questionContainer.innerText || '';
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

                questionText = questionText.replace(/\\*/g, '').trim();
                const questionKey = questionText.slice(0, 50).toLowerCase();

                if (processedQuestions.has(questionKey)) continue;
                processedQuestions.add(questionKey);

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
                    if (qLower.includes('do you have') || qLower.includes('are you')) {
                        answer = 'YES';
                    } else {
                        continue;
                    }
                }

                const allSpans = questionContainer.querySelectorAll('span, div, label');
                let targetEl = null;
                for (const span of allSpans) {
                    const dt = (span.childNodes.length === 1 && span.childNodes[0].nodeType === 3)
                        ? span.childNodes[0].textContent.trim().toUpperCase() : null;
                    if (dt === answer) {
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
                print(f"     >> Toggle: {r['question'][:55]}... -> {r['answer']}")
            return len(results)
        else:
            print(f"     >> No toggle buttons found to fill")
            return 0

    except Exception as e:
        logger.error("Toggle sweep error: %s", e, exc_info=True)
        return 0


# ── Dropdown sweep: DOM-inspection approach ──────────────────────────────────
# Scans the full DOM for ALL dropdown-like elements (<select>, custom components),
# analyzes their structure, determines the right answer, and fills them.

def _determine_dropdown_answer(label: str, available_options: list[str], profile: dict) -> str | None:
    """
    Dynamically determine the best answer for a dropdown based on:
    1. Yes/No detection using toggle button keyword rules
    2. Profile-based answer lookup
    3. Common field-type defaults

    Returns the exact option text to select, or None if undetermined.
    """
    label_lower = label.lower().replace('*', '').replace('(required)', '').strip()
    opts_lower = [o.lower().strip() for o in available_options]

    # ── 1. Yes/No dropdown detection ──────────────────────────────────────
    # Strip trailing asterisks/symbols that some ATS add (e.g. "Yes*")
    import re as _re
    def _clean(s):
        return _re.sub(r'[^a-z]', '', s.strip().lower())
    yes_opts = [o for o in available_options if _clean(o) in ('yes', 'y')]
    no_opts = [o for o in available_options if _clean(o) in ('no', 'n')]

    if yes_opts and no_opts:
        for kw in YES_RULES:
            if kw.lower() in label_lower:
                return yes_opts[0]
        for kw in NO_RULES:
            if kw.lower() in label_lower:
                return no_opts[0]

        # Heuristic defaults for common Yes/No patterns
        if any(kw in label_lower for kw in [
            'permission', 'consent', 'agree', 'sms', 'text',
            'contact you', 'notify', 'send you',
        ]):
            return yes_opts[0]
        if any(kw in label_lower for kw in [
            'applied', 'worked', 'employed', 'before', 'previously',
            'former', 'prior',
        ]):
            return no_opts[0]

        # Unknown yes/no — skip
        return None

    # ── 2. Profile-based answer lookup ────────────────────────────────────
    eeoc = profile.get("eeoc", {})
    profile_answers = {
        "salary type": "Yearly",
        "pay type": "Yearly",
        "compensation type": "Yearly",
        "employment type": "Full-time",
        "desired employment": "Full-time",
        "job type": "Full-time",
        "available for": "Full-time",
        "work schedule": "Full-time",
        "gender": eeoc.get("gender", ""),
        "race": eeoc.get("race", ""),
        "ethnicity": eeoc.get("race", ""),
        "hispanic": eeoc.get("hispanic_ethnicity", ""),
        "veteran": eeoc.get("veteran_status", ""),
        "disability": eeoc.get("disability_status", ""),
        "how did you hear": "LinkedIn",
        "referral source": "LinkedIn",
        "source": "LinkedIn",
        "hear about": "LinkedIn",
        "where did you find": "LinkedIn",
    }

    for keyword, answer in profile_answers.items():
        if keyword in label_lower and answer:
            answer_lower = answer.lower().strip()
            # Exact match first
            for opt in available_options:
                if opt.lower().strip() == answer_lower:
                    return opt
            # Fuzzy: contains match
            for opt in available_options:
                opt_lower = opt.lower().strip()
                if answer_lower in opt_lower or opt_lower in answer_lower:
                    return opt

    # ── 3. State dropdown (address or education) ────────────────────────
    if label_lower in ('state', 'state/province', 'province'):
        from job_bot.utils import parse_location
        personal = profile.get("personal", {})
        loc = personal.get("location", "")
        parsed = parse_location(loc)
        state_full = parsed["state_full"]
        if state_full:
            for opt in available_options:
                if opt.lower().strip() == state_full.lower():
                    return opt
            for opt in available_options:
                if state_full.lower() in opt.lower() or opt.lower() in state_full.lower():
                    return opt

    # ── 4. School Type / Education Level ────────────────────────────────
    if any(kw in label_lower for kw in ['school type', 'education level',
                                         'education type']):
        edu = profile.get("education", [])
        if edu and isinstance(edu, list) and len(edu) > 0:
            degree = edu[0].get("degree", "").lower()
            if any(k in degree for k in ["master", "mba", "m.s", "m.a"]):
                for opt in available_options:
                    if 'graduate' in opt.lower():
                        return opt
            # Bachelor's / Associates → College / University
            for opt in available_options:
                if 'university' in opt.lower():
                    return opt
            for opt in available_options:
                ol = opt.lower()
                if 'college' in ol and 'community' not in ol:
                    return opt
        # No education data — default to College / University
        for opt in available_options:
            if 'university' in opt.lower():
                return opt
        for opt in available_options:
            ol = opt.lower()
            if 'college' in ol and 'community' not in ol and 'vocational' not in ol:
                return opt

    # ── 5. Degree Type / Degree Obtained ──────────────────────────────
    if any(kw in label_lower for kw in ['degree type', 'degree level',
                                         'degree obtained', 'type of degree',
                                         'highest degree']):
        edu = profile.get("education", [])
        degree_label = ""
        if edu and isinstance(edu, list) and len(edu) > 0:
            degree_label = edu[0].get("degree", "")
        # The core keyword from the profile degree (e.g. "bachelor" from "Bachelor's")
        degree_keywords = {
            "bachelor": ["bachelor"],
            "b.s": ["bachelor"],
            "b.a": ["bachelor"],
            "master": ["master"],
            "m.s": ["master"],
            "m.a": ["master"],
            "mba": ["master"],
            "associate": ["associate"],
            "a.s": ["associate"],
            "a.a": ["associate"],
            "doctor": ["doctor", "doctoral", "phd"],
            "ph.d": ["doctor", "doctoral", "phd"],
            "phd": ["doctor", "doctoral", "phd"],
            "high school": ["high school"],
            "ged": ["high school", "ged"],
        }
        search_keys = []
        for key, keywords in degree_keywords.items():
            if key in degree_label.lower():
                search_keys = keywords
                break
        if search_keys:
            # Match any option containing our keyword
            for opt in available_options:
                opt_lower = opt.lower().strip()
                for sk in search_keys:
                    if sk in opt_lower:
                        return opt

    return None

# JS that inspects the DOM to find ALL dropdown-like elements
FIND_DROPDOWNS_JS = """() => {
    const dropdowns = [];

    // Helper: find label text for an element
    function findLabel(el) {
        // 1. Explicit <label for=id>
        if (el.id) {
            const lbl = document.querySelector('label[for="' + el.id + '"]');
            if (lbl) return lbl.innerText.trim();
        }

        // 2. aria-label
        if (el.getAttribute('aria-label')) return el.getAttribute('aria-label').trim();

        // 3. Walk up DOM to find question text
        let parent = el.parentElement;
        for (let i = 0; i < 8 && parent; i++) {
            // Look for label-like elements in this container
            const labels = parent.querySelectorAll(':scope > label, :scope > span, :scope > p, :scope > div > label, :scope > legend');
            for (const lbl of labels) {
                // Don't use the select itself or its children as the label
                if (lbl.contains(el) || el.contains(lbl)) continue;
                const txt = lbl.innerText.trim().replace(/\\*/g, '').trim();
                if (txt && txt.length > 3 && txt.length < 200) return txt;
            }

            // Check parent's own text (minus child elements)
            const parentText = parent.innerText?.trim() || '';
            if (parentText.length > 5 && parentText.length < 300) {
                // Get first line as the label
                const firstLine = parentText.split('\\n')[0].replace(/\\*/g, '').trim();
                if (firstLine.length > 3 && firstLine.length < 200) return firstLine;
            }
            parent = parent.parentElement;
        }
        return '';
    }

    // Phase 1: Standard <select> elements (including hidden ones)
    document.querySelectorAll('select').forEach(sel => {
        const selectedText = sel.options[sel.selectedIndex]
            ? sel.options[sel.selectedIndex].text.trim() : '';
        const isFilled = sel.value && sel.value !== ''
            && selectedText !== '--' && selectedText !== ''
            && selectedText !== 'Select' && selectedText !== 'Choose'
            && selectedText !== '--Select--';

        const options = Array.from(sel.options)
            .map(o => ({text: o.text.trim(), value: o.value}))
            .filter(o => o.text && o.text !== '--' && o.text !== '' && o.text !== 'Select');

        const selector = sel.id ? '#' + CSS.escape(sel.id)
            : sel.name ? 'select[name="' + sel.name + '"]' : null;

        dropdowns.push({
            type: 'select',
            selector: selector,
            label: findLabel(sel),
            currentValue: selectedText,
            isFilled: isFilled,
            options: options,
            tagName: 'SELECT'
        });
    });

    // Phase 2: Scan ALL iframes for <select> elements too
    document.querySelectorAll('iframe').forEach((iframe, idx) => {
        try {
            const iframeDoc = iframe.contentDocument || iframe.contentWindow?.document;
            if (!iframeDoc) return;

            iframeDoc.querySelectorAll('select').forEach(sel => {
                const selectedText = sel.options[sel.selectedIndex]
                    ? sel.options[sel.selectedIndex].text.trim() : '';
                const isFilled = sel.value && sel.value !== ''
                    && selectedText !== '--' && selectedText !== '';

                const options = Array.from(sel.options)
                    .map(o => ({text: o.text.trim(), value: o.value}))
                    .filter(o => o.text && o.text !== '--' && o.text !== '');

                dropdowns.push({
                    type: 'iframe-select',
                    iframeIndex: idx,
                    selector: sel.id ? '#' + CSS.escape(sel.id)
                        : sel.name ? 'select[name="' + sel.name + '"]' : null,
                    label: findLabel(sel),
                    currentValue: selectedText,
                    isFilled: isFilled,
                    options: options,
                    tagName: 'SELECT'
                });
            });
        } catch(e) { /* cross-origin iframe, skip */ }
    });

    return dropdowns;
}"""


# JS that finds custom (div-based) dropdown components showing "--".
# Tags each trigger with data-jobbot-dd="N" so Playwright can locate them
# (auto-scroll, proper click handling).  Returns labels and indices.
FIND_CUSTOM_DROPDOWNS_JS = """() => {
    const results = [];
    const seen = new Set();
    let idx = 0;

    // Remove stale tags from previous runs
    document.querySelectorAll('[data-jobbot-dd]').forEach(el => el.removeAttribute('data-jobbot-dd'));

    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    while (walker.nextNode()) {
        const textNode = walker.currentNode;
        if (textNode.textContent.trim() !== '--') continue;

        const el = textNode.parentElement;
        if (!el) continue;

        const rect = el.getBoundingClientRect();
        if (rect.width < 20 || rect.height < 10) continue;
        const style = window.getComputedStyle(el);
        if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') continue;
        if (el.closest('select')) continue;

        const posKey = Math.round(rect.x / 10) + '_' + Math.round(rect.y / 10);
        if (seen.has(posKey)) continue;
        seen.add(posKey);

        // Find clickable ancestor
        let clickTarget = el;
        let ct = el;
        for (let i = 0; i < 6 && ct; i++) {
            const cursor = window.getComputedStyle(ct).cursor;
            const role = ct.getAttribute('role');
            const tabindex = ct.getAttribute('tabindex');
            const tag = ct.tagName.toLowerCase();
            if (cursor === 'pointer' || role === 'combobox' || role === 'button' ||
                role === 'listbox' || tabindex !== null || tag === 'button' || tag === 'a') {
                clickTarget = ct;
                break;
            }
            ct = ct.parentElement;
        }

        // Tag the element so Playwright can locate it
        clickTarget.setAttribute('data-jobbot-dd', String(idx));

        // Find label
        let label = '';
        let search = clickTarget;
        for (let i = 0; i < 6 && search && !label; i++) {
            const al = search.getAttribute('aria-label');
            if (al && al.trim().length > 3 && al.trim() !== '--') { label = al.trim(); break; }
            const alBy = search.getAttribute('aria-labelledby');
            if (alBy) {
                const ref = document.getElementById(alBy);
                if (ref) { label = ref.innerText.replace(/\\*/g, '').trim(); break; }
            }
            search = search.parentElement;
        }
        if (!label) {
            let parent = clickTarget.parentElement;
            for (let i = 0; i < 10 && parent && !label; i++) {
                const labelEls = parent.querySelectorAll(
                    ':scope > label, :scope > span, :scope > p, :scope > div > label, ' +
                    ':scope > legend, :scope > div > span');
                for (const lbl of labelEls) {
                    if (lbl.contains(clickTarget) || clickTarget.contains(lbl)) continue;
                    const txt = lbl.innerText.replace(/\\*/g, '').trim();
                    if (txt && txt.length > 3 && txt.length < 200 && txt !== '--') {
                        label = txt; break;
                    }
                }
                if (!label && parent.id) {
                    const expl = document.querySelector('label[for="' + parent.id + '"]');
                    if (expl) label = expl.innerText.replace(/\\*/g, '').trim();
                }
                parent = parent.parentElement;
            }
        }

        // Also capture the outerHTML of the trigger + parent for debugging
        const triggerHtml = clickTarget.outerHTML.slice(0, 200);
        const parentHtml = (clickTarget.parentElement || clickTarget).outerHTML.slice(0, 300);

        results.push({
            label: label || '',
            index: idx,
            tagName: clickTarget.tagName,
            triggerHtml: triggerHtml,
            parentHtml: parentHtml,
        });
        idx++;
    }

    return results;
}"""

# JS to find and click an option after a dropdown opens.
# Searches ALL visible elements by direct text content (no CSS selector assumptions).
# Prefers elements below the trigger and in popup-like containers.
CLICK_DROPDOWN_OPTION_JS = """(args) => {
    const answers = args.answers;
    const triggerIdx = args.triggerIdx;
    const debug = [];

    // Get trigger position for proximity sorting
    const trigger = document.querySelector('[data-jobbot-dd="' + triggerIdx + '"]');
    const triggerRect = trigger ? trigger.getBoundingClientRect() : {x: 0, y: 0};

    // Collect ALL visible elements with their DIRECT text content
    const candidates = [];
    const allEls = document.getElementsByTagName('*');
    for (let i = 0; i < allEls.length; i++) {
        const el = allEls[i];
        // Get direct text only (not from children)
        let directText = '';
        for (const node of el.childNodes) {
            if (node.nodeType === 3) directText += node.textContent;
        }
        directText = directText.trim();
        if (!directText || directText === '--' || directText.length > 100) continue;

        const rect = el.getBoundingClientRect();
        if (rect.width <= 0 || rect.height <= 0) continue;
        const style = window.getComputedStyle(el);
        if (style.display === 'none' || style.visibility === 'hidden') continue;

        // Distance from trigger (prefer elements below it)
        const dx = Math.abs(rect.x - triggerRect.x);
        const dy = rect.y - triggerRect.y;
        const dist = dx + Math.abs(dy);
        const isBelow = dy > -10;

        candidates.push({el, text: directText, dist, isBelow, rect});
    }

    debug.push('Visible text elements: ' + candidates.length);

    for (const answer of answers) {
        const ansLower = answer.toLowerCase().trim();
        // Find exact matches
        let matches = candidates.filter(c => c.text.toLowerCase().trim() === ansLower);
        // Fallback: starts-with or contains
        if (matches.length === 0) {
            matches = candidates.filter(c => {
                const tl = c.text.toLowerCase().trim();
                return tl.startsWith(ansLower) || ansLower.startsWith(tl) ||
                       tl.includes(ansLower) || ansLower.includes(tl);
            });
        }

        debug.push('"' + answer + '": ' + matches.length + ' matches');

        if (matches.length > 0) {
            // Sort: prefer below trigger + close to trigger
            matches.sort((a, b) => {
                const aScore = (a.isBelow ? 0 : 10000) + a.dist;
                const bScore = (b.isBelow ? 0 : 10000) + b.dist;
                return aScore - bScore;
            });
            debug.push('Clicking: "' + matches[0].text + '" at y=' + matches[0].rect.y.toFixed(0));
            matches[0].el.click();
            return {clicked: true, matched: matches[0].text, debug: debug.join(' | ')};
        }
    }

    // Debug: dump elements near the trigger
    const nearby = candidates
        .filter(c => c.dist < 400 && c.isBelow)
        .sort((a, b) => a.dist - b.dist)
        .slice(0, 15);
    debug.push('Elements near trigger: ' + nearby.map(c =>
        c.el.tagName + ':"' + c.text.slice(0, 25) + '"'
    ).join(', '));

    return {clicked: false, matched: null, debug: debug.join(' | ')};
}"""

# JS to read ALL visible option texts after opening a custom dropdown.
# Returns a deduplicated list of option texts sorted by proximity to the trigger.
READ_DROPDOWN_OPTIONS_JS = """(triggerIdx) => {
    const trigger = document.querySelector('[data-jobbot-dd="' + triggerIdx + '"]');
    if (!trigger) return [];

    // ── Strategy 1: ARIA role="option" elements (most reliable) ────────
    // Paylocity rw-widget dropdowns use <li role="option"> inside a
    // <ul role="listbox">.  If we find a visible listbox near the trigger,
    // use ONLY its options — no guessing.
    const listboxes = document.querySelectorAll('[role="listbox"]');
    for (const lb of listboxes) {
        const rect = lb.getBoundingClientRect();
        if (rect.width <= 0 || rect.height <= 0) continue;
        const style = window.getComputedStyle(lb);
        if (style.display === 'none' || style.visibility === 'hidden') continue;

        const opts = lb.querySelectorAll('[role="option"]');
        if (opts.length === 0) continue;

        const texts = [];
        const seen = new Set();
        for (const opt of opts) {
            const t = (opt.textContent || '').trim();
            if (t && !seen.has(t.toLowerCase())) {
                seen.add(t.toLowerCase());
                texts.push(t);
            }
        }
        if (texts.length >= 2) return texts.slice(0, 50);
    }

    // ── Strategy 2: rw-list items (Paylocity-specific fallback) ────────
    const rwLists = document.querySelectorAll('.rw-list, [class*="rw-list"]');
    for (const rwList of rwLists) {
        const rect = rwList.getBoundingClientRect();
        if (rect.width <= 0 || rect.height <= 0) continue;
        const items = rwList.querySelectorAll('li, [class*="rw-list-option"]');
        if (items.length === 0) continue;

        const texts = [];
        const seen = new Set();
        for (const item of items) {
            const t = (item.textContent || '').trim();
            if (t && t !== '--' && !seen.has(t.toLowerCase())) {
                seen.add(t.toLowerCase());
                texts.push(t);
            }
        }
        if (texts.length >= 2) return texts.slice(0, 50);
    }

    // ── Strategy 3: generic proximity search (last resort) ─────────────
    const triggerRect = trigger.getBoundingClientRect();
    const options = [];
    const allEls = document.getElementsByTagName('*');
    for (let i = 0; i < allEls.length; i++) {
        const el = allEls[i];
        let directText = '';
        for (const node of el.childNodes) {
            if (node.nodeType === 3) directText += node.textContent;
        }
        directText = directText.trim();
        if (!directText || directText === '--' || directText.length > 100) continue;

        const rect = el.getBoundingClientRect();
        if (rect.width <= 0 || rect.height <= 0) continue;
        const style = window.getComputedStyle(el);
        if (style.display === 'none' || style.visibility === 'hidden') continue;

        const dy = rect.y - triggerRect.y;
        if (dy < -30) continue;
        const dx = Math.abs(rect.x - triggerRect.x);
        if (dx > 400) continue;

        const isInPopup = !!el.closest(
            '[class*="popup"], [class*="dropdown-menu"], ' +
            '[class*="menu"], [class*="overlay"], [class*="panel"], ' +
            '[role="listbox"], [role="menu"]'
        );

        options.push({text: directText, dist: dx + Math.abs(dy), isInPopup});
    }

    options.sort((a, b) => {
        const aS = (a.isInPopup ? 0 : 5000) + a.dist;
        const bS = (b.isInPopup ? 0 : 5000) + b.dist;
        return aS - bS;
    });

    const seen = new Set();
    const unique = [];
    for (const opt of options) {
        const key = opt.text.toLowerCase().trim();
        if (!seen.has(key)) {
            seen.add(key);
            unique.push(opt.text);
            if (unique.length >= 25) break;
        }
    }
    return unique;
}"""


def _set_paylocity_react_select(page, wrapper_id: str, label: str, value: str) -> bool:
    """Set a Paylocity pcty-input-select component via React fiber onChange.

    Paylocity's custom react-select ignores normal click/type/Enter
    interactions.  The only reliable way to set its value is to walk the
    React fiber tree and call the component's onChange with {label, value}.

    Returns True if the onChange was called successfully.
    """
    return page.evaluate("""(data) => {
        const wrapper = document.querySelector(data.wrapperId);
        if (!wrapper) return false;
        const fiberKey = Object.keys(wrapper).find(k => k.startsWith('__reactFiber'));
        if (!fiberKey) return false;

        // Collect ALL onChange handlers from the fiber tree
        let handlers = [];
        let current = wrapper[fiberKey];
        for (let d = 0; d < 25; d++) {
            if (!current) break;
            if (current.memoizedProps && current.memoizedProps.onChange) {
                handlers.push({fn: current.memoizedProps.onChange, hasOptions: !!current.memoizedProps.options});
            }
            current = current.return;
        }

        if (handlers.length === 0) return false;

        // Call from outermost to innermost so the store updates first.
        // Handlers WITH options (the form store) get {label, value}.
        // Handlers WITHOUT options (the InputBase display) get {value: label}
        // because InputBase extracts e.value for display text.
        const storeVal = {label: data.label, value: data.value};
        const displayVal = {label: data.label, value: data.label};
        for (let i = handlers.length - 1; i >= 0; i--) {
            try {
                handlers[i].fn(handlers[i].hasOptions ? storeVal : displayVal);
            } catch(e) {}
        }
        return true;
    }""", {"wrapperId": '#' + wrapper_id, "label": label, "value": value})


def fix_country_react_select(page, expected_country: str = "United States") -> bool:
    """Pre-fill fix: ensure the main address Country react-select is correct.

    Paylocity's resume parser sometimes flips the Country to a wrong value
    (e.g. "Seychelles") due to a race condition.  When the country is wrong
    the form switches to international address fields and City/State/Zip
    all fail.
    """
    COUNTRY_SEL = '#public-site-address-country'

    current = page.evaluate("""(sel) => {
        const input = document.querySelector(sel);
        if (!input) return null;
        let el = input;
        for (let i = 0; i < 8; i++) {
            el = el.parentElement;
            if (!el) break;
            const sv = el.querySelector('[class*="single-value"], [class*="singleValue"]');
            if (sv) return sv.textContent.trim();
        }
        return null;
    }""", COUNTRY_SEL)

    if current and current.lower() == expected_country.lower():
        return False  # already correct

    if current is None:
        return False  # field not found

    logger.info("Country is '%s', expected '%s' — fixing react-select", current, expected_country)
    try:
        _set_paylocity_react_select(page, 'public-site-address-country-select-wrapper',
                                    expected_country, 'USA')
        time.sleep(2)

        has_us_fields = page.evaluate("""() => {
            return !!document.querySelector('#public-site-address-us-state');
        }""")
        if has_us_fields:
            logger.info("Country fix applied — US address fields are present")
            return True
        else:
            logger.warning("Country fix failed — US address fields not found")
            return False
    except Exception as e:
        logger.warning("Country react-select fix failed: %s", e)
        return False


def fix_paylocity_react_selects(page, profile: dict) -> int:
    """Post-fill fix for ALL Paylocity pcty-input-select react-selects.

    After the fill loop, some react-selects may still show placeholder
    values because Paylocity's custom component ignores Enter/click for
    option selection.  This function detects unfilled react-selects and
    sets them via React fiber onChange.

    Must run AFTER all fills so no subsequent interactions undo the fix.
    """
    from job_bot.utils import parse_location

    personal = profile.get("personal", {})
    location = personal.get("location", "")
    loc = parse_location(location) if location else {}

    # Map of wrapper-id → (expected-label, expected-value)
    react_select_fixes = {}

    # Country
    react_select_fixes['public-site-address-country-select-wrapper'] = ('United States', 'USA')

    # State — map state full name to abbreviation
    state_full = loc.get('state_full', '')
    state_abbrev = loc.get('state_abbrev', '').upper()
    if state_full and state_abbrev:
        react_select_fixes['public-site-address-us-state-select-wrapper'] = (state_full, state_abbrev)

    fixed_count = 0
    for wrapper_id, (label, value) in react_select_fixes.items():
        # Check if the wrapper exists
        exists = page.evaluate("""(id) => !!document.querySelector('#' + id)""", wrapper_id)
        if not exists:
            continue

        # Check current displayed value
        current = page.evaluate("""(id) => {
            const wrapper = document.querySelector('#' + id);
            if (!wrapper) return null;
            const sv = wrapper.querySelector('[class*="single-value"]');
            return sv ? sv.textContent.trim() : null;
        }""", wrapper_id)

        if current and (current.lower() == label.lower()
                        or current.lower() == value.lower()):
            continue  # already correct (matches label OR abbreviation/value)

        logger.info("React-select %s: '%s' → '%s'", wrapper_id, current, label)
        ok = _set_paylocity_react_select(page, wrapper_id, label, value)
        if ok:
            fixed_count += 1
            time.sleep(0.5)

    if fixed_count:
        time.sleep(1)
        logger.info("Fixed %d Paylocity react-select(s)", fixed_count)
    return fixed_count


def fix_email_validation(page, email_value: str, max_attempts: int = 2) -> bool:
    """Post-fill fix for sticky email validation errors on React forms.

    Resume auto-fill can set a wrong email and trigger a validation error
    that persists even after retyping (because programmatic fill() corrupts
    React's internal DebounceInput state).  This function detects the error
    dynamically (any site, any email field) and retypes using pure keyboard
    events at human speed — the only approach that reliably clears it.

    Must run AFTER all other fields are filled so no subsequent fill()
    calls trigger React re-renders that undo the fix.
    """

    # ── Step 1: Dynamically find the email field ──
    # Look for any input that is type=email, or whose id/name/label
    # contains "email".  Works on any site, not just Paylocity.
    email_sel = page.evaluate("""() => {
        const candidates = document.querySelectorAll(
            'input[type="email"], input[id*="email" i], input[name*="email" i]'
        );
        for (const el of candidates) {
            if (el.offsetParent !== null) {  // visible
                return el.id ? '[id="' + el.id + '"]'
                     : el.name ? 'input[name="' + el.name + '"]'
                     : null;
            }
        }
        // Fallback: check data-for or aria-label attributes
        const all = document.querySelectorAll('input[type="text"]');
        for (const el of all) {
            const attr = (el.getAttribute('data-for') || el.getAttribute('aria-label') || '').toLowerCase();
            if (attr.includes('email') && el.offsetParent !== null) {
                return el.id ? '[id="' + el.id + '"]'
                     : el.name ? 'input[name="' + el.name + '"]'
                     : null;
            }
        }
        return null;
    }""")

    if not email_sel:
        return False  # no email field found

    # ── Step 2: Check for validation error near the email field ──
    def _has_validation_error() -> bool:
        return page.evaluate("""(sel) => {
            const el = document.querySelector(sel);
            if (!el) return false;
            // Walk up a few parents and look for error-like text
            let p = el.parentElement;
            for (let i = 0; i < 6; i++) {
                if (!p) break;
                const text = p.textContent.toLowerCase();
                if (text.includes('invalid email') || text.includes('invalid e-mail')
                    || text.includes('valid email') || text.includes('verify before')) {
                    return true;
                }
                p = p.parentElement;
            }
            // Also check for red/error-styled siblings
            const container = el.closest('.form-group') || el.parentElement;
            if (container) {
                const errEls = container.querySelectorAll('[class*="error"], [class*="invalid"], .text-danger');
                for (const e of errEls) {
                    if (e.textContent.toLowerCase().includes('email') && e.offsetHeight > 0) return true;
                }
            }
            return false;
        }""", email_sel)

    if not _has_validation_error():
        return False  # no fix needed

    # ── Step 3: Re-fill with pure keyboard events (retry up to max_attempts) ──
    for attempt in range(1, max_attempts + 1):
        logger.info("Email validation error detected — re-filling with keyboard events (attempt %d/%d)",
                     attempt, max_attempts)
        try:
            # Scroll into view
            page.evaluate("""(sel) => {
                const el = document.querySelector(sel);
                if (el) el.scrollIntoView({block: 'center'});
            }""", email_sel)
            time.sleep(0.3)

            el = page.locator(email_sel)
            el.click(timeout=5000)
            time.sleep(0.3)

            # Pure keyboard clear (no fill("") — that corrupts React state)
            page.keyboard.press("Control+a")
            time.sleep(0.05)
            page.keyboard.press("Meta+a")    # macOS
            time.sleep(0.05)
            page.keyboard.press("Backspace")
            time.sleep(0.5)

            # Type each character at human speed so DebounceInput
            # processes each keystroke and re-runs validation
            for char in email_value:
                page.keyboard.type(char)
                time.sleep(0.15)
            time.sleep(3)                    # let debounce settle
            page.keyboard.press("Tab")       # blur = final validation
            time.sleep(3)
        except Exception as e:
            logger.warning("Email validation fix attempt %d failed: %s", attempt, e)
            continue

        if not _has_validation_error():
            logger.info("Email validation error cleared (attempt %d)", attempt)
            return True

    logger.warning("Email validation error persists after %d attempts", max_attempts)
    return False


def fill_dropdowns_sweep(page, profile: dict) -> int:
    """
    Post-fill sweep using DOM inspection approach:
    1. Scan the entire DOM (including iframes) for ALL dropdown elements
    2. Log what's found for visibility
    3. For unfilled dropdowns, determine the answer from keyword rules
    4. Fill using Playwright select_option() or JS direct set
    """
    filled = 0
    try:
        # Step 1: Inspect the DOM to find all dropdown elements
        dropdowns = page.evaluate(FIND_DROPDOWNS_JS)
        total_selects = len(dropdowns)
        unfilled = [d for d in dropdowns if not d["isFilled"]]

        print(f"     >> DOM scan: {total_selects} dropdown(s) found, {len(unfilled)} unfilled")

        for dd in dropdowns:
            label_preview = dd["label"][:50] if dd["label"] else "(no label)"
            if not dd["isFilled"]:
                opt_preview = ", ".join(o["text"] for o in dd["options"][:5])
                print(f"        - [{dd['type']}] {label_preview} = '{dd['currentValue']}' | options: [{opt_preview}]")

        # Step 2: Fill unfilled dropdowns using dynamic answer determination
        for dd in unfilled:
            if not dd["selector"] or not dd["label"]:
                continue

            option_texts = [o["text"] for o in dd["options"]]
            answer = _determine_dropdown_answer(dd["label"], option_texts, profile)

            if not answer:
                print(f"     -- Skipping dropdown (no answer): {dd['label'][:50]}")
                continue

            # Find the matching option object
            best_option = None
            answer_lower = answer.lower().strip()
            for opt in dd["options"]:
                if opt["text"].lower().strip() == answer_lower:
                    best_option = opt
                    break
            if not best_option:
                for opt in dd["options"]:
                    opt_lower = opt["text"].lower().strip()
                    if answer_lower in opt_lower or opt_lower in answer_lower:
                        best_option = opt
                        break

            if not best_option:
                print(f"     !! No matching option for '{answer}' in {dd['label'][:40]}")
                continue

            # Fill the dropdown
            success = False
            selector = dd["selector"]

            if dd["type"] == "iframe-select":
                try:
                    adjusted_idx = dd.get("iframeIndex", 0) + 1  # +1 to skip main frame
                    if adjusted_idx >= len(page.frames):
                        logger.warning(
                            "Frame index %d out of range (total frames: %d) for %s",
                            adjusted_idx, len(page.frames), dd.get("label", "")[:40],
                        )
                        continue
                    frame = page.frames[adjusted_idx]
                    frame_el = frame.locator(selector)
                    frame_el.select_option(label=best_option["text"])
                    success = True
                except (TimeoutError, ValueError, IndexError) as e:
                    logger.debug("iframe-select label fill failed: %s", e)
                    try:
                        frame.evaluate(SELECT_JS_FILL, {"selector": selector, "answer": answer})
                        success = True
                    except (TimeoutError, ValueError) as e2:
                        logger.debug("iframe-select JS fill also failed: %s", e2)
            else:
                try:
                    el = page.locator(selector)
                    el.select_option(label=best_option["text"])
                    success = True
                except (TimeoutError, ValueError) as e:
                    logger.debug("Dropdown select_option by label failed for %s: %s", selector, e)

                if not success:
                    try:
                        el = page.locator(selector)
                        el.select_option(value=best_option["value"])
                        success = True
                    except (TimeoutError, ValueError) as e:
                        logger.debug("Dropdown select_option by value failed for %s: %s", selector, e)

                if not success:
                    try:
                        result = page.evaluate(SELECT_JS_FILL, {"selector": selector, "answer": answer})
                        if result:
                            success = True
                    except (TimeoutError, ValueError) as e:
                        logger.debug("Dropdown JS fill failed for %s: %s", selector, e)

            if success:
                print(f"     >> Dropdown: {dd['label'][:55]} -> {best_option['text']}")
                filled += 1
            else:
                print(f"     !! Dropdown failed: {dd['label'][:55]}")

        if not unfilled:
            print(f"     >> All dropdowns already filled")

    except Exception as e:
        logger.error("Dropdown sweep error: %s", e, exc_info=True)

    # Phase 2: Custom dropdown components (div-based, showing "--")
    # These are NOT <select> elements — they use divs/spans with click handlers.
    # Strategy: tag triggers with data-jobbot-dd, use Playwright locators
    # (auto-scroll + real click), then search ALL visible elements for options.
    try:
        custom_dds = page.evaluate(FIND_CUSTOM_DROPDOWNS_JS)
        if custom_dds:
            print(f"     >> Custom dropdown scan: {len(custom_dds)} dropdown(s) showing '--'")
            for dd in custom_dds:
                lbl = dd.get('label', '(no label)')[:60]
                print(f"        - [{dd['tagName']}] {lbl}")
                print(f"          html: {dd.get('triggerHtml', '')[:120]}")

        for dd in custom_dds:
            label = dd.get('label', '')
            if not label:
                continue

            # Click the dropdown trigger, read options, decide, then click
            try:
                selector = f'[data-jobbot-dd="{dd["index"]}"]'
                trigger = page.locator(selector)

                if trigger.count() == 0:
                    print(f"     !! Trigger element not found: {selector}")
                    continue

                trigger.scroll_into_view_if_needed()
                time.sleep(0.2)
                trigger.click(timeout=5000)
                time.sleep(0.8)  # Wait for dropdown panel to render

                # Read all visible option texts near the trigger
                # str() is intentional: JS uses it in attribute selector [data-jobbot-dd="X"]
                available_options = page.evaluate(
                    READ_DROPDOWN_OPTIONS_JS, str(dd["index"]))

                if available_options:
                    print(f"        Options found: {available_options[:8]}")
                else:
                    print(f"     !! No options visible for: {label[:40]}")
                    page.keyboard.press("Escape")
                    time.sleep(0.2)
                    continue

                # Dynamically determine the best answer
                answer = _determine_dropdown_answer(
                    label, available_options, profile)

                if not answer:
                    print(f"     -- Skipping custom dropdown (no answer): {label[:40]}")
                    print(f"        Options were: {available_options[:8]}")
                    page.keyboard.press("Escape")
                    time.sleep(0.2)
                    continue

                # Click the chosen option
                result = page.evaluate(
                    CLICK_DROPDOWN_OPTION_JS,
                    {"answers": [answer], "triggerIdx": str(dd["index"])})

                if result and result.get("clicked"):
                    print(f"     >> Custom dropdown: {label[:45]} -> {result.get('matched', '?')}")
                    filled += 1
                    time.sleep(0.3)
                else:
                    # Try Playwright text-based click as last resort
                    pw_clicked = False
                    try:
                        opt = page.get_by_text(answer, exact=True)
                        for j in range(min(opt.count(), 5)):
                            if opt.nth(j).is_visible():
                                opt.nth(j).click()
                                pw_clicked = True
                                print(f"     >> Custom dropdown (PW): {label[:40]} -> {answer}")
                                filled += 1
                                break
                    except (TimeoutError, ValueError) as e:
                        logger.debug("Custom dropdown Playwright text click failed for %s: %s", label[:40], e)

                    if not pw_clicked:
                        page.keyboard.press("Escape")
                        time.sleep(0.2)
                        debug_info = result.get("debug", "") if result else ""
                        print(f"     !! Custom dropdown: no match for {label[:40]}")
                        print(f"        tried: {answer}")
                        print(f"        debug: {debug_info}")
            except (TimeoutError, ValueError) as e:
                logger.warning("Custom dropdown error for %s: %s", label[:40], e)
                try:
                    page.keyboard.press("Escape")
                except (TimeoutError, ValueError) as esc_err:
                    logger.debug("Escape key press failed after dropdown error: %s", esc_err)

    except Exception as e:
        logger.error("Custom dropdown sweep error: %s", e, exc_info=True)

    return filled
