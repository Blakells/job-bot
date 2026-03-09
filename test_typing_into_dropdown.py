#!/usr/bin/env python3
"""
Test typing into react-select dropdown search input (Opus's method)
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
print("TESTING OPUS'S METHOD: Type into dropdown search input")
print("="*70)

with sync_playwright() as p:
    browser = p.chromium.connect_over_cdp(connect_url)
    ctx = browser.contexts[0] if browser.contexts else browser.new_context()
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    
    page.goto("https://job-boards.greenhouse.io/humaninterest/jobs/7565471")
    time.sleep(3)
    page.get_by_role("button", name="Apply").click()
    time.sleep(3)
    
    # Test Work Authorization dropdown
    print("\n--- Testing Work Authorization Dropdown ---")
    
    label = "Are you legally authorized to work in the United States?"
    answer = "Yes"
    
    # Find label
    label_el = page.locator("label:has-text('legally authorized')").first
    
    if label_el.count() > 0:
        for_id = label_el.get_attribute("for")
        print(f"1. Label found, for_id: {for_id}")
        
        # Find and click the dropdown control
        dropdown = page.locator(f"#{for_id}")
        print(f"2. Dropdown element count: {dropdown.count()}")
        
        print(f"3. Clicking dropdown...")
        dropdown.click()
        time.sleep(1.0)
        
        # Now find the search input that appeared
        # Try different selectors
        print(f"\n4. Looking for search input...")
        
        selectors = [
            f"input#{for_id}",  # Same ID as combobox
            "input[class*='select__input']",  # React-select class
            "input[aria-autocomplete='list']",  # Autocomplete attribute
            f"input[aria-labelledby='{for_id}-label']",  # Connected to label
        ]
        
        search_found = False
        for sel in selectors:
            search = page.locator(sel).first
            if search.count() > 0:
                print(f"   ✅ Found with selector: {sel}")
                print(f"      Count: {search.count()}, Visible: {search.is_visible()}")
                
                # Type the answer
                print(f"\n5. Typing '{answer}' into search input...")
                search.type(answer, delay=50)
                time.sleep(1.0)
                
                # Click matching option
                print(f"\n6. Looking for '{answer}' option...")
                option = page.get_by_text(answer, exact=True).first
                if option.count() > 0 and option.is_visible():
                    print(f"   ✅ Option found, clicking...")
                    option.click()
                    time.sleep(0.5)
                    
                    # Verify selection
                    final_val = dropdown.get_attribute("aria-activedescendant") or dropdown.input_value()
                    print(f"\n7. Final value/state: {final_val}")
                    search_found = True
                    break
                else:
                    print(f"   ❌ Option not found or not visible")
            else:
                print(f"   ❌ Not found: {sel}")
        
        if not search_found:
            print("\n❌ Could not find search input")
    
    page.screenshot(path="outputs/test_typing_dropdown.png")
    print(f"\n📸 Screenshot: outputs/test_typing_dropdown.png")
    
    browser.close()

print("\n✅ Test complete!")
