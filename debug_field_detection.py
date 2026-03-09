#!/usr/bin/env python3
"""
Debug what Claude sees when analyzing the form
"""
import os, time, json
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
    
    # Get the page text that Claude would see
    page_text = page.inner_text("body")
    
    # Check if "Country" appears in the text
    print("Checking if 'Country' appears in page text...")
    if "Country" in page_text:
        print("✅ 'Country' found in page text")
        # Find the context around it
        idx = page_text.find("Country")
        print(f"\nContext around 'Country':")
        print(page_text[max(0, idx-100):idx+100])
    else:
        print("❌ 'Country' NOT found in page text")
    
    # Check for all combobox fields
    print("\n" + "="*60)
    print("All combobox fields (react-select dropdowns):")
    print("="*60)
    comboboxes = page.locator("[role='combobox']").all()
    print(f"Found {len(comboboxes)} combobox fields:\n")
    
    for i, cb in enumerate(comboboxes):
        try:
            field_id = cb.get_attribute("id")
            aria_label = cb.get_attribute("aria-labelledby")
            
            # Try to get the label text
            label_text = ""
            if aria_label:
                try:
                    label_el = page.locator(f"#{aria_label}").first
                    if label_el.count() > 0:
                        label_text = label_el.inner_text()
                except:
                    pass
            
            # If no label yet, try finding by "for" attribute
            if not label_text:
                try:
                    label_el = page.locator(f"label[for='{field_id}']").first
                    if label_el.count() > 0:
                        label_text = label_el.inner_text()
                except:
                    pass
            
            print(f"{i+1}. ID: {field_id}")
            print(f"   Label: {label_text}")
            print(f"   aria-labelledby: {aria_label}")
            print()
        except Exception as e:
            print(f"{i+1}. Error: {e}\n")
    
    # Save the page text for inspection
    with open("outputs/page_text_for_claude.txt", "w") as f:
        f.write(page_text)
    
    print("📄 Saved page text to: outputs/page_text_for_claude.txt")
    
    browser.close()
