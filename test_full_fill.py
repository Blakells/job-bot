#!/usr/bin/env python3
"""
Full test - fill all fields including Country and Location
"""
import os, sys, time
sys.path.insert(0, '/Users/blakeb/job-bot/scripts')
from auto_apply import *

# Load profile and job
with open('/Users/blakeb/job-bot/profiles/job_profile.json') as f:
    profile = json.load(f)

job = {
    "title": "Security Engineer II",
    "company": "Human Interest",
    "apply_url": "https://job-boards.greenhouse.io/humaninterest/jobs/7565471",
    "match_score": 85
}

resume_path = "/Users/blakeb/job-bot/outputs/tailored/03_Human_Interest_Security_Engineer_II_RESUME.pdf"
cover_letter_path = "/Users/blakeb/job-bot/outputs/tailored/03_Human_Interest_Security_Engineer_II_COVER_LETTER.pdf"

# Create browser session
BROWSERBASE_API_KEY = os.environ.get("BROWSERBASE_API_KEY", "")
BROWSERBASE_PROJECT = os.environ.get("BROWSERBASE_PROJECT_ID", "")
import requests
resp = requests.post(
    "https://www.browserbase.com/v1/sessions",
    headers={"x-bb-api-key": BROWSERBASE_API_KEY, "Content-Type": "application/json"},
    json={"projectId": BROWSERBASE_PROJECT, "browserSettings": {"stealth": True}})
data = resp.json()
connect_url = data.get("connectUrl")

from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    browser = p.chromium.connect_over_cdp(connect_url)
    ctx = browser.contexts[0] if browser.contexts else browser.new_context()
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    
    # Navigate to form
    page.goto(job['apply_url'], wait_until="domcontentloaded", timeout=30000)
    time.sleep(3)
    page.get_by_role("button", name="Apply").click()
    time.sleep(3)
    
    # Get fields
    page_text = page.inner_text("body")
    form_data = get_form_fields(page_text, profile, job, resume_path, cover_letter_path)
    fields = form_data.get("fields", [])
    
    print(f"\n✅ Detected {len(fields)} fields")
    print("\nFilling fields...")
    
    filled_count = 0
    failed_fields = []
    
    for f in fields:
        label = f.get("label", "")
        answer = f.get("answer", "")
        ftype = f.get("type", "text")
        
        if not answer:
            continue
        
        print(f"\n{label} ({ftype}): {str(answer)[:50]}")
        
        try:
            if ftype == "text":
                success = fill_text(page, label, answer)
                if success:
                    filled_count += 1
                    print(f"  ✅ Filled")
                else:
                    failed_fields.append(label)
                    print(f"  ❌ Failed")
            
            elif ftype == "react-select":
                success = fill_react_select(page, label, answer)
                if success:
                    filled_count += 1
                    print(f"  ✅ Selected: {answer}")
                else:
                    failed_fields.append(label)
                    print(f"  ❌ Failed")
            
            elif ftype == "autocomplete":
                success = fill_autocomplete(page, label, answer)
                if success:
                    filled_count += 1
                    print(f"  ✅ Autocomplete filled")
                else:
                    failed_fields.append(label)
                    print(f"  ❌ Failed")
            
            elif ftype == "file":
                file_path = resume_path if answer == "RESUME_FILE" else cover_letter_path
                if file_path:
                    try:
                        inputs = page.locator("input[type='file']").all()
                        for inp in inputs:
                            aria_label = inp.get_attribute("aria-labelledby") or ""
                            if "resume" in label.lower() and "resume" in aria_label.lower():
                                inp.set_input_files(file_path)
                                filled_count += 1
                                print(f"  ✅ Uploaded {Path(file_path).name}")
                                break
                            elif "cover" in label.lower() and "cover" in aria_label.lower():
                                inp.set_input_files(file_path)
                                filled_count += 1
                                print(f"  ✅ Uploaded {Path(file_path).name}")
                                break
                    except Exception as e:
                        failed_fields.append(label)
                        print(f"  ❌ Upload failed: {e}")
            
            time.sleep(0.5)
        
        except Exception as e:
            failed_fields.append(label)
            print(f"  ❌ Error: {e}")
    
    # Screenshot
    page.screenshot(path="outputs/test_full_fill.png")
    
    print(f"\n" + "="*60)
    print(f"RESULTS:")
    print(f"  Total fields: {len(fields)}")
    print(f"  Filled: {filled_count}/{len(fields)} ({filled_count*100//len(fields)}%)")
    
    if failed_fields:
        print(f"\n  Failed fields:")
        for f in failed_fields:
            print(f"    - {f}")
    
    print(f"\n📸 Screenshot: outputs/test_full_fill.png")
    
    browser.close()
