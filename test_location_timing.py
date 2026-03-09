#!/usr/bin/env python3
"""
Test location autocomplete with proper timing
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
print("TESTING LOCATION AUTOCOMPLETE WITH TIMING")
print("="*60)

with sync_playwright() as p:
    browser = p.chromium.connect_over_cdp(connect_url)
    ctx = browser.contexts[0] if browser.contexts else browser.new_context()
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    
    page.goto("https://job-boards.greenhouse.io/humaninterest/jobs/7565471")
    time.sleep(3)
    page.get_by_role("button", name="Apply").click()
    time.sleep(3)
    
    loc_field = page.get_by_label("Location (City)", exact=False)
    
    # METHOD 1: Wait 1 second then Enter
    print("\n--- METHOD 1: Type, Wait 1 sec, Enter ---")
    loc_field.click()
    time.sleep(0.3)
    loc_field.fill("")
    time.sleep(0.2)
    
    print("Typing 'Florence, S'...")
    loc_field.type("Florence, S", delay=100)
    
    print("Waiting 1 second for autocomplete...")
    time.sleep(1.0)
    
    print("Pressing Enter...")
    page.keyboard.press("Enter")
    time.sleep(0.5)
    
    result1 = loc_field.input_value()
    print(f"Result: '{result1}'")
    
    if result1:
        print(f"✅ SUCCESS - Location set to: {result1}")
        if "South Carolina" in result1 or "United States" in result1:
            print("✅ CORRECT - US location!")
    else:
        print("❌ FAILED - Empty field")
        
        # METHOD 2: ArrowDown first, then Enter
        print("\n--- METHOD 2: Type, Wait, ArrowDown, Enter ---")
        loc_field.click()
        time.sleep(0.3)
        loc_field.fill("")
        time.sleep(0.2)
        
        print("Typing 'Florence, S'...")
        loc_field.type("Florence, S", delay=100)
        
        print("Waiting 1 second...")
        time.sleep(1.0)
        
        print("Pressing ArrowDown...")
        page.keyboard.press("ArrowDown")
        time.sleep(0.3)
        
        print("Pressing Enter...")
        page.keyboard.press("Enter")
        time.sleep(0.5)
        
        result2 = loc_field.input_value()
        print(f"Result: '{result2}'")
        
        if result2:
            print(f"✅ SUCCESS - Location set to: {result2}")
            if "South Carolina" in result2 or "United States" in result2:
                print("✅ CORRECT - US location!")
        else:
            print("❌ FAILED - Empty field")
    
    page.screenshot(path="outputs/location_timing_test.png")
    print(f"\n📸 Screenshot: outputs/location_timing_test.png")
    
    browser.close()

print("\n✅ Test complete!")
