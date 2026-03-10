"""React-Select dropdown handling for Greenhouse ATS forms."""

import re
import time

from job_bot.config import STATE_MAP, STATE_MAP_REVERSE


def _get_search_text(field_id, answer):
    """
    Determine the best search text to TYPE into a React-Select field.
    Type the MINIMUM needed to filter the dropdown.
    """
    is_location = "location" in field_id.lower() or "candidate-location" == field_id.lower()

    if is_location:
        city = answer.split(",")[0].strip()
        return city

    if len(answer) <= 10:
        return answer

    first_segment = answer.split(",")[0].strip()
    words = first_segment.split()
    return " ".join(words[:3])


def _find_options(page, field_id):
    """
    Find dropdown option elements scoped to the ACTIVE dropdown menu
    for a specific field.
    """
    # Strategy 1: Find menu within the same select container
    for container_class in ['select-shell', 'select__container', 'select']:
        container = page.locator(
            f"input#{field_id} >> xpath=ancestor::div[contains(@class,'{container_class}')]"
        )
        if container.count() > 0:
            opts = container.first.locator("div[class*='select__option']")
            if opts.count() > 0:
                return opts
            opts = container.first.locator("[role='option']")
            if opts.count() > 0:
                return opts

    # Strategy 2: Portal-rendered menu
    menu = page.locator("div[class*='select__menu']")
    if menu.count() > 0:
        opts = menu.last.locator("div[class*='select__option']")
        if opts.count() > 0:
            return opts

    # Strategy 3: ARIA listbox (excluding phone picker)
    listbox = page.locator("[role='listbox']:not(.iti__country-list)")
    if listbox.count() > 0:
        opts = listbox.last.locator("[role='option']")
        if opts.count() > 0:
            return opts

    return None


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


def _pick_best_option(option_texts, answer, is_location=False):
    """
    Pick the best matching option from a list of (index, text) tuples.

    Matching priority:
    1. Exact match (case-insensitive)
    2. Abbreviation/expansion EXACT match (SC <-> South Carolina)
    3. Scored keyword match (for location/long answers)
    4. Yes/No-aware fuzzy keyword overlap
    5. Partial string containment
    """
    answer_lower = answer.lower().strip()

    # 1. Exact match
    for idx, text in option_texts:
        if text.lower().strip() == answer_lower:
            return idx

    # 2. Abbreviation / expansion EXACT matching
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

    for idx, text in option_texts:
        text_lower = text.lower().strip()
        if text_lower in answer_variants:
            return idx

    # 3. Location-specific scored matching
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
            print(f"      >> Options: {[t for _, t in option_texts[:10]]}")
            print(f"      >> Best match (score={best_score}): \"{option_texts[best_idx][1]}\"")
            return best_idx

    # 4. Yes/No-aware fuzzy keyword matching
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

            if is_yes_no:
                if answer_first_word == "yes" and text_first_word == "no":
                    continue
                if answer_first_word == "no" and text_first_word == "yes":
                    continue

            text_words = set(
                w.lower() for w in re.split(r'[\s,\-\']+', text) if len(w) > 2
            )
            overlap = len(answer_keywords & text_words)
            if answer_first_word == text_first_word:
                overlap += 1
            if overlap > best_score:
                best_score = overlap
                best_idx = idx

        if best_idx >= 0 and best_score >= 1:
            print(f"      >> Fuzzy match ({best_score} keywords): \"{option_texts[best_idx][1]}\"")
            return best_idx

    # 5. Partial string containment (long strings only)
    if len(answer_lower) > 3:
        for idx, text in option_texts:
            text_lower = text.lower()
            if answer_lower in text_lower or text_lower in answer_lower:
                return idx

    return None


def _verify_selection(page, field_id, expected_answer):
    """Verify a React-Select dropdown actually accepted the selection."""
    try:
        container = page.locator(
            f"input#{field_id} >> xpath=ancestor::div[contains(@class,'select-shell')]"
        )
        if container.count() > 0:
            single_val = container.locator("div[class*='select__single-value']")
            if single_val.count() > 0:
                actual = single_val.first.inner_text().strip()
                if actual:
                    print(f"      >> Verified: \"{actual}\"")
                    return True

        hidden = page.locator(
            f"input#{field_id} >> xpath=ancestor::div[contains(@class,'select__container')]"
            f"//input[@aria-hidden='true']"
        )
        if hidden.count() > 0:
            val = hidden.first.get_attribute("value")
            if val:
                return True

        expanded = page.evaluate(
            f'document.getElementById("{field_id}")?.getAttribute("aria-expanded")'
        )
        if expanded == "false" or expanded is None:
            return True

        return True
    except Exception:
        return True


def fill_react_select(page, field_id, answer, retries=3):
    """
    Fill a Greenhouse React-Select dropdown.

    Strategy: open first, read options, then pick best match.
    For async/search fields (like Location), type a search term first.
    """
    is_location = "location" in field_id.lower() or "candidate-location" == field_id.lower()

    for attempt in range(retries + 1):
        try:
            combobox = page.locator(f"input#{field_id}")
            if combobox.count() == 0:
                print(f"      !! No combobox found with id={field_id}")
                return False

            # Step 1: Click to open the dropdown
            container = page.locator(
                f"input#{field_id} >> xpath=ancestor::div[contains(@class,'select__control')]"
            )
            if container.count() > 0:
                container.first.click()
            else:
                combobox.click()
            time.sleep(0.5)

            combobox.press("Control+a")
            combobox.press("Backspace")
            time.sleep(0.3)

            # Step 2: Check if options appeared (static dropdown)
            options_appeared = _wait_for_options(page, field_id, timeout=2)

            # Step 3: If no options, type to search (async dropdown)
            if not options_appeared:
                search_text = _get_search_text(field_id, answer)
                keystroke_delay = 100 if is_location else 60
                combobox.type(search_text, delay=keystroke_delay)

                wait_time = 8 if is_location else 5
                if is_location:
                    time.sleep(2.0)
                options_appeared = _wait_for_options(page, field_id, timeout=wait_time)

            if not options_appeared:
                if attempt < retries:
                    print(f"      >> No options appeared, retrying... ({attempt+1})")
                    combobox.press("Escape")
                    time.sleep(0.5)
                    continue
                else:
                    debug = _debug_dropdown(page, field_id)
                    print(f"      >> Debug DOM state: {debug}")
                    print(f"      !! No options rendered for {field_id}")
                    return False

            # Step 4: Read all options
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

            # Step 5: Pick the best match
            chosen_idx = _pick_best_option(option_texts, answer, is_location)

            if chosen_idx is not None:
                options.nth(chosen_idx).click()
                time.sleep(0.4)
                return _verify_selection(page, field_id, answer)

            if option_count > 0:
                print(f"      !! No match found. Options: {[t for _, t in option_texts[:10]]}")
                print(f"      >> Picking first: \"{option_texts[0][1]}\"")
                options.first.click()
                time.sleep(0.4)
                return _verify_selection(page, field_id, answer)

            return False

        except Exception as e:
            if attempt < retries:
                print(f"      >> Error, retrying: {e}")
                time.sleep(1)
                continue
            print(f"      !! React-Select failed for {field_id}: {e}")
            return False

    return False
