#!/usr/bin/env python3
"""
Check the filled form - take screenshots of different sections
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

print("Opening form and checking field values...")

with sync_playwright() as p:
    browser = p.chromium.connect_over_cdp(connect_url)
    ctx = browser.contexts[0] if browser.contexts else browser.new_context()
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    
    # Open form
    page.goto("https://job-boards.greenhouse.io/humaninterest/jobs/7565471")
    time.sleep(3)
    page.get_by_role("button", name="Apply").click()
    time.sleep(3)
    
    # Scroll to top
    page.evaluate("window.scrollTo(0, 0)")
    time.sleep(1)
    
    print("\nChecking field values...")
    
    # Check each field
    fields_to_check = [
        ("First Name", "first_name"),
        ("Last Name", "last_name"),
        ("Email", "email"),
        ("Phone", "phone"),
        ("Country", "country"),
        ("Location (City)", "candidate-location"),
    ]
    
    results = {}
    
    for label, field_id in fields_to_check:
        try:
            field = page.locator(f"#{field_id}")
            if field.count() > 0:
                value = field.input_value()
                results[label] = value if value else "[EMPTY]"
                print(f"  {label}: {results[label]}")
            else:
                results[label] = "[NOT FOUND]"
                print(f"  {label}: NOT FOUND")
        except:
            results[label] = "[ERROR]"
            print(f"  {label}: ERROR")
    
    # Take screenshots of different sections
    page.evaluate("window.scrollTo(0, 0)")
    time.sleep(0.5)
    page.screenshot(path="outputs/filled_top.png")
    print("\n📸 outputs/filled_top.png")
    
    page.evaluate("window.scrollBy(0, 600)")
    time.sleep(0.5)
    page.screenshot(path="outputs/filled_middle.png")
    print("📸 outputs/filled_middle.png")
    
    page.evaluate("window.scrollBy(0, 800)")
    time.sleep(0.5)
    page.screenshot(path="outputs/filled_bottom.png")
    print("📸 outputs/filled_bottom.png")
    
    # Full page
    page.screenshot(path="outputs/filled_fullpage.png", full_page=True)
    print("📸 outputs/filled_fullpage.png")
    
    print("\nSummary:")
    print("="*60)
    for label, value in results.items():
        status = "✅" if value and value != "[EMPTY]" and "[" not in value else "❌"
        print(f"{status} {label}: {value}")
    
    browser.close()

print("\n✅ Done!")
