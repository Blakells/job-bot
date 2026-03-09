#!/usr/bin/env python3
"""
Direct test of Greenhouse dropdown filling
"""
import os, time
from playwright.sync_api import sync_playwright

BROWSERBASE_API_KEY = os.environ.get("BROWSERBASE_API_KEY", "")
BROWSERBASE_PROJECT = os.environ.get("BROWSERBASE_PROJECT_ID", "")

import requests
resp = requests.post(
    "https://www.browserbase.com/v1/sessions",
    headers={"x-bb-api-key": BROWSERBASE_API_KEY, "Content-Type": "application/json"},
    json={"projectId": BROWSERBASE_PROJECT, "browserSettings": {"stealth": True}})
data = resp.json()
session_id = data.get("id")
connect_url = data.get("connectUrl")

print(f"Session: {session_id}")

with sync_playwright() as p:
    browser = p.chromium.connect_over_cdp(connect_url)
    ctx = browser.contexts[0] if browser.contexts else browser.new_context()
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    
    # Load and open form
    page.goto("https://job-boards.greenhouse.io/humaninterest/jobs/7565471")
    time.sleep(3)
    page.get_by_role("button", name="Apply").click()
    time.sleep(3)
    
    print("\n" + "="*60)
    print("TESTING WORK AUTHORIZATION DROPDOWN")
    print("="*60)
    
    label_text = "Are you legally authorized to work in the United States?"
    answer = "Yes"
    
    # Method 1: Find label, get the "for" attribute
    print(f"\n1. Finding label with text: '{label_text[:50]}...'")
    label_el = page.locator(f"label:has-text('{label_text}')").first
    
    if label_el.count() > 0:
        for_id = label_el.get_attribute("for")
        print(f"   ✅ Found label, for='{for_id}'")
        
        # Find the input by ID
        if for_id:
            combobox = page.locator(f"#{for_id}")
            print(f"   ✅ Found combobox with id='{for_id}'")
            print(f"   Role: {combobox.get_attribute('role')}")
            print(f"   Type: {combobox.get_attribute('type')}")
            
            # Click to open
            print("\n2. Clicking combobox to open dropdown...")
            combobox.click()
            time.sleep(1)
            
            # Check what appeared
            print("\n3. Looking for options...")
            
            # Try different option selectors
            options_1 = page.locator("div[class*='option']").all()
            print(f"   Found {len(options_1)} divs with class*='option'")
            
            options_2 = page.get_by_role("option").all()
            print(f"   Found {len(options_2)} elements with role='option'")
            
            # Try to find "Yes" option
            print(f"\n4. Looking for option with text '{answer}'...")
            
            yes_option = page.locator(f"div[class*='option']:has-text('{answer}')").first
            if yes_option.count() > 0:
                print(f"   ✅ Found option div")
                if yes_option.is_visible():
                    print(f"   ✅ Option is visible - clicking it...")
                    yes_option.click()
                    time.sleep(1)
                    
                    # Verify it was selected
                    current_value = combobox.get_attribute("value") or combobox.input_value()
                    print(f"   Selected value: '{current_value}'")
                else:
                    print(f"   ❌ Option not visible")
            else:
                print(f"   ❌ Could not find option div")
                
                # Try alternate approach
                print(f"\n5. Trying role='option' approach...")
                yes_option2 = page.get_by_role("option", name=answer)
                if yes_option2.count() > 0:
                    print(f"   Found {yes_option2.count()} option(s)")
                    yes_option2.first.click()
                    time.sleep(1)
                    print(f"   ✅ Clicked option")
    
    # Take screenshot
    page.screenshot(path="outputs/test_dropdown_filled.png")
    print(f"\n📸 Screenshot saved: outputs/test_dropdown_filled.png")
    
    input("\nPress Enter to close browser...")
    
    browser.close()

requests.delete(f"https://www.browserbase.com/v1/sessions/{session_id}",
    headers={"x-bb-api-key": BROWSERBASE_API_KEY})
