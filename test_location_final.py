#!/usr/bin/env python3
"""
Test the new location autocomplete method: type "Florence, S" and press Enter
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

print("\n" + "="*60)
print("TESTING LOCATION AUTOCOMPLETE FIX")
print("="*60)

with sync_playwright() as p:
    browser = p.chromium.connect_over_cdp(connect_url)
    ctx = browser.contexts[0] if browser.contexts else browser.new_context()
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    
    page.goto("https://job-boards.greenhouse.io/humaninterest/jobs/7565471")
    time.sleep(3)
    page.get_by_role("button", name="Apply").click()
    time.sleep(3)
    
    print("\n1. Finding Location (City) field...")
    loc_field = page.get_by_label("Location (City)", exact=False)
    
    if loc_field.count() > 0:
        print("   ✅ Field found")
        
        print("\n2. Clicking field...")
        loc_field.click()
        time.sleep(0.5)
        
        print("\n3. Typing 'Florence, S'...")
        loc_field.fill("")  # Clear first
        time.sleep(0.2)
        loc_field.type("Florence, S", delay=100)
        time.sleep(1.5)
        
        print("\n4. Taking screenshot before Enter...")
        page.screenshot(path="outputs/location_before_enter.png")
        
        print("\n5. Pressing Enter to select...")
        page.keyboard.press("Enter")
        time.sleep(0.5)
        
        print("\n6. Taking screenshot after Enter...")
        page.screenshot(path="outputs/location_after_enter.png")
        
        print("\n7. Checking final value...")
        final_value = loc_field.input_value()
        
        print("\n" + "="*60)
        print("RESULT:")
        print("="*60)
        if final_value:
            print(f"✅ SUCCESS - Location set to: {final_value}")
            
            # Check if it's the US location
            if "United States" in final_value or "South Carolina" in final_value:
                print("✅ CORRECT - US location selected!")
            elif "Italy" in final_value:
                print("❌ WRONG - Italy selected instead of US")
            else:
                print(f"⚠️  PARTIAL - Value exists but needs verification")
        else:
            print("❌ FAILED - No value selected")
        
        print("\n📸 Screenshots:")
        print("   - outputs/location_before_enter.png")
        print("   - outputs/location_after_enter.png")
    else:
        print("   ❌ Field not found")
    
    browser.close()

print("\n✅ Test complete!")
