#!/usr/bin/env python3
"""
Test location autocomplete fix
"""
import os, time, json
from playwright.sync_api import sync_playwright
import requests

BROWSERBASE_API_KEY = os.environ.get("BROWSERBASE_API_KEY", "")
BROWSERBASE_PROJECT = os.environ.get("BROWSERBASE_PROJECT_ID", "")

# Create session
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
    print("TESTING LOCATION AUTOCOMPLETE")
    print("="*60)
    
    # Find location field
    label_el = page.locator("label:has-text('Location')").first
    if label_el.count() > 0:
        input_id = label_el.get_attribute("for")
        print(f"\n1. Found label, for='{input_id}'")
        
        if input_id:
            autocomplete = page.locator(f"#{input_id}")
            print(f"   Field found: {autocomplete.count()} element(s)")
            
            # Click and type
            print("\n2. Clicking and typing 'Florence, SC'...")
            autocomplete.click()
            time.sleep(0.3)
            autocomplete.type("Florence, SC", delay=80)
            time.sleep(2.0)
            
            # Wait for options
            print("\n3. Waiting for dropdown options...")
            try:
                page.wait_for_selector("div[class*='option']", timeout=3000)
            except:
                pass
            
            # Get ALL options
            options = page.locator("div[class*='option']").all()
            print(f"\n4. Found {len(options)} options:")
            
            for i, opt in enumerate(options):
                try:
                    if opt.is_visible():
                        text = opt.inner_text()
                        print(f"   Option {i+1}: {text}")
                except:
                    print(f"   Option {i+1}: [error reading text]")
            
            # Test matching logic
            print("\n5. Testing match strategies:")
            state_code = "SC"
            
            # Strategy 1
            for opt in options:
                try:
                    if not opt.is_visible():
                        continue
                    text = opt.inner_text()
                    if state_code in text and ("United States" in text or "USA" in text):
                        print(f"   ✅ Strategy 1 would match: {text}")
                        break
                except:
                    pass
            
            # Strategy 2  
            for opt in options:
                try:
                    if not opt.is_visible():
                        continue
                    text = opt.inner_text()
                    if state_code in text and "Italy" not in text:
                        print(f"   ✅ Strategy 2 would match: {text}")
                        break
                except:
                    pass
            
            # Take screenshot
            page.screenshot(path="outputs/location_test.png")
            print("\n📸 Screenshot: outputs/location_test.png")
    
    browser.close()
    print("\n✅ Test complete")
