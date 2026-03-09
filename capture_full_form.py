#!/usr/bin/env python3
"""
Capture the full application form properly
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

print("Opening form and taking full-page screenshots...")

with sync_playwright() as p:
    browser = p.chromium.connect_over_cdp(connect_url)
    ctx = browser.contexts[0] if browser.contexts else browser.new_context()
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    
    # Navigate and open form
    page.goto("https://job-boards.greenhouse.io/humaninterest/jobs/7565471")
    time.sleep(3)
    page.get_by_role("button", name="Apply").click()
    time.sleep(4)  # Wait for form to fully load
    
    # Scroll to very top of form
    page.evaluate("window.scrollTo(0, 0)")
    time.sleep(1)
    
    print("\nCapturing form sections...")
    
    # Section 1: Top (Name, Email, Phone, Country)
    page.screenshot(path="outputs/form_section_1_top.png")
    print("✅ Section 1: Top fields (First Name through Country)")
    
    # Scroll down 500px
    page.evaluate("window.scrollBy(0, 500)")
    time.sleep(1)
    page.screenshot(path="outputs/form_section_2_location.png")
    print("✅ Section 2: Location and File uploads")
    
    # Scroll down 500px more
    page.evaluate("window.scrollBy(0, 500)")
    time.sleep(1)
    page.screenshot(path="outputs/form_section_3_questions.png")
    print("✅ Section 3: Questions (Work auth, LinkedIn, etc)")
    
    # Scroll down to bottom (voluntary fields)
    page.evaluate("window.scrollBy(0, 800)")
    time.sleep(1)
    page.screenshot(path="outputs/form_section_4_bottom.png")
    print("✅ Section 4: Bottom (Voluntary self-ID fields)")
    
    # Also get a full-page screenshot
    page.screenshot(path="outputs/form_fullpage.png", full_page=True)
    print("✅ Full page screenshot saved")
    
    print("\nScreenshots saved to outputs/")
    print("  - form_section_1_top.png")
    print("  - form_section_2_location.png")
    print("  - form_section_3_questions.png")
    print("  -form_section_4_bottom.png")
    print("  - form_fullpage.png")
    
    browser.close()

print("\n✅ Complete!")
