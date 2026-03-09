#!/usr/bin/env python3
"""
Job Bot - Phase 4: Auto-Apply Engine
100% Automation with File Uploads, Multi-Page Navigation, and React-Select Support
"""

import json, os, sys, time, argparse, re
from pathlib import Path
import requests

BROWSERBASE_API_KEY = os.environ.get("BROWSERBASE_API_KEY", "")
BROWSERBASE_PROJECT = os.environ.get("BROWSERBASE_PROJECT_ID", "")
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")
OPENROUTER_BASE = "https://openrouter.ai/api/v1/chat/completions"
MODEL = "anthropic/claude-sonnet-4-5"

def ask_claude(prompt):
    """Call Claude via OpenRouter"""
    resp = requests.post(OPENROUTER_BASE,
        headers={"Authorization": f"Bearer {OPENROUTER_API_KEY}", "Content-Type": "application/json"},
        json={"model": MODEL, "messages": [{"role": "user", "content": prompt}],
              "max_tokens": 4000, "temperature": 0.1})
    data = resp.json()
    try:
        return data["choices"][0]["message"]["content"].strip()
    except Exception as e:
        print(f"  ❌ Claude error: {e}")
        sys.exit(1)

def create_session():
    """Create Browserbase session"""
    print("  🌐 Starting cloud browser...")
    resp = requests.post(
        "https://www.browserbase.com/v1/sessions",
        headers={"x-bb-api-key": BROWSERBASE_API_KEY, "Content-Type": "application/json"},
        json={"projectId": BROWSERBASE_PROJECT, "browserSettings": {"stealth": True}})
    data = resp.json()
    session_id = data.get("id")
    if not session_id:
        print(f"  ❌ Session error: {data}")
        return None, None
    connect_url = data.get("connectUrl") or f"wss://connect.browserbase.com?apiKey={BROWSERBASE_API_KEY}&sessionId={session_id}"
    print(f"  ✅ Session: {session_id}")
    return session_id, connect_url

def end_session(session_id):
    """Close Browserbase session"""
    requests.delete(f"https://www.browserbase.com/v1/sessions/{session_id}",
        headers={"x-bb-api-key": BROWSERBASE_API_KEY})
    print("  🔒 Session closed")

def screenshot(page, name):
    """Take screenshot"""
    Path("outputs/screenshots").mkdir(parents=True, exist_ok=True)
    path = f"outputs/screenshots/{name}.png"
    page.screenshot(path=path)
    print(f"  📸 {path}")
    return path

def find_tailored_files(company, title):
    """Find tailored resume and cover letter PDFs"""
    tailored_dir = Path("outputs/tailored")
    if not tailored_dir.exists():
        print("  ⚠️  No tailored directory")
        return None, None
    
    company_norm = re.sub(r'[^a-zA-Z0-9]+', '_', company).strip('_')
    resume = None
    cover_letter = None
    
    # Try PDF first, then TXT
    for ext in ['.pdf', '.txt']:
        for file in tailored_dir.glob(f"*_RESUME{ext}"):
            filename = file.stem.lower()
            if company_norm.lower() in filename:
                title_words = [w.lower() for w in title.split() if len(w) > 3]
                if any(word in filename for word in title_words[:3]):
                    resume = str(file.absolute())
                    cover_file = file.parent / file.name.replace(f"_RESUME{ext}", f"_COVER_LETTER{ext}")
                    if cover_file.exists():
                        cover_letter = str(cover_file.absolute())
                    print(f"  📄 Resume: {file.name}")
                    if cover_letter:
                        print(f"  📄 Cover: {cover_file.name}")
                    break
        if resume:
            break
    
    if not resume:
        print(f"  ⚠️  No resume for {company}")
    
    return resume, cover_letter

def classify_page(page_text, job_title, company):
    """Determine what type of page we're on"""
    prompt = f"""
We're applying for: "{job_title}" at {company}

Page content (first 3000 chars):
{page_text[:3000]}

Return ONLY JSON:
{{
  "page_type": "job_search_results | individual_job_page | application_form | login_required | error | confirmation",
  "summary": "brief description",
  "has_apply_button": false,
  "apply_button_text": "exact button text or empty"
}}
"""
    raw = ask_claude(prompt).strip()
    if "```" in raw:
        raw = raw.split("```")[1].lstrip("json").strip()
    try:
        return json.loads(raw)
    except:
        return {"page_type": "unknown", "summary": "parse error", "has_apply_button": False}

def get_form_fields(page_text, profile, job, resume_path, cover_letter_path):
    """Ask Claude to detect ALL form fields"""
    prompt = f"""
Analyze this job application form for: {job.get('title')} @ {job.get('company')}

Candidate Info:
- Name: {profile['personal'].get('name')}
- Email: {profile['personal'].get('email')}
- Phone: {profile['personal'].get('phone')}
- Country: United States
- Location: {profile['personal'].get('location')}
- LinkedIn: {profile['personal'].get('linkedin_url')}
- Years experience: {profile.get('years_of_experience')}
- Work auth US: Yes (no sponsorship needed)
- Saved answers: {json.dumps(profile.get('extra_answers', {}))}

FILES AVAILABLE:
- Resume: {"YES" if resume_path else "NO"}
- Cover letter: {"YES" if cover_letter_path else "NO"}

CRITICAL: Detect ALL fields including required (*) and optional voluntary self-ID fields.

Required: First Name, Last Name, Email, Phone, Country, Location, Resume, Work auth, Visa, LinkedIn, Full legal name, How did you hear, Do you know anyone

Optional: Gender (Male), Hispanic/Latino (No), Veteran Status (I am not a protected veteran), Disability Status (I don't have a disability)

RULES:
- Detect ALL fields, no limit
- For file uploads: type="file", answer="RESUME_FILE" or "COVER_LETTER_FILE"
- For React-Select dropdowns (role=combobox): type="react-select"
  * ONLY these are dropdowns: Country, Work auth, Visa, Gender, Hispanic/Latino, Veteran, Disability, Secret Clearance
  * Country: answer="United States"
  * Gender: answer="Male"
  * Others: use specified answers
- For Location/City autocomplete: type="autocomplete"
- For TEXT fields: type="text"
  * "How did you hear": type="text", answer=saved_answers or "LinkedIn"
  * "Do you know anyone": type="text", answer="No"
  * "LinkedIn Profile": type="text", use linkedin_url
  * "Legal name"/"Full name": type="text", use name
  * First/Last Name, Email, Phone: type="text"

Page content:
{page_text[:5000]}

Return ONLY JSON:
{{
  "fields": [
    {{"label": "First Name", "type": "text", "answer": "Alex"}},
    {{"label": "Location", "type": "autocomplete", "answer": "Florence, SC"}},
    {{"label": "Resume/CV", "type": "file", "answer": "RESUME_FILE"}},
    {{"label": "Work auth?", "type": "react-select", "answer": "Yes"}}
  ],
  "is_final_page": true,
  "continue_button": ""
}}
"""
    raw = ask_claude(prompt).strip()
    if "```" in raw:
        raw = raw.split("```")[1].lstrip("json").strip()
    try:
        return json.loads(raw)
    except:
        return {"fields": [], "is_final_page": True, "continue_button": ""}

def fill_react_select(page, label, answer):
    """Fill React-Select dropdown - TYPE into search input first!"""
    try:
        # Find label element
        label_el = page.locator(f"label:has-text('{label}')").first
        
        # Try fuzzy match if exact fails
        if label_el.count() == 0:
            key_words = [w for w in label.split() if len(w) > 4][:3]
            for word in key_words:
                label_el = page.locator(f"label:has-text('{word}')").first
                if label_el.count() > 0:
                    break
        
        if label_el.count() > 0:
            for_id = label_el.get_attribute("for")
            if for_id:
                # Find combobox by ID
                combobox = page.locator(f"#{for_id}")
                if combobox.count() > 0:
                    # Step 1: Click to open dropdown
                    combobox.click()
                    time.sleep(0.5)
                    
                    # Step 2: TYPE into the search input that appears!
                    # This is the key step I was missing
                    search_input = page.locator(f"input#{for_id}")
                    if search_input.count() > 0:
                        search_input.type(answer, delay=50)
                        time.sleep(0.8)  # Wait for options to filter
                    
                    # Step 3: Click the matching option
                    option = page.get_by_text(answer, exact=True).first
                    if option.count() > 0 and option.is_visible():
                        option.click()
                        time.sleep(0.5)
                        return True
                    
                    # Fallback: try partial match
                    option = page.locator(f"div[class*='option']:has-text('{answer}')").first
                    if option.count() > 0 and option.is_visible():
                        option.click()
                        time.sleep(0.5)
                        return True
        
        return False
    except Exception as e:
        print(f"    React-Select error: {e}")
        return False

def fill_autocomplete(page, label, answer):
    """Fill Location autocomplete - type city, find match with state"""
    try:
        # Find field
        autocomplete = page.get_by_label(label, exact=False)
        
        if autocomplete.count() == 0:
            label_el = page.locator(f"label:has-text('{label}')").first
            if label_el.count() == 0:
                label_el = page.locator("label:has-text('Location')").first
            
            if label_el.count() > 0:
                input_id = label_el.get_attribute("for")
                if input_id:
                    autocomplete = page.locator(f"#{input_id}")
        
        if autocomplete.count() > 0:
            # Extract city and state from answer (e.g., "Florence, SC")
            city = answer.split(",")[0].strip() if "," in answer else answer
            state = answer.split(",")[1].strip() if "," in answer else ""
            
            # Click and type just the CITY name
            autocomplete.click()
            time.sleep(0.5)
            autocomplete.fill("")
            time.sleep(0.3)
            autocomplete.type(city, delay=100)
            time.sleep(2.0)  # Wait for options to appear
            
            # Get ALL visible options
            options = page.locator("div[class*='option']").all()
            print(f"      Found {len(options)} location options")
            
            # Look for option matching our state
            for opt in options:
                try:
                    if not opt.is_visible():
                        continue
                    text = opt.inner_text()
                    print(f"      Option: {text[:60]}")
                    
                    # Check if this option matches our state
                    if state and (state in text or "South Carolina" in text):
                        print(f"      ✅ Matched: {text[:50]}")
                        opt.click(force=True)
                        time.sleep(1.0)
                        
                        if autocomplete.input_value():
                            print(f"      ✅ Selected: {autocomplete.input_value()[:50]}")
                            return True
                except:
                    continue
            
            # If no state match, just take first option
            print(f"      No state match, trying first option...")
            if len(options) > 0 and options[0].is_visible():
                options[0].click(force=True)
                time.sleep(1.0)
                if autocomplete.input_value():
                    print(f"      ✅ Selected: {autocomplete.input_value()[:50]}")
                    return True
            
            print(f"      ⚠️  Location failed")
            return False
        
        return False
    except Exception as e:
        print(f"    Autocomplete error: {e}")
        return False

def run_application(connect_url, job, profile, resume_path, cover_letter_path, dry_run):
    """Run the application flow"""
    title = job.get("title", "")
    company = job.get("company", "")
    url = job.get("apply_url", "")
    slug = company.replace(" ", "_")

    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            print(f"  🔌 Connecting...")
            browser = p.chromium.connect_over_cdp(connect_url)
            ctx = browser.contexts[0] if browser.contexts else browser.new_context()
            page = ctx.pages[0] if ctx.pages else ctx.new_page()

            # Load URL
            print(f"  🔗 Loading {url[:60]}...")
            page.goto(url, wait_until="domcontentloaded", timeout=30000)
            time.sleep(3)
            screenshot(page, f"{slug}_01_start")

            page_text = page.inner_text("body")
            info = classify_page(page_text, title, company)
            print(f"  📄 {info['page_type']} - {info['summary']}")

            # Click Apply if on job page
            if info.get("has_apply_button"):
                btn_text = info.get("apply_button_text", "Apply")
                print(f"  🖱️  Clicking: {btn_text}")
                for pattern in [btn_text, "Apply", "Apply Now"]:
                    try:
                        btn = page.get_by_role("button", name=pattern)
                        if btn.count() == 0:
                            btn = page.get_by_role("link", name=pattern)
                        if btn.count() > 0:
                            btn.first.click()
                            time.sleep(3)
                            break
                    except:
                        continue
                screenshot(page, f"{slug}_02_form_opened")

            # Process form pages
            page_num = 1
            while page_num <= 10:
                print(f"\n  📋 Page {page_num}")
                print(f"  {'─'*50}")
                
                page_text = page.inner_text("body")
                form_data = get_form_fields(page_text, profile, job, resume_path, cover_letter_path)
                fields = form_data.get("fields", [])
                is_final = form_data.get("is_final_page", True)
                continue_btn = form_data.get("continue_button", "")
                
                print(f"  ✅ Found {len(fields)} fields")
                if not is_final:
                    print(f"  📍 Intermediate page (Continue: {continue_btn})")
                
                # Show fill plan
                print(f"\n  📋 Fill plan:")
                for f in fields:
                    ans = f.get("answer", "")
                    if ans == "RESUME_FILE":
                        ans = f"📄 {Path(resume_path).name if resume_path else 'NO FILE'}"
                    elif ans == "COVER_LETTER_FILE":
                        ans = f"📄 {Path(cover_letter_path).name if cover_letter_path else 'NO FILE'}"
                    print(f"  ✅ {f.get('label')}: {str(ans)[:60]}")
                print(f"  {'─'*50}")
                
                if dry_run:
                    screenshot(page, f"{slug}_page{page_num}_preview")
                    print(f"\n  [DRY RUN] Analyzed page {page_num}")
                    if not is_final:
                        print(f"  [DRY RUN] Would continue to next page")
                    else:
                        print(f"  [DRY RUN] Would stop before submit")
                    browser.close()
                    return "dry_run_ok"
                
                # Fill fields
                print(f"\n  ✏️  Filling fields...")
                for f in fields:
                    label = f.get("label", "")
                    answer = f.get("answer", "")
                    ftype = f.get("type", "text")
                    
                    if not answer:
                        continue
                    
                    # File uploads
                    if ftype == "file":
                        file_path = None
                        if answer == "RESUME_FILE" and resume_path:
                            file_path = resume_path
                        elif answer == "COVER_LETTER_FILE" and cover_letter_path:
                            file_path = cover_letter_path
                        
                        if file_path:
                            try:
                                # Try multiple file input selectors
                                selectors = ["input[type='file']"]
                                if "resume" in label.lower() or "cv" in label.lower():
                                    selectors = [
                                        "input[type='file'][id='resume']",
                                        "input[type='file'][name*='resume']",
                                        "input[type='file']"
                                    ]
                                elif "cover" in label.lower():
                                    selectors = [
                                        "input[type='file'][id='cover_letter']",
                                        "input[type='file'][name*='cover']",
                                        "input[type='file']"
                                    ]
                                
                                for sel in selectors:
                                    try:
                                        el = page.locator(sel).first
                                        if el.count() > 0:
                                            el.set_input_files(file_path)
                                            print(f"    ✅ {label} (uploaded {Path(file_path).name})")
                                            break
                                    except:
                                        continue
                            except Exception as e:
                                print(f"    ⚠️  {label}: {e}")
                        continue
                    
                    # React-Select dropdowns
                    if ftype == "react-select":
                        if fill_react_select(page, label, answer):
                            print(f"    ✅ {label} = {answer}")
                        else:
                            print(f"    ⚠️  {label}: Dropdown failed")
                        continue
                    
                    # Location autocomplete
                    if ftype == "autocomplete":
                        if fill_autocomplete(page, label, answer):
                            print(f"    ✅ {label} (autocomplete)")
                        else:
                            print(f"    ⚠️  {label}: Autocomplete failed")
                        continue
                    
                    # Regular text/number fields
                    try:
                        el = page.get_by_label(label).first
                        if el.count() > 0:
                            el.fill(str(answer))
                            print(f"    ✅ {label}")
                    except Exception as e:
                        print(f"    ⚠️  {label}: {e}")
                
                screenshot(page, f"{slug}_page{page_num}_filled")
                
                # If intermediate page, click Continue
                if not is_final and continue_btn:
                    print(f"\n  ➡️  Clicking: {continue_btn}")
                    clicked = False
                    for pattern in [continue_btn, "Continue", "Next"]:
                        try:
                            btn = page.get_by_role("button", name=pattern)
                            if btn.count() > 0:
                                btn.first.click()
                                time.sleep(3)
                                page_num += 1
                                clicked = True
                                print(f"  ✅ Moving to page {page_num}")
                                break
                        except:
                            continue
                    
                    if not clicked:
                        print(f"  ⚠️  Continue button not found")
                        browser.close()
                        return "continue_error"
                    continue
                
                # Final page - prompt for submission
                print(f"\n  📸 Review form:")
                print(f"     open outputs/screenshots/{slug}_page{page_num}_filled.png")
                
                confirm = input("\n  Type YES to submit, SKIP to skip: ").strip().upper()
                if confirm == "YES":
                    # Submit
                    for pattern in ["Submit Application", "Submit", "Apply"]:
                        try:
                            btn = page.get_by_role("button", name=pattern)
                            if btn.count() > 0:
                                btn.first.click()
                                time.sleep(3)
                                screenshot(page, f"{slug}_submitted")
                                print(f"  🎉 Submitted!")
                                browser.close()
                                return "submitted"
                        except:
                            continue
                    browser.close()
                    return "submit_error"
                else:
                    browser.close()
                    return "user_skipped"
            
            # Max pages reached
            browser.close()
            return "max_pages_exceeded"

    except Exception as e:
        print(f"  ❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return "error"

def main():
    parser = argparse.ArgumentParser(description="Job Bot Auto-Apply Engine - 100% Automation")
    parser.add_argument("--jobs", default="profiles/scored_jobs.json")
    parser.add_argument("--profile", default="profiles/job_profile.json")
    parser.add_argument("--min-score", type=int, default=50)
    parser.add_argument("--dry-run", action="store_true", help="Analyze only, no submission")
    args = parser.parse_args()

    print("\n🚀 Job Bot — Auto-Apply Engine v2.0")
    print("="*60)
    if args.dry_run:
        print("  ⚠️  DRY RUN MODE\n")

    jobs = json.loads(Path(args.jobs).read_text())
    profile = json.loads(Path(args.profile).read_text())
    qualified = [j for j in jobs if j.get("score", 0) >= args.min_score]
    results = []

    print(f"  ✅ {len(qualified)} jobs to process\n")

    for i, job in enumerate(qualified, 1):
        title = job.get('title', '')
        company = job.get('company', '')
        score = job.get('score', 0)
        url = job.get('apply_url', '')

        print(f"\n{'='*60}")
        print(f"  🎯 [{i}/{len(qualified)}] {title} @ {company} ({score}%)")
        print(f"{'='*60}")

        if not url:
            results.append({"job": title, "company": company, "status": "no_url"})
            continue

        # Find resume files
        resume_path, cover_letter_path = find_tailored_files(company, title)
        if not resume_path:
            results.append({"job": title, "company": company, "status": "no_resume"})
            continue

        # Create browser session
        session_id, connect_url = create_session()
        if not session_id:
            results.append({"job": title, "company": company, "status": "session_error"})
            continue

        try:
            status = run_application(connect_url, job, profile, resume_path, cover_letter_path, args.dry_run)
            results.append({"job": title, "company": company, "status": status, "score": score})
            print(f"\n  ➡️  Result: {status}")
        finally:
            end_session(session_id)

    # Save results
    Path("outputs/application_log.json").write_text(json.dumps(results, indent=2))
    
    print(f"\n{'='*60}")
    print(f"✅ Complete!\n")
    
    icons = {"submitted":"🎉", "dry_run_ok":"✅", "user_skipped":"⏭️", "error":"❌", "no_resume":"⚠️"}
    for r in results:
        icon = icons.get(r.get("status", ""), "•")
        print(f"  {icon} {r['company']} → {r['status']}")
    
    print(f"\n  📸 open outputs/screenshots/")

if __name__ == "__main__":
    main()
