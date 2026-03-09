#!/usr/bin/env python3
"""
Test Tab key and blur method for location autocomplete
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

print("Testing Tab key and blur methods...")

with sync_playwright() as p:
    browser = p.chromium.connect_over_cdp(connect_url)
    ctx = browser.contexts[0] if browser.contexts else browser.new_context()
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    
    page.goto("https://job-boards.greenhouse.io/humaninterest/jobs/7565471")
    time.sleep(3)
    page.get_by_role("button", name="Apply").click()
    time.sleep(3)
    
    loc_field = page.get_by_label("Location (City)", exact=False)
    
    # METHOD 1: Tab key
    print("\n=== METHOD 1: Tab Key ===")
    loc_field.click()
    time.sleep(0.3)
    loc_field.fill("")
    loc_field.type("Florence, S", delay=100)
    time.sleep(1.0)
    
    print("Pressing Tab...")
    page.keyboard.press("Tab")
    time.sleep(1.0)
    
    result = loc_field.input_value()
    print(f"Result: '{result}'")
    
    if result:
        print(f"✅ SUCCESS with Tab! Value: {result}")
    else:
        print("❌ Tab didn't work, trying blur method...")
        
        # METHOD 2: Click field, type, then click elsewhere to blur
        print("\n=== METHOD 2: Blur (click elsewhere) ===")
        loc_field.click()
        time.sleep(0.3)
        loc_field.fill("")
        loc_field.type("Florence, S", delay=100)
        time.sleep(1.5)
        
        print("Clicking elsewhere to blur field...")
        # Click on a label or other safe element
        page.locator("label").first.click()
        time.sleep(1.0)
        
        result = loc_field.input_value()
        print(f"Result: '{result}'")
        
        if result:
            print(f"✅ SUCCESS with blur! Value: {result}")
        else:
            print("❌ Blur didn't work either")
    
    page.screenshot(path="outputs/tab_blur_test.png")
    print(f"\n📸 Screenshot: outputs/tab_blur_test.png")
    
    browser.close()

print("\n✅ Test complete!")
