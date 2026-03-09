#!/usr/bin/env python3
"""
Code Snippets for Opus - Key Functions That Need Debugging
"""

# ============================================================================
# WORKING: fill_react_select() - Partially working (5/9 dropdowns)
# ============================================================================
def fill_react_select(page, label, answer):
    """Fill React-Select dropdown - TYPE into search input first!"""
    try:
        # Find label element
        label_el = page.locator(f"label:has-text('{label}')").first
        
        # Try fuzzy match if exact fails
        if label_el.count() == 0:
            key_words = [w for w in label.split() if len(w) > 4][:3]
            for word in key_words:
                label_el = page.locator(f"label:has-text('{word}')").first
                if label_el.count() > 0:
                    break
        
        if label_el.count() > 0:
            for_id = label_el.get_attribute("for")
            if for_id:
                # Find combobox by ID
                combobox = page.locator(f"#{for_id}")
                if combobox.count() > 0:
                    # Step 1: Click to open dropdown
                    combobox.click()
                    time.sleep(0.5)
                    
                    # Step 2: TYPE into the search input that appears!
                    # This is the CRITICAL step
                    search_input = page.locator(f"input#{for_id}")
                    if search_input.count() > 0:
                        search_input.type(answer, delay=50)
                        time.sleep(0.8)  # Wait for options to filter
                    
                    # Step 3: Click the matching option
                    option = page.get_by_text(answer, exact=True).first
                    if option.count() > 0 and option.is_visible():
                        option.click()
                        time.sleep(0.5)
                        return True
                    
                    # Fallback: try partial match
                    option = page.locator(f"div[class*='option']:has-text('{answer}')").first
                    if option.count() > 0 and option.is_visible():
                        option.click()
                        time.sleep(0.5)
                        return True
        
        return False
    except Exception as e:
        print(f"    React-Select error: {e}")
        return False

# STATUS: Working for Country, Visa, Gender, Veteran, Disability
# FAILING for: Work Authorization, Hispanic/Latino, Secret Clearance
# NEEDS: Debug why search_input.type() isn't working for those specific fields


# ============================================================================
# BROKEN: fill_autocomplete() - Location field doesn't work
# ============================================================================
def fill_autocomplete(page, label, answer):
    """Fill Location autocomplete field - CURRENTLY BROKEN"""
    try:
        # Find field
        autocomplete = page.get_by_label(label, exact=False)
        
        if autocomplete.count() == 0:
            label_el = page.locator(f"label:has-text('{label}')").first
            if label_el.count() == 0:
                label_el = page.locator("label:has-text('Location')").first
            
            if label_el.count() > 0:
                input_id = label_el.get_attribute("for")
                if input_id:
                    autocomplete = page.locator(f"#{input_id}")
        
        if autocomplete.count() > 0:
            # Type partial location
            partial = answer
            if ", " in answer:
                city, state = answer.split(", ", 1)
                partial = f"{city}, {state[0]}"  # "Florence, S"
            
            autocomplete.click()
            time.sleep(0.5)
            autocomplete.fill("")
            time.sleep(0.3)
            autocomplete.type(partial, delay=100)
            time.sleep(3.0)  # Wait for dropdown
            
            # Nothing below this works:
            option = page.locator("div[class*='option']").first
            option.click(force=True)  # ❌ Doesn't work
            # Tried: Regular click, JS click, Tab key, Enter key, blur
            # All fail - value stays empty
            
            return False
        
        return False
    except Exception as e:
        print(f"    Autocomplete error: {e}")
        return False

# STATUS: BROKEN - dropdown appears with correct option but won't select
# TRIED: 6+ different methods, all fail
# NEEDS: Different approach - maybe this autocomplete works like React-Select?
# TODO: Try typing into a search input for the autocomplete too?


# ============================================================================
# DEBUGGING NOTES:
# ============================================================================

# Field IDs discovered:
# - first_name, last_name, email, phone
# - country (react-select)
# - candidate-location (autocomplete)
# - question_63021724 (Work authorization - react-select)
# - question_63021725 (Visa sponsorship - react-select)
# - gender (react-select)
# - hispanic_ethnicity (react-select)
# - veteran_status (react-select)
# - disability_status (react-select)

# React-Select structure:
# - Combobox: role="combobox", id="field_id"
# - Search input appears after click: input#field_id
# - Options: div[class*='option']
# - Selected value shown in: div[class*='singleValue']

# Autocomplete structure (Location):
# - Input: id="candidate-location", role="combobox"
# - Dropdown appears BUT clicks don't register
# - Might also have a search input that needs typing?

# Common errors:
# - "intercepts pointer events" - Element blocking click
# - Apostrophe in text breaks CSS selector - use get_by_text() instead
# - Timing - some fields need 3+ second waits
