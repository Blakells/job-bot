"""Generic form filling: text fields, selects, toggles, file uploads."""

import time
from pathlib import Path


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


def fill_text_field(page, field_id, answer):
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
    except Exception as e:
        print(f"      !! Text fill error ({field_id}): {e}")
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

        except Exception as e:
            print(f"      >> Attach button method failed: {e}, trying direct input...")

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
        print(f"      !! Upload error ({input_id}): {e}")
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
        print(f"      !! File upload error: {e}")
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
            except Exception:
                pass

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
        except Exception:
            pass

        return False

    except Exception as e:
        print(f"      !! Toggle button error: {e}")
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
            txt_companion = cover_letter_path.replace(".pdf", ".txt")
            if Path(txt_companion).exists():
                try:
                    answer = Path(txt_companion).read_text()
                except Exception:
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
                except Exception:
                    pass

            # Strategy 2: Fuzzy option match via Playwright
            try:
                options = field.get("options", [])
                answer_lower = answer.lower().strip()
                for opt in options:
                    if answer_lower in opt.lower() or opt.lower() in answer_lower:
                        el.select_option(label=opt)
                        return True
            except Exception:
                pass

            # Strategy 3: JavaScript direct set (works on hidden/custom selects)
            try:
                result = page.evaluate(SELECT_JS_FILL, {"selector": selector, "answer": answer})
                if result:
                    print(f"      >> Used JS select fill -> {result}")
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
            answer_str = str(answer)
            try:
                el.click(timeout=5000)
                time.sleep(0.1)
                if len(answer_str) < 200:
                    # Short text: use type() to fire real keyboard events.
                    # This triggers React validation (onChange, onKeyUp, etc.)
                    # that Playwright's .fill() alone does not.
                    el.press("Control+a")
                    el.type(answer_str, delay=12)
                else:
                    # Long text: use fill() for speed, then nudge React
                    el.fill(answer_str)
            except Exception:
                try:
                    page.evaluate(REACT_NATIVE_FILL_JS, {"selector": selector, "value": answer_str})
                    print(f"      >> Used JS fill (overlay was blocking)")
                except Exception as js_err:
                    print(f"      !! JS fill also failed: {js_err}")
                    return False
            try:
                el.press("Tab")
                time.sleep(0.2)
            except Exception:
                pass
            return True

    except Exception as e:
        if selector:
            try:
                page.evaluate(REACT_NATIVE_FILL_JS, {"selector": selector, "value": str(answer)})
                print(f"      >> Used JS fill fallback for {field.get('label', '')}")
                return True
            except Exception:
                pass
        print(f"      !! Could not fill {field.get('label', '')}: {e}")
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


def fill_toggle_buttons_sweep(page, profile):
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
        print(f"     !! Toggle sweep error: {e}")
        return 0
