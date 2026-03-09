#!/usr/bin/env python3
"""
Simple location test - try different approaches
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

with sync_playwright() as p:
    browser = p.chromium.connect_over_cdp(connect_url)
    ctx = browser.contexts[0] if browser.contexts else browser.new_context()
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    
    page.goto("https://job-boards.greenhouse.io/humaninterest/jobs/7565471")
    time.sleep(3)
    page.get_by_role("button", name="Apply").click()
    time.sleep(3)
    
    print("Testing location autocomplete...")
    
    # Approach 1: Use get_by_label
    print("\n1. Using get_by_label...")
    try:
        loc_field = page.get_by_label("Location (City)", exact=False)
        if loc_field.count() > 0:
            print(f"   Found by label: {loc_field.count()} element(s)")
            loc_field.click()
            time.sleep(0.5)
            loc_field.fill("Florence, SC")
            time.sleep(2.0)
            
            # Check if dropdown appeared
            page.screenshot(path="outputs/location_after_fill.png")
            print("   📸 Screenshot: outputs/location_after_fill.png")
            
            #Try selecting with keyboard
            print("   Trying keyboard navigation...")
            page.keyboard.press("ArrowDown")
            time.sleep(0.5)
            page.keyboard.press("Enter")
            time.sleep(1.0)
            
            page.screenshot(path="outputs/location_after_enter.png")
            print("   📸 Screenshot: outputs/location_after_enter.png")
            
            # Check value
            val = loc_field.input_value()
            print(f"   Final value: {val}")
    except Exception as e:
        print(f"   Error: {e}")
    
    browser.close()
