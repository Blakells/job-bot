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

            # Skip if field already has the correct value (avoids breaking
            # pre-filled react-select/autocomplete fields like Country)
            try:
                current_value = el.input_value() or ""
                if current_value.strip().lower() == answer_str.strip().lower():
                    return True

                # React-select / autocomplete: the <input> is for searching
                # and may be empty, but the *displayed* value lives in a
                # sibling span.  Check the parent container's visible text.
                if not current_value.strip() and selector:
                    displayed = page.evaluate("""(sel) => {
                        const el = document.querySelector(sel);
                        if (!el) return '';
                        let c = el.parentElement;
                        for (let i = 0; i < 5 && c; i++) {
                            const cls = (c.className || '').toString().toLowerCase();
                            if (cls.includes('select') || cls.includes('combobox') ||
                                cls.includes('dropdown') || cls.includes('autocomplete')) {
                                const v = c.querySelector(
                                    '[class*="singleValue"], [class*="value"]:not(input), ' +
                                    '[class*="selected"], [class*="display"]');
                                if (v) return v.textContent.trim();
                                // fallback: any direct-child span with text
                                for (const ch of c.querySelectorAll(':scope > div > span, :scope > span')) {
                                    const t = ch.textContent.trim();
                                    if (t && t.length > 1 && t !== '--') return t;
                                }
                            }
                            c = c.parentElement;
                        }
                        return '';
                    }""", selector)
                    if displayed and displayed.strip().lower() == answer_str.strip().lower():
                        print(f"      >> Skipping (react-select already shows: {displayed})")
                        return True
            except Exception:
                pass

            # Detect react-select / autocomplete inputs
            is_autocomplete = False
            try:
                role = el.get_attribute("role") or ""
                aria_auto = el.get_attribute("aria-autocomplete") or ""
                parent_class = field.get("parentClass", "").lower()
                if (role == "combobox" or aria_auto
                        or "react-select" in parent_class
                        or "autocomplete" in parent_class
                        or "combobox" in parent_class):
                    is_autocomplete = True
            except Exception:
                pass

            try:
                el.click(timeout=5000)
                time.sleep(0.1)

                # Detect email fields for special React-compatible fill
                is_email = (field_type == 'email' or
                            'email' in field.get('id', '').lower() or
                            'email' in field.get('name', '').lower())

                if is_autocomplete:
                    # Autocomplete/react-select: type search + Enter to select
                    el.fill("")
                    el.type(answer_str, delay=50)
                    time.sleep(0.5)
                    el.press("Enter")
                    time.sleep(0.3)
                elif is_email and selector:
                    # Email: avoid clearing a form-auto-filled value.
                    # If already correct → just fire validation events.
                    # Otherwise → type it once (no fill("") clear first).
                    cur = ""
                    try:
                        cur = el.input_value() or ""
                    except Exception:
                        pass

                    if cur.strip().lower() == answer_str.strip().lower():
                        # Already correct — just retrigger validation
                        print(f"      >> Email already correct, triggering validation")
                    else:
                        # Type the email fresh (only type, no clear)
                        el.type(answer_str, delay=20)
                        time.sleep(0.3)

                    # Native setter + events to sync React state & clear errors
                    try:
                        page.evaluate("""(args) => {
                            const el = document.querySelector(args.selector);
                            if (!el) return;
                            const nativeSetter = Object.getOwnPropertyDescriptor(
                                window.HTMLInputElement.prototype, 'value').set;
                            nativeSetter.call(el, args.value);
                            el.dispatchEvent(new InputEvent('input', {
                                bubbles: true, inputType: 'insertText', data: args.value
                            }));
                            el.dispatchEvent(new Event('change', {bubbles: true}));
                        }""", {"selector": selector, "value": answer_str})
                    except Exception:
                        pass
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


# ── Dropdown sweep: DOM-inspection approach ──────────────────────────────────
# Scans the full DOM for ALL dropdown-like elements (<select>, custom components),
# analyzes their structure, determines the right answer, and fills them.

DROPDOWN_ANSWER_RULES = {
    # keyword in question → list of acceptable answers (tried in order)
    "salary type": ["Yearly", "Annual", "Annually", "Year", "Salary"],
    "desired salary type": ["Yearly", "Annual", "Annually", "Year", "Salary"],
    "pay type": ["Yearly", "Annual", "Annually", "Year", "Salary"],
    "compensation type": ["Yearly", "Annual", "Annually", "Year", "Salary"],
    "applied for a job": ["No"],
    "applied with us": ["No"],
    "applied before": ["No"],
    "worked with us": ["No"],
    "worked here before": ["No"],
    "have you applied": ["No"],
    "have you worked": ["No"],
    "permission to text": ["Yes"],
    "sms": ["Yes"],
    "text you": ["Yes"],
    "text message": ["Yes"],
    "contact you via text": ["Yes"],
}

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


# JS that finds custom (div-based) dropdown components by looking for
# visible elements that display "--" as their text content.
# Returns their labels and click coordinates for Playwright interaction.
FIND_CUSTOM_DROPDOWNS_JS = """() => {
    const results = [];
    const seen = new Set();

    // Walk all text nodes looking for exact "--" content
    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    while (walker.nextNode()) {
        const textNode = walker.currentNode;
        if (textNode.textContent.trim() !== '--') continue;

        const el = textNode.parentElement;
        if (!el) continue;

        // Must be visible and reasonable size
        const rect = el.getBoundingClientRect();
        if (rect.width < 20 || rect.height < 10) continue;

        const style = window.getComputedStyle(el);
        if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') continue;

        // Skip if inside a <select> element (handled by Phase 1)
        if (el.closest('select')) continue;

        // Dedup by approximate position
        const posKey = Math.round(rect.x / 10) + '_' + Math.round(rect.y / 10);
        if (seen.has(posKey)) continue;
        seen.add(posKey);

        // Find the best clickable ancestor (the dropdown trigger)
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

        const clickRect = clickTarget.getBoundingClientRect();

        // Find the associated label by walking up the DOM
        let label = '';

        // Check aria-label / aria-labelledby on the click target or ancestors
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

        // Walk up DOM to find question/label text
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
                        label = txt;
                        break;
                    }
                }

                // Check explicit label[for]
                if (!label && parent.id) {
                    const expl = document.querySelector('label[for="' + parent.id + '"]');
                    if (expl) label = expl.innerText.replace(/\\*/g, '').trim();
                }

                parent = parent.parentElement;
            }
        }

        results.push({
            label: label || '',
            clickX: Math.round(clickRect.x + clickRect.width / 2),
            clickY: Math.round(clickRect.y + clickRect.height / 2),
            tagName: clickTarget.tagName,
        });
    }

    return results;
}"""

# JS that finds and clicks a dropdown option after the dropdown is opened.
# Uses fuzzy matching: exact → starts-with → contains → partial.
# Returns {clicked: bool, debug: str} with info about what was found.
CLICK_DROPDOWN_OPTION_JS = """(args) => {
    const answers = args.answers;   // list of acceptable answers
    const debug = [];

    // Collect ALL visible candidate elements that could be options
    const candidates = [];

    // Gather from role="option", li, class*="option", etc.
    const selectorList = '[role="option"], [role="menuitem"], li, [class*="option"], [class*="item"], [class*="choice"]';
    document.querySelectorAll(selectorList).forEach(el => {
        const text = el.textContent.trim();
        if (!text || text === '--') return;
        const rect = el.getBoundingClientRect();
        if (rect.width <= 0 || rect.height <= 0) return;
        const style = window.getComputedStyle(el);
        if (style.display === 'none' || style.visibility === 'hidden') return;

        // Check if in a popup/overlay
        let isPopup = false;
        let p = el.parentElement;
        for (let i = 0; i < 5 && p; i++) {
            const ps = window.getComputedStyle(p);
            const role = p.getAttribute('role');
            if (ps.position === 'absolute' || ps.position === 'fixed' ||
                role === 'listbox' || role === 'menu' ||
                (p.className || '').toString().match(/dropdown|popup|overlay|menu|popover|modal/i)) {
                isPopup = true; break;
            }
            p = p.parentElement;
        }
        candidates.push({el, text, isPopup});
    });

    debug.push('Found ' + candidates.length + ' option candidates');
    const popupOpts = candidates.filter(c => c.isPopup);
    debug.push('Popup options: ' + popupOpts.map(c => c.text).join(', '));
    if (popupOpts.length === 0) {
        debug.push('Non-popup: ' + candidates.slice(0, 10).map(c => c.text).join(', '));
    }

    // Search targets: prefer popup candidates, fall back to all
    const searchPool = popupOpts.length > 0 ? popupOpts : candidates;

    // Try each answer candidate with progressively fuzzier matching
    for (const answer of answers) {
        const ansLower = answer.toLowerCase().trim();

        // Pass 1: exact match
        for (const c of searchPool) {
            if (c.text === answer || c.text.toLowerCase().trim() === ansLower) {
                c.el.click();
                return {clicked: true, matched: c.text, debug: debug.join(' | ')};
            }
        }
        // Pass 2: option starts with answer or answer starts with option
        for (const c of searchPool) {
            const tl = c.text.toLowerCase().trim();
            if (tl.startsWith(ansLower) || ansLower.startsWith(tl)) {
                c.el.click();
                return {clicked: true, matched: c.text, debug: debug.join(' | ')};
            }
        }
        // Pass 3: contains (either direction)
        for (const c of searchPool) {
            const tl = c.text.toLowerCase().trim();
            if (tl.includes(ansLower) || ansLower.includes(tl)) {
                c.el.click();
                return {clicked: true, matched: c.text, debug: debug.join(' | ')};
            }
        }
    }

    return {clicked: false, matched: null, debug: debug.join(' | ')};
}"""


def fill_dropdowns_sweep(page, profile):
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

        # Step 2: Fill unfilled dropdowns
        for dd in unfilled:
            if not dd["selector"] or not dd["label"]:
                continue

            label_lower = dd["label"].lower().replace("*", "").strip()

            # Determine answer candidates from keyword rules
            answer_candidates = None
            for keyword, ans_list in DROPDOWN_ANSWER_RULES.items():
                if keyword in label_lower:
                    answer_candidates = ans_list
                    break

            if not answer_candidates:
                continue

            # Find the best matching option (try each candidate)
            best_option = None
            answer = answer_candidates[0]  # default for logging
            for candidate in answer_candidates:
                cand_lower = candidate.lower()
                for opt in dd["options"]:
                    opt_lower = opt["text"].lower().strip()
                    if opt_lower == cand_lower or cand_lower in opt_lower or opt_lower in cand_lower:
                        best_option = opt
                        answer = candidate
                        break
                if best_option:
                    break

            if not best_option:
                print(f"     !! No matching option for {answer_candidates} in {dd['label'][:40]}")
                continue

            # Fill the dropdown
            success = False
            selector = dd["selector"]

            if dd["type"] == "iframe-select":
                # Fill inside iframe
                try:
                    frame = page.frames[dd["iframeIndex"] + 1]  # +1 for main frame
                    frame_el = frame.locator(selector)
                    frame_el.select_option(label=best_option["text"])
                    success = True
                except Exception:
                    try:
                        frame.evaluate(SELECT_JS_FILL, {"selector": selector, "answer": answer})
                        success = True
                    except Exception:
                        pass
            else:
                # Fill on main page — try Playwright first, then JS
                try:
                    el = page.locator(selector)
                    el.select_option(label=best_option["text"])
                    success = True
                except Exception:
                    pass

                if not success:
                    try:
                        el = page.locator(selector)
                        el.select_option(value=best_option["value"])
                        success = True
                    except Exception:
                        pass

                if not success:
                    try:
                        result = page.evaluate(SELECT_JS_FILL, {"selector": selector, "answer": answer})
                        if result:
                            success = True
                    except Exception:
                        pass

            if success:
                print(f"     >> Dropdown: {dd['label'][:55]} -> {best_option['text']}")
                filled += 1
            else:
                print(f"     !! Dropdown failed: {dd['label'][:55]}")

        if not unfilled:
            print(f"     >> All dropdowns already filled")

    except Exception as e:
        print(f"     !! Dropdown sweep error: {e}")

    # Phase 2: Custom dropdown components (div-based, showing "--")
    # These are NOT <select> elements — they use divs/spans with click handlers.
    # Strategy: find "--" text nodes, click to open, then click the correct option.
    try:
        custom_dds = page.evaluate(FIND_CUSTOM_DROPDOWNS_JS)
        if custom_dds:
            print(f"     >> Custom dropdown scan: {len(custom_dds)} dropdown(s) showing '--'")

        for dd in custom_dds:
            label = dd.get('label', '')
            if not label:
                print(f"        - '--' at ({dd['clickX']}, {dd['clickY']}) - no label, skipping")
                continue

            # Match label against answer rules
            label_lower = label.lower().replace('*', '').strip()
            answer_candidates = None
            for keyword, ans_list in DROPDOWN_ANSWER_RULES.items():
                if keyword in label_lower:
                    answer_candidates = ans_list
                    break

            if not answer_candidates:
                print(f"        - {label[:50]} - no matching rule")
                continue

            # Click the dropdown trigger to open it
            try:
                page.mouse.click(dd['clickX'], dd['clickY'])
                time.sleep(0.6)

                # Try to find and click the matching option (fuzzy matching)
                result = page.evaluate(
                    CLICK_DROPDOWN_OPTION_JS,
                    {"answers": answer_candidates})

                if result and result.get("clicked"):
                    print(f"     >> Custom dropdown: {label[:45]} -> {result.get('matched', '?')}")
                    filled += 1
                    time.sleep(0.3)
                else:
                    page.keyboard.press("Escape")
                    time.sleep(0.2)
                    debug_info = result.get("debug", "") if result else ""
                    print(f"     !! Custom dropdown: no match for {label[:40]}")
                    print(f"        tried: {answer_candidates}")
                    print(f"        debug: {debug_info}")
            except Exception as e:
                print(f"     !! Custom dropdown click error: {e}")
                try:
                    page.keyboard.press("Escape")
                except Exception:
                    pass

    except Exception as e:
        print(f"     !! Custom dropdown sweep error: {e}")

    return filled
