#!/usr/bin/env python3
"""
Debug location autocomplete - find the right selector
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
data = resp.json()
connect_url = data.get("connectUrl")

with sync_playwright() as p:
    browser = p.chromium.connect_over_cdp(connect_url)
    ctx = browser.contexts[0] if browser.contexts else browser.new_context()
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    
    page.goto("https://job-boards.greenhouse.io/humaninterest/jobs/7565471")
    time.sleep(3)
    page.get_by_role("button", name="Apply").click()
    time.sleep(3)
    
    print("Finding location field...")
    label_el = page.locator("label:has-text('Location')").first
    input_id = label_el.get_attribute("for")
    autocomplete = page.locator(f"#{input_id}")
    
    print("Clicking and typing...")
    autocomplete.click()
    time.sleep(0.3)
    autocomplete.type("Florence, SC", delay=80)
    time.sleep(2.0)
    
    print("\nTrying different selectors:")
    
    selectors = [
        "div[class*='option']",
        "div[role='option']",
        "li[role='option']",
        "[role='option']",
        "div[class*='menu'] div",
        "div[class*='Menu'] div",
        "div[id*='menu'] div",
        "div[id*='listbox'] div",
        "[id*='option']",
        "div[class*='selectOption']",
    ]
    
    for sel in selectors:
        try:
            opts = page.locator(sel).all()
            visible_count = sum(1 for opt in opts if opt.is_visible())
            if visible_count > 0:
                print(f"  ✅ {sel}: {visible_count} visible options")
                # Print first option text
                for opt in opts:
                    if opt.is_visible():
                        print(f"     First option: {opt.inner_text()[:60]}")
                        break
            else:
                print(f"  ❌ {sel}: 0 visible (found {len(opts)} total)")
        except Exception as e:
            print(f"  ❌ {sel}: error - {e}")
    
    # Save screenshot and HTML for inspection
    page.screenshot(path="outputs/location_debug.png")
    html = page.content()
    with open("outputs/location_page.html", "w") as f:
        f.write(html)
    
    print("\n📸 Screenshot: outputs/location_debug.png")
    print("📄 HTML: outputs/location_page.html")
    
    browser.close()
