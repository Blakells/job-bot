#!/usr/bin/env python3
"""
Try different methods to select the autocomplete option
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

print("\nTesting different autocomplete selection methods...")

with sync_playwright() as p:
    browser = p.chromium.connect_over_cdp(connect_url)
    ctx = browser.contexts[0] if browser.contexts else browser.new_context()
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    
    page.goto("https://job-boards.greenhouse.io/humaninterest/jobs/7565471")
    time.sleep(3)
    page.get_by_role("button", name="Apply").click()
    time.sleep(3)
    
    loc_field = page.get_by_label("Location (City)", exact=False)
    
    # METHOD 1: ArrowDown then Enter
    print("\n" + "="*60)
    print("METHOD 1: Type, ArrowDown, Enter")
    print("="*60)
    loc_field.click()
    time.sleep(0.3)
    loc_field.fill("")
    loc_field.type("Florence, S", delay=100)
    time.sleep(2.0)
    
    print("Pressing ArrowDown...")
    page.keyboard.press("ArrowDown")
    time.sleep(0.5)
    
    print("Pressing Enter...")
    page.keyboard.press("Enter")
    time.sleep(0.5)
    
    result1 = loc_field.input_value()
    print(f"Result: {result1 if result1 else 'EMPTY'}")
    
    if not result1:
        # METHOD 2: Click the dropdown option directly
        print("\n" + "="*60)
        print("METHOD 2: Click dropdown option directly")
        print("="*60)
        loc_field.click()
        loc_field.fill("")
        time.sleep(0.2)
        loc_field.type("Florence, S", delay=100)
        time.sleep(2.0)
        
        # Try to click the dropdown option
        try:
            # Look for the option with "South Carolina"
            option = page.locator("text=South Carolina").first
            if option.count() > 0 and option.is_visible():
                print("Found 'South Carolina' option, clicking...")
                option.click()
                time.sleep(0.5)
                result2 = loc_field.input_value()
                print(f"Result: {result2 if result2 else 'EMPTY'}")
            else:
                print("Option not found or not visible")
                
                # Try any visible div option
                print("\nTrying generic div click...")
                div_option = page.locator("div[class*='option']").first
                if div_option.count() > 0 and div_option.is_visible():
                    div_option.click()
                    time.sleep(0.5)
                    result2 = loc_field.input_value()
                    print(f"Result: {result2 if result2 else 'EMPTY'}")
        except Exception as e:
            print(f"Error: {e}")
    
    # Take final screenshot
    page.screenshot(path="outputs/location_test_final.png")
    print(f"\n📸 Screenshot: outputs/location_test_final.png")
    
    browser.close()

print("\n✅ Test complete!")
