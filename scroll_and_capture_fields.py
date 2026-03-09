#!/usr/bin/env python3
"""
Scroll through entire form and capture all visible fields
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
    
    print("\n" + "="*60)
    print("SCROLLING THROUGH FORM - CAPTURING ALL FIELDS")
    print("="*60)
    
    # Scroll to top first
    page.evaluate("window.scrollTo(0, 0)")
    time.sleep(1)
    
    # Take screenshots at different scroll positions
    screenshots = []
    
    # Top of form
    page.screenshot(path="outputs/form_scroll_top.png")
    screenshots.append("Top section")
    print("\n📸 Captured: Top of form")
    
    # Scroll middle
    page.evaluate("window.scrollBy(0, 400)")
    time.sleep(1)
    page.screenshot(path="outputs/form_scroll_mid1.png")
    screenshots.append("Middle section 1")
    print("📸 Captured: Middle section 1")
    
    # Scroll more
    page.evaluate("window.scrollBy(0, 400)")
    time.sleep(1)
    page.screenshot(path="outputs/form_scroll_mid2.png")
    screenshots.append("Middle section 2")
    print("📸 Captured: Middle section 2")
    
    # Scroll to bottom
    page.evaluate("window.scrollBy(0, 800)")
    time.sleep(1)
    page.screenshot(path="outputs/form_scroll_bottom.png")
    screenshots.append("Bottom section")
    print("📸 Captured: Bottom of form")
    
    # Get ALL input fields, textareas, and selects
    print("\n" + "="*60)
    print("ALL FORM FIELDS DETECTED:")
    print("="*60)
    
    # Text inputs
    print("\nTEXT INPUT FIELDS:")
    text_inputs = page.locator("input[type='text'], input[type='email'], input[type='tel'], input:not([type])").all()
    for i, inp in enumerate(text_inputs, 1):
        try:
            field_id = inp.get_attribute("id") or "no-id"
            aria_label = inp.get_attribute("aria-labelledby") or ""
            placeholder = inp.get_attribute("placeholder") or ""
            
            # Try to get label text
            label_text = ""
            if aria_label:
                try:
                    label_el = page.locator(f"#{aria_label}").first
                    if label_el.count() > 0:
                        label_text = label_el.inner_text()
                except:
                    pass
            
            if not label_text and field_id != "no-id":
                try:
                    label_el = page.locator(f"label[for='{field_id}']").first
                    if label_el.count() > 0:
                        label_text = label_el.inner_text()
                except:
                    pass
            
            print(f"{i:2}. ID: {field_id:30} Label: {label_text or placeholder or 'N/A'}")
        except:
            print(f"{i:2}. [Error reading field]")
    
    # Comboboxes (react-select)
    print("\nCOMBOBOX/SELECT FIELDS (React-Select):")
    comboboxes = page.locator("[role='combobox']").all()
    for i, cb in enumerate(comboboxes, 1):
        try:
            field_id = cb.get_attribute("id") or "no-id"
            aria_label = cb.get_attribute("aria-labelledby") or ""
            
            label_text = ""
            if aria_label:
                try:
                    label_el = page.locator(f"#{aria_label}").first
                    if label_el.count() > 0:
                        label_text = label_el.inner_text()
                except:
                    pass
            
            print(f"{i:2}. ID: {field_id:30} Label: {label_text or 'N/A'}")
        except:
            print(f"{i:2}. [Error reading field]")
    
    # File inputs
    print("\nFILE INPUT FIELDS:")
    file_inputs = page.locator("input[type='file']").all()
    for i, inp in enumerate(file_inputs, 1):
        try:
            field_id = inp.get_attribute("id") or "no-id"
            aria_label = inp.get_attribute("aria-labelledby") or ""
            
            label_text = ""
            if aria_label:
                try:
                    label_el = page.locator(f"#{aria_label}").first
                    if label_el.count() > 0:
                        label_text = label_el.inner_text()
                except:
                    pass
            
            print(f"{i:2}. ID: {field_id:30} Label: {label_text or 'N/A'}")
        except:
            print(f"{i:2}. [Error reading field]")
    
    # Textareas
    print("\nTEXTAREA FIELDS:")
    textareas = page.locator("textarea").all()
    for i, ta in enumerate(textareas, 1):
        try:
            field_id = ta.get_attribute("id") or "no-id"
            aria_label = ta.get_attribute("aria-labelledby") or ""
            
            label_text = ""
            if aria_label:
                try:
                    label_el = page.locator(f"#{aria_label}").first
                    if label_el.count() > 0:
                        label_text = label_el.inner_text()
                except:
                    pass
            
            print(f"{i:2}. ID: {field_id:30} Label: {label_text or 'N/A'}")
        except:
            print(f"{i:2}. [Error reading field]")
    
    print("\n" + "="*60)
    print("Screenshots saved:")
    print("  - outputs/form_scroll_top.png")
    print("  - outputs/form_scroll_mid1.png")
    print("  - outputs/form_scroll_mid2.png")
    print("  - outputs/form_scroll_bottom.png")
    print("="*60)
    
    browser.close()

print("\n✅ Form scan complete!")
