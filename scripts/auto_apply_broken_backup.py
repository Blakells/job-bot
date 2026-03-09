#!/usr/bin/env python3
"""
Phase 4: Auto-Apply Engine - 100% Automation
Features: File upload, multi-page forms, React-Select dropdowns, location autocomplete
"""

import json, os, sys, time, argparse
from pathlib import Path
import requests

BROWSERBASE_API_KEY = os.environ.get("BROWSERBASE_API_KEY", "")
BROWSERBASE_PROJECT = os.environ.get("BROWSERBASE_PROJECT_ID", "")
OPENROUTER_API_KEY  = os.environ.get("OPENROUTER_API_KEY", "")
OPENROUTER_BASE     = "https://openrouter.ai/api/v1/chat/completions"
MODEL               = "anthropic/claude-sonnet-4-5"

def ask_claude(prompt):
    resp = requests.post(OPENROUTER_BASE,
        headers={"Authorization": f"Bearer {OPENROUTER_API_KEY}", "Content-Type": "application/json"},
        json={"model": MODEL, "messages": [{"role": "user", "content": prompt}],
              "max_tokens": 3000, "temperature": 0.1})
    data = resp.json()
    try:
        return data["choices"][0]["message"]["content"].strip()
    except Exception as e:
        print(f"  ❌ Claude error: {e}")
        sys.exit(1)

def create_session():
    print("  🌐 Starting cloud browser session...")
    resp = requests.post(
        "https://www.browserbase.com/v1/sessions",
        headers={"x-bb-api-key": BROWSERBASE_API_KEY, "Content-Type": "application/json"},
        json={"projectId": BROWSERBASE_PROJECT, "browserSettings": {"stealth": True}})
    data = resp.json()
    session_id = data.get("id")
    if not session_id:
        print(f"  ❌ Session error: {data}")
        return None, None
    connect_url = data.get("connectUrl") or \
                  f"wss://connect.browserbase.com?apiKey={BROWSERBASE_API_KEY}&sessionId={session_id}"
    print(f"  ✅ Session: {session_id}")
    return session_id, connect_url

def end_session(session_id):
    requests.delete(f"https://www.browserbase.com/v1/sessions/{session_id}",
        headers={"x-bb-api-key": BROWSERBASE_API_KEY})
    print("  🔒 Session closed")

def screenshot(page, name):
    Path("outputs/screenshots").mkdir(parents=True, exist_ok=True)
    path = f"outputs/screenshots/{name}.png"
    page.screenshot(path=path)
    print(f"  📸 {path}")
    return path

def classify_page(page_text, job_title, company):
    """Ask Claude what kind of page we're on and what to do."""
    prompt = f"""
We're trying to apply for: "{job_title}" at {company}

Page content (first 3000 chars):
{page_text[:3000]}

What page is this? Return ONLY JSON:
{{
  "page_type": "job_search_results | individual_job_page | application_form | login_required | error | confirmation",
  "summary": "one sentence",
  "target_job_visible": true,
  "target_job_title_on_page": "exact job title text as it appears on page, or empty string",
  "target_job_location": "location of the correct job listing to click (e.g. Remote - US)",
  "has_apply_button": false,
  "apply_button_text": "exact text of apply button or empty string"
}}
"""
    raw = ask_claude(prompt).strip()
    if "```" in raw:
        raw = raw.split("```")[1].lstrip("json").strip().rstrip("```")
    try:
        return json.loads(raw)
    except:
        return {"page_type": "unknown", "summary": "parse error",
                "target_job_visible": False, "has_apply_button": False}

def get_form_fields(page_text, profile, job):
    """Ask Claude to identify all form fields and best answers."""
    prompt = f"""
Fill out this job application form for: {job.get('title')} @ {job.get('company')}

Candidate:
- Name: {profile['personal'].get('name')}
- Email: {profile['personal'].get('email')}
- Phone: {profile['personal'].get('phone')}
- Location: {profile['personal'].get('location')}
- LinkedIn: {profile['personal'].get('linkedin_url')}
- Years experience: {profile.get('years_of_experience')}
- Skills: {', '.join(profile.get('hard_skills', [])[:10])}
- Education: {json.dumps(profile.get('education', []))}
- Work authorization: {json.dumps(profile.get('work_authorization', {}))}
- Saved answers: {json.dumps(profile.get('extra_answers', {}))}

IMPORTANT RULES:
- If a question asks about work authorization for the SPECIFIC COUNTRY the job is in, answer based on work_authorization above
- Never reuse a saved answer for a different country than it was originally for
- "Authorized to work in the US/United States?" = Yes (US citizen, no sponsorship needed)
- "Require visa sponsorship?" = No
- "How did you hear about this job?" = LinkedIn (from saved answers)
- "LinkedIn URL/Profile" = use the linkedin_url from personal info
- "Do you know anyone who works at/currently works at" = No (from saved answers)
- "Full legal name" or "Legal name" = use the name from personal info
- For location fields with autocomplete, return just the city (e.g. "Florence")

Page content:
{page_text[:4000]}

Return ONLY JSON:
{{
  "form_fields": [
    {{
      "label": "First Name",
      "type": "text",
      "answer": "Alex",
      "confident": true,
      "selector": "input[name='firstName']",
      "is_react_select": false,
      "is_autocomplete": false,
      "is_file_upload": false
    }},
    {{
      "label": "Location",
      "type": "autocomplete",
      "answer": "Florence",
      "confident": true,
      "selector": "#candidate-location",
      "is_react_select": true,
      "is_autocomplete": true,
      "is_file_upload": false
    }},
    {{
      "label": "Resume",
      "type": "file",
      "answer": "",
      "confident": true,
      "selector": "input[type='file']",
      "is_react_select": false,
      "is_autocomplete": false,
      "is_file_upload": true
    }},
    {{
      "label": "Require visa sponsorship?",
      "type": "select",
      "answer": "UNCERTAIN",
      "confident": false,
      "question": "Do you need visa sponsorship to work in the US?",
      "selector": "",
      "is_react_select": true,
      "is_autocomplete": false,
      "is_file_upload": false
    }}
  ],
  "submit_button": "Submit Application",
  "has_continue_button": false,
  "continue_button_text": ""
}}
"""
    raw = ask_claude(prompt).strip()
    if "```" in raw:
        raw = raw.split("```")[1].lstrip("json").strip().rstrip("```")
    try:
        return json.loads(raw)
    except:
        return {"form_fields": [], "submit_button": "Submit", "has_continue_button": False}

def ask_user(uncertain_fields, memory):
    new = {}
    todo = [f for f in uncertain_fields
            if not f.get("confident") and f.get("label") not in memory]
    if not todo:
        return new
    print("\n  ❓ Quick questions:\n")
    for f in todo:
        q = f.get("question", f"What to enter for '{f.get('label')}'?")
        print(f"  Q: {q}")
        new[f.get("label")] = input("  A: ").strip()
    return new

def find_resume_file():
    """Find resume/CV in uploads folder, prioritize PDF."""
    uploads = Path("uploads")
    if not uploads.exists():
        return None
    
    # Prioritize PDFs
    pdfs = list(uploads.glob("*.pdf"))
    if pdfs:
        return str(pdfs[0].absolute())
    
    # Fall back to docx
    docx = list(uploads.glob("*.docx"))
    if docx:
        return str(docx[0].absolute())
    
    return None

def fill_react_select_dropdown(page, field, answer):
    """Fill React-Select dropdown using the EXACT working pattern from test_dropdown_direct.py"""
    label = field.get("label", "")
    selector = field.get("selector", "")
    
    try:
        # Method 1: If we have a selector, use it directly
        if selector:
            print(f"    🔍 Using selector: {selector}")
            combobox = page.locator(selector)
        else:
            # Method 2: Find label and get the "for" attribute
            print(f"    🔍 Finding label: '{label}'")
            label_el = page.locator(f"label:has-text('{label}')").first
            if label_el.count() > 0:
                for_id = label_el.get_attribute("for")
                print(f"    ✅ Found label, for='{for_id}'")
                if for_id:
                    combobox = page.locator(f"#{for_id}")
                else:
                    return False
            else:
                return False
        
        if combobox.count() == 0:
            print(f"    ❌ Combobox not found")
            return False
        
        # Click to open dropdown
        print(f"    🖱️  Clicking combobox to open dropdown...")
        combobox.click()
        time.sleep(1)
        
        # Find and click option
        print(f"    🔍 Looking for option: '{answer}'")
        
        # Try different option selectors
        option = page.locator(f"div[class*='option']:has-text('{answer}')").first
        if option.count() == 0:
            option = page.get_by_role("option", name=answer).first
        
        if option.count() > 0 and option.is_visible():
            print(f"    ✅ Found option - clicking it...")
            option.click()
            time.sleep(0.5)
            print(f"    ✅ Selected: {answer}")
            return True
        else:
            print(f"    ❌ Could not find visible option")
            return False
            
    except Exception as e:
        print(f"    ⚠️  Error: {e}")
        return False

def fill_location_autocomplete(page, field, answer):
    """Fill location autocomplete (type city, wait, click first option)"""
    selector = field.get("selector", "")
    label = field.get("label", "")
    
    try:
        # Find the input
        if selector:
            input_el = page.locator(selector)
        else:
            input_el = page.get_by_label(label)
        
        if input_el.count() == 0:
            return False
        
        # Click and type the city name
        print(f"    ⌨️  Typing: {answer}")
        input_el.first.click()
        time.sleep(0.5)
        input_el.first.type(answer, delay=100)  # Use .type() not .fill()
        time.sleep(1.5)  # Wait for suggestions
        
        # Click first option
        print(f"    🔍 Looking for suggestion...")
        option = page.locator("div[class*='option']").first
        if option.count() == 0:
            option = page.get_by_role("option").first
        
        if option.count() > 0 and option.is_visible():
            print(f"    ✅ Clicking first suggestion")
            option.click()
            time.sleep(0.5)
            return True
        else:
            print(f"    ⚠️  No suggestions appeared")
            return False
            
    except Exception as e:
        print(f"    ⚠️  Error: {e}")
        return False

def upload_file(page, field):
    """Handle file upload with PDF prioritization"""
    selector = field.get("selector", "")
    label = field.get("label", "")
    
    resume_file = find_resume_file()
    if not resume_file:
        print(f"    ⚠️  No resume found in uploads/ folder")
        return False
    
    try:
        # Find file input
        if selector:
            file_input = page.locator(selector)
        else:
            file_input = page.locator("input[type='file']").filter(has_text=label).first
            if file_input.count() == 0:
                file_input = page.locator("input[type='file']").first
        
        if file_input.count() == 0:
            print(f"    ❌ File input not found")
            return False
        
        print(f"    📎 Uploading: {Path(resume_file).name}")
        file_input.first.set_input_files(resume_file)
        time.sleep(1)
        print(f"    ✅ File uploaded")
        return True
        
    except Exception as e:
        print(f"    ⚠️  Upload error: {e}")
        return False

def fill_field(page, field, all_answers):
    """Universal field filler - handles all field types"""
    label = field.get("label", "")
    answer = field.get("answer", "")
    selector = field.get("selector", "")
    ftype = field.get("type", "text")
    is_react_select = field.get("is_react_select", False)
    is_autocomplete = field.get("is_autocomplete", False)
    is_file_upload = field.get("is_file_upload", False)
    
    # Resolve UNCERTAIN answers
    if answer == "UNCERTAIN":
        answer = all_answers.get(label, "")
    
    if not answer and not is_file_upload:
        return False
    
    try:
        # File upload
        if is_file_upload:
            return upload_file(page, field)
        
        # React-Select dropdown (Greenhouse style)
        if is_react_select and not is_autocomplete:
            return fill_react_select_dropdown(page, field, answer)
        
        # Location autocomplete
        if is_autocomplete:
            return fill_location_autocomplete(page, field, answer)
        
        # Standard fields
        el = None
        if selector:
            el = page.locator(selector)
        if not el or el.count() == 0:
            el = page.get_by_label(label)
        
        if el and el.count() > 0:
            if ftype == "select":
                el.first.select_option(answer)
            else:
                el.first.fill(str(answer))
            print(f"    ✅ {label}")
            return True
        else:
            print(f"    ⚠️  {label}: element not found")
            return False
            
    except Exception as e:
        print(f"    ⚠️  {label}: {e}")
        return False

def run_application(connect_url, job, profile, memory, dry_run, auto_submit):
    title   = job.get("title", "")
    company = job.get("company", "")
    url     = job.get("apply_url", "")
    slug    = company.replace(" ", "_")
    all_answers = dict(memory)
    new_answers = {}
    page_num = 1

    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            print(f"  🔌 Connecting...")
            browser = p.chromium.connect_over_cdp(connect_url)
            ctx  = browser.contexts[0] if browser.contexts else browser.new_context()
            page = ctx.pages[0] if ctx.pages else ctx.new_page()

            # ── STEP 1: Load starting URL ────────────────────────────────
            print(f"  🔗 Loading {url[:60]}...")
            page.goto(url, wait_until="domcontentloaded", timeout=30000)
            time.sleep(3)
            screenshot(page, f"{slug}_01_start")

            page_text = page.inner_text("body")
            info      = classify_page(page_text, title, company)
            print(f"  📄 Page type: {info['page_type']} — {info['summary']}")

            # ── STEP 2: If search results, click on the job title ────────
            if info["page_type"] == "job_search_results":
                job_title_on_page = info.get("target_job_title_on_page", "")
                clicked = False

                if job_title_on_page:
                    print(f"  🖱️  Clicking job title: '{job_title_on_page}'...")
                    try:
                        # Get all links matching the job title
                        matches = page.get_by_role("link").filter(has_text=job_title_on_page)
                        count = matches.count()
                        print(f"  🔍 Found {count} matching links")

                        # Prefer US/Remote-US over other locations
                        best = None
                        location_pref = profile.get("remote_preference", "")
                        for idx in range(count):
                            el = matches.nth(idx)
                            # Look at surrounding text for location hints
                            try:
                                parent_text = el.locator("xpath=..").inner_text()
                                if "United States" in parent_text or "Remote - US" in parent_text or "US" in parent_text:
                                    best = el
                                    print(f"  🎯 Found US location match!")
                                    break
                            except:
                                pass
                        
                        # Fall back to first match if no US match found
                        if best is None:
                            best = matches.first
                            print(f"  ⚠️  No US match found, using first result")
                        
                        best.click(timeout=10000)
                        time.sleep(3)
                        clicked = True
                        print(f"  ✅ Clicked job title!")
                    except Exception as e:
                        print(f"  ⚠️  Could not click by text: {e}")

                if not clicked:
                    # Try searching on the page for key words from job title
                    words = title.split()[:3]
                    for word in words:
                        try:
                            matches = page.get_by_role("link").filter(has_text=word)
                            if matches.count() > 0:
                                matches.first.click(timeout=10000)
                                time.sleep(3)
                                clicked = True
                                print(f"  ✅ Clicked link containing '{word}'")
                                break
                        except:
                            continue

                if not clicked:
                    print(f"  ⚠️  Could not find job listing to click")
                    screenshot(page, f"{slug}_no_job_found")
                    browser.close()
                    return "no_job_found", new_answers

                screenshot(page, f"{slug}_02_job_page")
                page_text = page.inner_text("body")
                info      = classify_page(page_text, title, company)
                print(f"  📄 Now on: {info['page_type']} — {info['summary']}")

            # ── STEP 3: On individual job page — click Apply ─────────────
            if info["page_type"] == "individual_job_page" and info.get("has_apply_button"):
                btn_text = info.get("apply_button_text", "Apply Now")
                print(f"  🖱️  Clicking Apply: '{btn_text}'...")
                clicked = False
                for pattern in [btn_text, "Apply Now", "Apply for this job",
                                 "Quick Apply", "Apply", "Apply on company site"]:
                    try:
                        btn = page.get_by_role("button", name=pattern)
                        if btn.count() == 0:
                            btn = page.get_by_role("link", name=pattern)
                        if btn.count() > 0:
                            btn.first.click(timeout=10000)
                            time.sleep(3)
                            clicked = True
                            print(f"  ✅ Clicked: '{pattern}'")
                            break
                    except:
                        continue

                if clicked:
                    screenshot(page, f"{slug}_03_after_apply_click")
                    page_text = page.inner_text("body")
                    info      = classify_page(page_text, title, company)
                    print(f"  📄 Now on: {info['page_type']} — {info['summary']}")

            # ── STEP 4: Login wall ───────────────────────────────────────
            if info["page_type"] == "login_required":
                print(f"  🔐 Login required — skipping (Phase 5 will handle auth)")
                screenshot(page, f"{slug}_login_wall")
                browser.close()
                return "login_required", new_answers

            # ── STEP 5: Application form (with multi-page support) ───────
            while info["page_type"] in ["application_form", "individual_job_page"]:
                print(f"\n  📋 Analyzing form (Page {page_num})...")
                page_text = page.inner_text("body")
                form = get_form_fields(page_text, profile, job)
                fields = form.get("form_fields", [])
                has_continue = form.get("has_continue_button", False)
                print(f"  ✅ Found {len(fields)} fields")

                # Ask user for uncertain answers
                uncertain   = [f for f in fields if not f.get("confident")]
                extra       = ask_user(uncertain, all_answers)
                new_answers.update(extra)
                all_answers.update(extra)

                # Show fill plan
                print(f"\n  📋 Fill plan:")
                print(f"  {'─'*50}")
                for f in fields:
                    ans = f.get("answer", "")
                    if ans == "UNCERTAIN":
                        ans = all_answers.get(f.get("label",""), "⚠️ NO ANSWER")
                    icon = "✅" if f.get("confident") else "📝"
                    if f.get("is_file_upload"):
                        ans = "📎 Resume"
                    print(f"  {icon} {f.get('label','')}: {str(ans)[:60]}")
                print(f"  {'─'*50}")

                if dry_run:
                    screenshot(page, f"{slug}_{str(page_num).zfill(2)}_form_preview")
                    print(f"\n  [DRY RUN] Would fill {len(fields)} fields — not submitting")
                    browser.close()
                    return "dry_run_ok", new_answers

                # Fill fields
                print(f"\n  ✏️  Filling fields...")
                for f in fields:
                    fill_field(page, f, all_answers)

                screenshot(page, f"{slug}_{str(page_num).zfill(2)}_filled")
                
                # Check if there's a Continue button or Submit
                if has_continue:
                    continue_text = form.get("continue_button_text", "Continue")
                    print(f"\n  ➡️  Looking for Continue button: '{continue_text}'")
                    clicked = False
                    for pattern in [continue_text, "Continue", "Next", "Continue to Next Step"]:
                        try:
                            btn = page.get_by_role("button", name=pattern)
                            if btn.count() > 0:
                                btn.first.click()
                                time.sleep(3)
                                clicked = True
                                print(f"  ✅ Clicked: '{pattern}'")
                                page_num += 1
                                break
                        except:
                            continue
                    
                    if not clicked:
                        print(f"  ⚠️  Could not find Continue button")
                        break
                    
                    # Re-classify the new page
                    page_text = page.inner_text("body")
                    info = classify_page(page_text, title, company)
                    print(f"  📄 Now on: {info['page_type']} — {info['summary']}")
                    
                else:
                    # Final page - submit
                    print(f"\n  📸 Check filled form:")
                    print(f"     open outputs/screenshots/{slug}_{str(page_num).zfill(2)}_filled.png")

                    if not auto_submit:
                        confirm = input("\n  Type YES to submit, SKIP to skip: ").strip().upper()
                    else:
                        confirm = "YES"
                        print("\n  🤖 Auto-submit enabled - submitting...")
                    
                    if confirm == "YES":
                        submit = form.get("submit_button", "Submit")
                        for pattern in [submit, "Submit Application", "Submit", "Apply"]:
                            try:
                                btn = page.get_by_role("button", name=pattern)
                                if btn.count() > 0:
                                    btn.first.click()
                                    time.sleep(3)
                                    screenshot(page, f"{slug}_final_submitted")
                                    print(f"  🎉 Submitted!")
                                    browser.close()
                                    return "submitted", new_answers
                            except:
                                continue
                        browser.close()
                        return "submit_error", new_answers
                    else:
                        browser.close()
                        return "user_skipped", new_answers
            
            # Unexpected page
            print(f"  ⚠️  Ended on unexpected page type: {info['page_type']}")
            screenshot(page, f"{slug}_unexpected")
            browser.close()
            return f"unexpected_{info['page_type']}", new_answers

    except Exception as e:
        print(f"  ❌ Error: {e}")
        import traceback; traceback.print_exc()
        return "error", new_answers

def main():
    parser = argparse.ArgumentParser(description="Job Bot Auto-Apply Engine with 100% automation")
    parser.add_argument("--jobs",      default="profiles/scored_jobs.json", help="Path to scored jobs JSON")
    parser.add_argument("--profile",   default="profiles/job_profile.json", help="Path to job profile JSON")
    parser.add_argument("--min-score", type=int, default=50, help="Minimum score to apply (default: 50)")
    parser.add_argument("--dry-run",   action="store_true", help="Analyze only, no submission")
    parser.add_argument("--auto-submit", action="store_true", help="Auto-submit without confirmation")
    args = parser.parse_args()

    print("\n🚀 Job Bot — Phase 4: Auto-Apply Engine (100% Automation)")
    print("=" * 60)

    if args.dry_run:
        print("  ⚠️  DRY RUN — analyze only, no submission\n")
    if args.auto_submit:
        print("  🤖 AUTO-SUBMIT enabled — no confirmation prompts\n")

    jobs      = json.loads(Path(args.jobs).read_text())
    profile   = json.loads(Path(args.profile).read_text())
    qualified = [j for j in jobs if j.get("score", 0) >= args.min_score]
    memory    = profile.get("extra_answers", {})
    results   = []

    print(f"  ✅ {len(qualified)} jobs\n")

    for i, job in enumerate(qualified, 1):
        title   = job.get('title','')
        company = job.get('company','')
        score   = job.get('score', 0)
        url     = job.get('apply_url','')

        print(f"\n{'='*60}")
        print(f"  🎯 [{i}/{len(qualified)}] {title} @ {company} ({score}%)")
        print(f"{'='*60}")

        if not url:
            results.append({"job": title, "company": company, "status": "no_url"})
            continue

        session_id, connect_url = create_session()
        if not session_id:
            results.append({"job": title, "company": company, "status": "session_error"})
            continue

        try:
            status, new_answers = run_application(
                connect_url, job, profile, memory, 
                dry_run=args.dry_run, 
                auto_submit=args.auto_submit)
            memory.update(new_answers)
            results.append({"job": title, "company": company,
                            "status": status, "score": score})
            print(f"\n  ➡️  Result: {status}")
        finally:
            end_session(session_id)

    if memory:
        profile["extra_answers"] = memory
        Path(args.profile).write_text(json.dumps(profile, indent=2))
        print(f"\n  💾 Answers saved to profile")

    print(f"\n{'='*60}")
    print(f"✅ Done!\n")
    icons = {"submitted":"🎉","dry_run_ok":"✅","user_skipped":"⏭️",
             "login_required":"🔐","no_job_found":"🔍","error":"❌"}
    for r in results:
        icon = icons.get(r.get("status",""), "•")
        print(f"  {icon} {r['job']} @ {r['company']} → {r['status']}")

    Path("outputs/application_log.json").write_text(json.dumps(results, indent=2))
    print(f"\n  📸 open outputs/screenshots/")

if __name__ == "__main__":
    main()
