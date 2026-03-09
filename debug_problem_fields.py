#!/usr/bin/env python3
"""
Debug the problematic fields: Location, Work Authorization, Race/Ethnicity
"""
import os, time
from playwright.sync_api import sync_playwright
import requests

BROWSERBASE_API_KEY = os.environ.get("BROWSERBASE_API_KEY", "")
BROWSERBASE_PROJECT = os.environ.get("BROWSERBASE_PROJECT_ID", "")

resp = requests.post(
    "https://www.browserbase.com/v1/sessions",
    headers={"x-bb-api-key": BROWSERBASE_API_KEY, "Content-Type": "application/json"},
    json={"projectId": BROWSERBASE_PROJECT, "browserSettings": {"stealth": True}})
connect_url = resp.json().get("connectUrl")

print("\n" + "="*70)
print("DEBUGGING PROBLEMATIC FIELDS")
print("="*70)

with sync_playwright() as p:
    browser = p.chromium.connect_over_cdp(connect_url)
    ctx = browser.contexts[0] if browser.contexts else browser.new_context()
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    
    page.goto("https://job-boards.greenhouse.io/humaninterest/jobs/7565471")
    time.sleep(3)
    page.get_by_role("button", name="Apply").click()
    time.sleep(3)
    
    # =================================================================
    # DEBUG #1: Location Autocomplete
    # =================================================================
    print("\n" + "="*70)
    print("DEBUG #1: LOCATION AUTOCOMPLETE")
    print("="*70)
    
    loc_field = page.get_by_label("Location (City)", exact=False)
    
    if loc_field.count() > 0:
        print("\n1. Field found ✅")
        print(f"   Count: {loc_field.count()}")
        
        # Click and type
        print("\n2. Clicking field...")
        loc_field.click()
        time.sleep(0.5)
        
        print("\n3. Typing 'Florence, S'...")
        loc_field.fill("")
        time.sleep(0.2)
        loc_field.type("Florence, S", delay=100)
        
        print("\n4. Waiting 2 seconds for dropdown...")
        time.sleep(2.0)
        
        # Check for dropdown options
        print("\n5. Looking for dropdown options...")
        
        selectors = [
            "div[class*='option']",
            "div[role='option']",
            "[role='option']",
            "div[class*='menu'] div",
        ]
        
        for sel in selectors:
            opts = page.locator(sel).all()
            visible = sum(1 for o in opts if o.is_visible())
            if visible > 0:
                print(f"   ✅ {sel}: {visible} visible options")
                # Print first 3
                for i, opt in enumerate(opts[:3]):
                    if opt.is_visible():
                        try:
                            text = opt.inner_text()
                            print(f"      Option {i+1}: {text[:60]}")
                        except:
                            pass
                break
            else:
                print(f"   ❌ {sel}: 0 visible")
        
        # Try ArrowDown + Enter
        print("\n6. Trying keyboard method...")
        page.keyboard.press("ArrowDown")
        time.sleep(0.5)
        print("   Pressed ArrowDown")
        
        page.keyboard.press("Enter")
        time.sleep(1.5)
        print("   Pressed Enter")
        
        # Check value
        value = loc_field.input_value()
        print(f"\n7. Final value: '{value}'")
        
        if value:
            print(f"   ✅ SUCCESS: {value}")
        else:
            print(f"   ❌ FAILED: Empty")
            
            # Try clicking option directly
            print("\n8. Trying direct click on option...")
            loc_field.click()
            loc_field.fill("")
            loc_field.type("Florence, S", delay=100)
            time.sleep(2.0)
            
            # Try clicking first visible option
            option = page.locator("div[class*='option']").first
            if option.count() > 0 and option.is_visible():
                print(f"   Found option, clicking...")
                option.click()
                time.sleep(1.0)
                value = loc_field.input_value()
                print(f"   Result: '{value}'")
    else:
        print("❌ Field not found")
    
    page.screenshot(path="outputs/debug_location.png")
    
    # =================================================================
    # DEBUG #2: Work Authorization Dropdown
    # =================================================================
    print("\n" + "="*70)
    print("DEBUG #2: WORK AUTHORIZATION DROPDOWN")
    print("="*70)
    
    label = "Are you legally authorized to work in the United States?"
    answer = "Yes"
    
    print(f"\nLabel: {label[:50]}...")
    print(f"Answer: {answer}")
    
    # Find label
    label_el = page.locator(f"label:has-text('legally authorized')").first
    
    if label_el.count() > 0:
        print("\n1. Label found ✅")
        for_id = label_el.get_attribute("for")
        print(f"   for ID: {for_id}")
        
        if for_id:
            combobox = page.locator(f"#{for_id}")
            if combobox.count() > 0:
                print("\n2. Combobox found ✅")
                
                # Click to open
                print("\n3. Clicking to open...")
                combobox.click()
                time.sleep(1.0)
                
                # Look for options
                print("\n4. Looking for 'Yes' option...")
                
                # Try different methods
                methods = [
                    ("get_by_text exact", lambda: page.get_by_text("Yes", exact=True).first),
                    ("get_by_text contains", lambda: page.get_by_text("Yes").first),
                    ("div option selector", lambda: page.locator("div[class*='option']:has-text('Yes')").first),
                ]
                
                for method_name, method_func in methods:
                    try:
                        option = method_func()
                        if option.count() > 0:
                            is_visible = option.is_visible()
                            print(f"   {method_name}: found={option.count()}, visible={is_visible}")
                            if is_visible:
                                print(f"      Text: {option.inner_text()[:60]}")
                    except Exception as e:
                        print(f"   {method_name}: ERROR - {e}")
                
                # Try clicking
                print("\n5. Attempting click...")
                try:
                    option = page.get_by_text("Yes", exact=True).first
                    if option.count() > 0 and option.is_visible():
                        option.click()
                        time.sleep(0.5)
                        print("   ✅ Clicked!")
                    else:
                        print("   ❌ Not found or not visible")
                except Exception as e:
                    print(f"   ❌ Error: {e}")
    else:
        print("❌ Label not found")
    
    page.screenshot(path="outputs/debug_work_auth.png")
    
    # =================================================================
    # DEBUG #3: Race/Ethnicity Dropdown
    # =================================================================
    print("\n" + "="*70)
    print("DEBUG #3: RACE/ETHNICITY DROPDOWN")
    print("="*70)
    
    # Scroll down to reach this field
    page.evaluate("window.scrollBy(0, 800)")
    time.sleep(1.0)
    
    # This field might have different label - check for variations
    race_labels = ["Race", "Ethnicity", "Race/Ethnicity", "Race & Ethnicity"]
    
    found = False
    for label_text in race_labels:
        label_el = page.locator(f"label:has-text('{label_text}')").first
        if label_el.count() > 0:
            print(f"\n1. Found label: '{label_text}' ✅")
            found = True
            
            for_id = label_el.get_attribute("for")
            print(f"   for ID: {for_id}")
            
            if for_id:
                combobox = page.locator(f"#{for_id}")
                print(f"   Combobox count: {combobox.count()}")
                
                if combobox.count() > 0:
                    print("\n2. Clicking to open...")
                    combobox.click()
                    time.sleep(1.0)
                    
                    # List all options
                    print("\n3. Available options:")
                    options = page.locator("div[class*='option']").all()
                    for i, opt in enumerate(options):
                        if opt.is_visible():
                            try:
                                text = opt.inner_text()
                                print(f"   {i+1}. {text}")
                            except:
                                pass
            break
    
    if not found:
        print("❌ Race/Ethnicity label not found")
        print("\nSearching for any race-related text...")
        # Try to find it by searching page text
        page_text = page.inner_text("body")
        if "race" in page_text.lower():
            idx = page_text.lower().find("race")
            print(f"Found 'race' in page text: {page_text[idx:idx+100]}")
    
    page.screenshot(path="outputs/debug_race.png")
    
    print("\n" + "="*70)
    print("DEBUGGING COMPLETE")
    print("="*70)
    print("\nScreenshots saved:")
    print("  - outputs/debug_location.png")
    print("  - outputs/debug_work_auth.png")
    print("  - outputs/debug_race.png")
    
    browser.close()

print("\n✅ Done!")
