#!/usr/bin/env python3
"""
Final verification test - fill all 14 fields and verify
"""
import os, sys, time, json
from pathlib import Path

# Setup paths
sys.path.insert(0, '/Users/blakeb/job-bot/scripts')

# Load profile
with open('/Users/blakeb/job-bot/profiles/job_profile.json') as f:
    profile = json.load(f)

job = {
    "title": "Security Engineer II",
    "company": "Human Interest",
    "apply_url": "https://job-boards.greenhouse.io/humaninterest/jobs/7565471"
}

resume_path = "/Users/blakeb/job-bot/outputs/tailored/03_Human_Interest_Security_Engineer_II_RESUME.pdf"
cover_letter_path = "/Users/blakeb/job-bot/outputs/tailored/03_Human_Interest_Security_Engineer_II_COVER_LETTER.pdf"

# Create browser
BROWSERBASE_API_KEY = os.environ.get("BROWSERBASE_API_KEY", "")
BROWSERBASE_PROJECT = os.environ.get("BROWSERBASE_PROJECT_ID", "")

import requests
resp = requests.post(
    "https://www.browserbase.com/v1/sessions",
    headers={"x-bb-api-key": BROWSERBASE_API_KEY, "Content-Type": "application/json"},
    json={"projectId": BROWSERBASE_PROJECT, "browserSettings": {"stealth": True}})
connect_url = resp.json().get("connectUrl")

print("\n" + "="*60)
print("FINAL VERIFICATION TEST")
print("="*60)

from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.connect_over_cdp(connect_url)
    ctx = browser.contexts[0] if browser.contexts else browser.new_context()
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    
    # Navigate
    print("\n1. Loading form...")
    page.goto(job['apply_url'], wait_until="domcontentloaded", timeout=30000)
    time.sleep(3)
    page.get_by_role("button", name="Apply").click()
    time.sleep(3)
    
    # Get fields using our function
    from auto_apply import get_form_fields, fill_react_select
    
    page_text = page.inner_text("body")
    form_data = get_form_fields(page_text, profile, job, resume_path, cover_letter_path)
    fields = form_data.get("fields", [])
    
    print(f"\n2. Detected {len(fields)} fields:")
    for i, f in enumerate(fields, 1):
        print(f"   {i}. {f.get('label')} ({f.get('type')})")
    
    print(f"\n3. Filling fields...")
    results = {}
    
    for f in fields:
        label = f.get("label", "")
        answer = f.get("answer", "")
        ftype = f.get("type", "text")
        
        if not answer:
            continue
        
        print(f"\n   [{label}]")
        
        try:
            if ftype == "text":
                # Simple text fill
                field = page.get_by_label(label, exact=False)
                if field.count() > 0:
                    field.fill(answer)
                    results[label] = "✅ Filled"
                    print(f"   ✅ Filled: {answer[:40]}")
                else:
                    results[label] = "❌ Not found"
                    print(f"   ❌ Field not found")
            
            elif ftype == "react-select":
                # Use our function
                success = fill_react_select(page, label, answer)
                if success:
                    results[label] = "✅ Selected"
                    print(f"   ✅ Selected: {answer}")
                else:
                    results[label] = "❌ Failed"
                    print(f"   ❌ Failed to select")
            
            elif ftype == "autocomplete":
                # Location field - use keyboard method
                print(f"   Typing: {answer}")
                field = page.get_by_label(label, exact=False)
                if field.count() > 0:
                    field.click()
                    time.sleep(0.3)
                    field.fill(answer)
                    time.sleep(1.5)
                    
                    # Keyboard navigation
                    page.keyboard.press("ArrowDown")
                    time.sleep(0.5)
                    page.keyboard.press("ArrowDown")  # Try second option
                    time.sleep(0.3)
                    page.keyboard.press("Enter")
                    time.sleep(0.5)
                    
                    # Check value
                    final_val = field.input_value()
                    if final_val:
                        results[label] = f"✅ Selected: {final_val}"
                        print(f"   ✅ Selected: {final_val}")
                    else:
                        results[label] = "⚠️ No value"
                        print(f"   ⚠️ No value set")
                else:
                    results[label] = "❌ Not found"
                    print(f"   ❌ Field not found")
            
            elif ftype == "file":
                file_path = resume_path if answer == "RESUME_FILE" else cover_letter_path
                if file_path and Path(file_path).exists():
                    # Find file input
                    inputs = page.locator("input[type='file']").all()
                    uploaded = False
                    for inp in inputs:
                        aria_label = (inp.get_attribute("aria-labelledby") or "").lower()
                        if ("resume" in label.lower() and "resume" in aria_label) or \
                           ("cover" in label.lower() and "cover" in aria_label):
                            inp.set_input_files(file_path)
                            results[label] = f"✅ Uploaded"
                            print(f"   ✅ Uploaded: {Path(file_path).name}")
                            uploaded = True
                            break
                    if not uploaded:
                        results[label] = "⚠️ No match"
                        print(f"   ⚠️ Couldn't match file input")
                else:
                    results[label] = "❌ No file"
                    print(f"   ❌ File not found")
            
            time.sleep(0.3)
        
        except Exception as e:
            results[label] = f"❌ Error: {str(e)[:30]}"
            print(f"   ❌ Error: {e}")
    
    # Screenshot
    page.screenshot(path="outputs/final_verification.png")
    
    # Summary
    print("\n" + "="*60)
    print("RESULTS SUMMARY")
    print("="*60)
    
    success_count = sum(1 for v in results.values() if v.startswith("✅"))
    print(f"\nTotal fields: {len(fields)}")
    print(f"Successfully filled: {success_count}/{len(fields)} ({success_count*100//len(fields)}%)")
    
    print(f"\nDetailed results:")
    for label, result in results.items():
        print(f"  {label[:40]:40} {result}")
    
    print(f"\n📸 Screenshot: outputs/final_verification.png")
    
    browser.close()

print("\n✅ Test complete!")
