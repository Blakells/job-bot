"""Form field extraction: JavaScript-based DOM parsing for any ATS platform."""

import re
from pathlib import Path

from job_bot.ai import ask_claude, parse_json_response
from job_bot.config import STATE_MAP


# ── JavaScript to extract ALL form fields from any page ──────────────────────

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

        // 5. aria-describedby
        if (!label) {
            const describedBy = el.getAttribute('aria-describedby');
            if (describedBy) {
                const ref = document.getElementById(describedBy);
                if (ref) label = ref.innerText.trim();
            }
        }

        // 6. data-* attributes
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

        // 8. Preceding siblings
        if (!label) {
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

        // 9. Parent container
        if (!label) {
            const wrapper = el.closest('.field, .form-group, .form-field, .form-row, ' +
                '.question, .field-group, .input-group, .MuiFormControl-root, ' +
                '[class*="field"], [class*="question"], [class*="form-group"]');
            if (wrapper) {
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

        // 10. Section header (context only, not primary label)
        // Skipped — too noisy as a primary label

        // 11. Name attribute as final fallback
        if (!label && el.name) {
            label = el.name.replace(/[_\\-\\[\\]\\d]+/g, ' ')
                          .replace(/([a-z])([A-Z])/g, '$1 $2')
                          .trim();
        }

        label = label.replace(/\\*/g, '').replace(/\\(required\\)/gi, '').replace(/\\s+/g, ' ').trim();
        return label.slice(0, 200);
    }

    function getOptions(el) {
        if (el.tagName === 'SELECT') {
            return Array.from(el.options).map(o => o.text.trim()).filter(t => t && t !== '' && t !== 'Select' && t !== 'Choose');
        }
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
        const ctx = {};
        const parent = el.closest('[class]');
        if (parent) ctx.parentClass = parent.className.slice(0, 200);
        const section = el.closest('section, fieldset, [role="group"]');
        if (section) {
            const heading = section.querySelector('h1, h2, h3, h4, legend, .section-title');
            if (heading) ctx.section = heading.innerText.trim().slice(0, 100);
        }
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
    document.querySelectorAll('input, select, textarea').forEach(el => {
        const type = el.type || el.tagName.toLowerCase();
        if (['hidden', 'submit', 'button', 'image', 'reset'].includes(type)) return;
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

    // Scan for YES/NO toggle button groups
    const toggleSeen = new Set();
    document.querySelectorAll('button, [role="button"]').forEach(btn => {
        const text = (btn.textContent || '').trim().toUpperCase();
        if (text !== 'YES' && text !== 'NO') return;
        if (!isVisible(btn)) return;

        const container = btn.closest('[class*="question"], [class*="toggle"], [class*="field"], [class*="group"]')
                       || btn.parentElement?.parentElement;
        if (!container) return;

        let questionText = '';
        const textEls = container.querySelectorAll('span, p, div, label, h3, h4');
        for (const tel of textEls) {
            const t = tel.innerText.trim();
            if (t && t.length > 5 && t !== 'YES' && t !== 'NO' && !t.match(/^(YES|NO)$/i)) {
                questionText = t.replace(/\\*/g, '').trim();
                break;
            }
        }
        if (!questionText) return;

        if (toggleSeen.has(questionText)) return;
        toggleSeen.add(questionText);

        const buttons = container.querySelectorAll('button, [role="button"]');
        let yesSelector = null, noSelector = null;
        for (const b of buttons) {
            const bt = (b.textContent || '').trim().toUpperCase();
            if (bt === 'YES' || bt.includes('YES')) {
                yesSelector = b.id ? '#' + CSS.escape(b.id) :
                    b.getAttribute('data-ui') ? '[data-ui="' + b.getAttribute('data-ui') + '"]' : null;
                if (!yesSelector) {
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
    """Extract all form fields from any page using JavaScript injection."""
    try:
        fields = page.evaluate(EXTRACT_FIELDS_JS)
        return [f for f in fields if f.get("label") or f.get("id") or f.get("name")]
    except Exception as e:
        print(f"  !! Could not extract fields: {e}")
        return []


def is_greenhouse_form(page):
    """Detect if the current page is a Greenhouse job board application."""
    url = page.url.lower()
    if "greenhouse.io" in url:
        return True
    try:
        has_gh = page.locator("div.application--questions").count() > 0
        if has_gh:
            return True
        has_gh = page.locator("div[class*='select-shell'][class*='remix-css']").count() > 0
        return has_gh
    except Exception:
        return False


def parse_greenhouse_fields(page):
    """
    Parse ALL form fields from a Greenhouse application page by reading the DOM.
    No LLM needed — the structure is deterministic.
    """
    fields = page.evaluate("""() => {
        const results = [];

        // 1. React-Select dropdowns
        document.querySelectorAll('input[role="combobox"]').forEach(input => {
            if (input.closest('.iti__dropdown-content')) return;
            const id = input.id;
            if (!id) return;
            const labelEl = document.querySelector('label[for="' + id + '"]');
            const label = labelEl ? labelEl.textContent.replace(/\\*/g, '').trim() : id;
            const required = input.getAttribute('aria-required') === 'true';
            results.push({ id, label, type: 'react-select', required });
        });

        // 2. Standard text/email/tel inputs
        document.querySelectorAll('input.input.input__single-line').forEach(input => {
            const id = input.id;
            if (!id) return;
            const labelEl = document.querySelector('label[for="' + id + '"]');
            const label = labelEl ? labelEl.textContent.replace(/\\*/g, '').trim() : id;
            const required = input.getAttribute('aria-required') === 'true';
            const inputType = input.type || 'text';
            results.push({ id, label, type: inputType === 'tel' ? 'tel' : 'text', required });
        });

        // 3. File upload inputs
        document.querySelectorAll('input[type="file"]').forEach(input => {
            const id = input.id;
            if (!id) return;
            const group = input.closest('.file-upload');
            const labelEl = group ? group.querySelector('.upload-label') : null;
            const label = labelEl ? labelEl.textContent.replace(/\\*/g, '').trim() : id;
            const required = group ? group.getAttribute('aria-required') === 'true' : false;
            results.push({ id, label, type: 'file', required });
        });

        return results;
    }""")
    return fields


def claude_map_fields(fields, profile, job):
    """
    Ask Claude to map form fields to profile answers.
    Only called for fields that weren't auto-matched by build_answer_map.
    """
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

    work_history = profile.get("work_history", [])
    work_hist_str = ""
    for wh in work_history[:3]:
        work_hist_str += "\n  - {} at {} ({})".format(
            wh.get("title", ""), wh.get("company", ""), wh.get("duration", ""))

    location = profile["personal"].get("location", "")
    city = location.split(",")[0].strip()
    state_raw = location.split(",")[-1].strip().lower()
    state_full = STATE_MAP.get(state_raw, state_raw).title()
    zip_code = profile["personal"].get("zip_code", "")
    street_address = profile["personal"].get("street_address", "")
    county = profile["personal"].get("county", city)
    salary_min = profile.get("salary_range", {}).get("min", 0)
    salary_max = profile.get("salary_range", {}).get("max", 0)
    if salary_min and not salary_max:
        salary_max = int(salary_min * 1.5)

    # Normalize LinkedIn URL for forms that require full URL
    linkedin_url = profile["personal"].get("linkedin_url", "")
    if linkedin_url and not linkedin_url.startswith("http"):
        linkedin_url = "https://www." + linkedin_url if not linkedin_url.startswith("www.") else "https://" + linkedin_url

    eeoc = profile.get("eeoc", {})
    gender = eeoc.get("gender", "Male")

    prompt = """You are filling out a job application form. Map the candidate's profile data to ALL fields you can answer.

## CANDIDATE PROFILE:
Name: {name}
Email: {email}
Phone: {phone}
Location: {location} (Street: {street_address}, City: {city}, County: {county}, State: {state_full}, Zip: {zip_code}, Country: United States)
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
- Answer EVERY field you can, not just required ones
- For file upload fields: use "RESUME_FILE" or "COVER_LETTER_FILE"
- For textarea fields about cover letter: use "COVER_LETTER_TEXT"
- For select/dropdown fields: pick the EXACT text from the options list
- For yes/no work authorization questions: "Yes" for authorized, "No" for needs sponsorship
- For "how did you hear" type questions: "LinkedIn"
- For EEOC gender: "{gender}"
- For EEOC/demographic fields (race, veteran, disability): use the closest declining option
- For address line / street address fields: "{street_address}"
- For county fields: "{county}"
- For city fields: just "{city}"
- For state fields: "{state_full}"
- For country fields: "United States"
- For zip code fields: "{zip_code}"
- For minimum salary / salary fields: "{salary_min}"
- For maximum salary fields: "{salary_max}"
- For salary type fields: "Yearly" or "Annual" (pick the matching option)
- For "have you applied before" type fields: "No"
- For SMS/text permission fields: "Yes"
- For years of experience: "{years}"
- Do NOT fabricate information or make up answers

Return ONLY the JSON object, no explanation.""".format(
        name=profile["personal"].get("name", ""),
        email=profile["personal"].get("email", ""),
        phone=profile["personal"].get("phone", ""),
        location=location,
        street_address=street_address,
        city=city,
        county=county,
        state_full=state_full,
        linkedin=linkedin_url,
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
        salary_min=str(salary_min) if salary_min else "",
        salary_max=str(salary_max) if salary_max else "",
        gender=gender,
        zip_code=zip_code,
        fields="\n".join(field_descriptions),
    )

    raw = ask_claude(prompt)
    if not raw:
        return {}

    result = parse_json_response(raw)
    return result if isinstance(result, dict) else {}
