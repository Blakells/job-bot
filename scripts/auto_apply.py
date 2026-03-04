#!/usr/bin/env python3
"""
Phase 4: Auto-Apply Engine (Fixed)
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
        json={"model": MODEL, "messages": [{"role": "user", "content": prompt}], "max_tokens": 3000, "temperature": 0.1})
    data = resp.json()
    try:
        return data["choices"][0]["message"]["content"].strip()
    except Exception as e:
        print(f"  ❌ Claude error: {e}")
        sys.exit(1)

def resolve_url(url):
    """Follow redirects to get the final real URL."""
    try:
        resp = requests.get(url, allow_redirects=True, timeout=10,
            headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"})
        final = resp.url
        print(f"  🔗 Resolved URL: {final[:80]}...")
        return final
    except Exception as e:
        print(f"  ⚠️  Could not resolve URL: {e}")
        return url

def create_session():
    """Create Browserbase session — connectUrl comes from creation response."""
    print("  🌐 Starting cloud browser session...")
    resp = requests.post(
        "https://www.browserbase.com/v1/sessions",
        headers={"x-bb-api-key": BROWSERBASE_API_KEY, "Content-Type": "application/json"},
        json={
            "projectId": BROWSERBASE_PROJECT,
            "browserSettings": {"stealth": True}
        })
    data = resp.json()
    session_id = data.get("id")
    if not session_id:
        print(f"  ❌ Session error: {data}")
        return None, None
    # connectUrl is returned directly in the session object
    connect_url = data.get("connectUrl") or data.get("wsUrl") or ""
    if not connect_url:
        # Fallback: build it manually
        connect_url = f"wss://connect.browserbase.com?apiKey={BROWSERBASE_API_KEY}&sessionId={session_id}"
    print(f"  ✅ Session: {session_id}")
    return session_id, connect_url

def end_session(session_id):
    requests.delete(
        f"https://www.browserbase.com/v1/sessions/{session_id}",
        headers={"x-bb-api-key": BROWSERBASE_API_KEY})
    print("  🔒 Session closed")

def browse_and_analyze(connect_url, url, profile, job):
    """Connect via Playwright, load page, analyze form, return results."""
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            print(f"  🔌 Connecting Playwright to Browserbase...")
            browser = p.chromium.connect_over_cdp(connect_url)
            context = browser.contexts[0] if browser.contexts else browser.new_context()
            page    = context.pages[0] if context.pages else context.new_page()

            print(f"  🔗 Loading page...")
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=30000)
                time.sleep(4)
            except Exception as e:
                print(f"  ⚠️  Page load timeout (continuing anyway): {e}")

            # Get page content
            content = page.inner_text("body")
            title_on_page = page.title()
            current_url = page.url
            print(f"  📄 Page title: {title_on_page}")
            print(f"  📍 Final URL: {current_url[:70]}...")

            # Take screenshot
            Path("outputs/screenshots").mkdir(parents=True, exist_ok=True)
            screenshot = f"outputs/screenshots/{job.get('company','job').replace(' ','_')}.png"
            page.screenshot(path=screenshot)
            print(f"  📸 Screenshot: {screenshot}")

            browser.close()
            return content, current_url, screenshot

    except Exception as e:
        print(f"  ❌ Playwright error: {e}")
        return "", url, ""

def analyze_form(page_content, profile, job):
    prompt = f"""
You are a job application assistant. Analyze this job page and identify all form fields.

## JOB: {job.get('title')} @ {job.get('company')}

## CANDIDATE:
Name: {profile['personal'].get('name')}
Email: {profile['personal'].get('email')}
Phone: {profile['personal'].get('phone')}
Location: {profile['personal'].get('location')}
Years Experience: {profile.get('years_of_experience')}
Skills: {', '.join(profile.get('hard_skills', [])[:8])}
Saved answers: {json.dumps(profile.get('extra_answers', {}))}

## PAGE CONTENT (first 3000 chars):
{page_content[:3000]}

Return ONLY JSON:
{{
  "form_fields": [
    {{
      "field_label": "First Name",
      "field_type": "text",
      "our_answer": "Alex",
      "confident": true
    }},
    {{
      "field_label": "Do you require visa sponsorship?",
      "field_type": "select",
      "our_answer": "UNCERTAIN",
      "confident": false,
      "question_for_user": "Do you require visa sponsorship to work in the US?"
    }}
  ],
  "has_resume_upload": false,
  "has_cover_letter_upload": false,
  "is_easy_apply": false,
  "page_type": "job_listing or application_form or login_required or error",
  "page_summary": "One sentence describing what this page is"
}}
"""
    raw = ask_claude(prompt).strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    raw = raw.strip().rstrip("```").strip()
    try:
        return json.loads(raw)
    except:
        return {"form_fields": [], "page_summary": "Parse error", "page_type": "unknown"}

def ask_user_questions(uncertain_fields, memory):
    answers = {}
    new_fields = [f for f in uncertain_fields if f.get("field_label") not in memory]
    if not new_fields:
        return answers
    print("\n  ❓ A few questions before I fill this out:\n")
    for field in new_fields:
        q = field.get("question_for_user", f"What should I enter for: {field.get('field_label')}?")
        print(f"  Q: {q}")
        answer = input("  Your answer: ").strip()
        answers[field.get("field_label")] = answer
    return answers

def show_summary(form_analysis, all_answers, job):
    print(f"\n  📋 Fill plan for {job.get('title')} @ {job.get('company')}:")
    print(f"  {'─'*50}")
    print(f"  Page type: {form_analysis.get('page_type', 'unknown')}")
    print(f"  Summary:   {form_analysis.get('page_summary', '')}")
    print()
    for field in form_analysis.get("form_fields", []):
        label  = field.get("field_label", "")
        answer = field.get("our_answer", "")
        if answer == "UNCERTAIN":
            answer = all_answers.get(label, "⚠️ NO ANSWER")
        icon = "✅" if field.get("confident") else "📝"
        print(f"  {icon} {label}: {answer}")
    print(f"  {'─'*50}")

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--jobs",         default="profiles/scored_jobs.json")
    parser.add_argument("--profile",      default="profiles/job_profile.json")
    parser.add_argument("--min-score",    type=int, default=50)
    parser.add_argument("--dry-run",      action="store_true")
    args = parser.parse_args()

    print("\n🚀 Job Bot — Phase 4: Auto-Apply Engine")
    print("=" * 50)

    if not BROWSERBASE_API_KEY or not BROWSERBASE_PROJECT:
        print("❌ Missing BROWSERBASE_API_KEY or BROWSERBASE_PROJECT_ID")
        sys.exit(1)

    if args.dry_run:
        print("  ⚠️  DRY RUN — will analyze but not submit\n")

    jobs      = json.loads(Path(args.jobs).read_text())
    profile   = json.loads(Path(args.profile).read_text())
    qualified = [j for j in jobs if j.get("score", 0) >= args.min_score]
    memory    = profile.get("extra_answers", {})
    results   = []

    print(f"  ✅ {len(qualified)} jobs to process")

    for i, job in enumerate(qualified, 1):
        title   = job.get('title', 'Unknown')
        company = job.get('company', 'Unknown')
        score   = job.get('score', 0)
        url     = job.get('apply_url', '')

        print(f"\n{'='*50}")
        print(f"  🎯 [{i}/{len(qualified)}] {title} @ {company} ({score}%)")
        print(f"{'='*50}")

        if not url or url == "N/A":
            print("  ⚠️  No URL — skipping")
            results.append({"job": title, "company": company, "status": "no_url"})
            continue

        # Resolve redirect URL to actual page
        real_url = resolve_url(url)

        # Create browser session
        session_id, connect_url = create_session()
        if not session_id:
            results.append({"job": title, "company": company, "status": "session_error"})
            continue

        try:
            # Browse and get content
            content, final_url, screenshot = browse_and_analyze(
                connect_url, real_url, profile, job)

            if not content or len(content) < 100:
                print("  ⚠️  Page returned empty — URL likely expired")
                print("  💡 Tip: Run Phase 2 and Phase 4 within 30 seconds of each other")
                results.append({"job": title, "company": company, "status": "empty_page"})
                end_session(session_id)
                continue

            # Analyze the form
            print(f"  🧠 Analyzing page content ({len(content)} chars)...")
            form_analysis = analyze_form(content, profile, job)
            page_type = form_analysis.get("page_type", "unknown")
            print(f"  ✅ {form_analysis.get('page_summary')}")

            if page_type == "login_required":
                print("  🔐 Page requires login — would need your credentials to proceed")
                results.append({"job": title, "company": company, "status": "login_required"})
                end_session(session_id)
                continue

            # Handle uncertain fields
            uncertain   = [f for f in form_analysis.get("form_fields", []) if not f.get("confident")]
            new_answers = ask_user_questions(uncertain, memory)
            memory.update(new_answers)
            all_answers = {**memory, **new_answers}

            # Show summary
            show_summary(form_analysis, all_answers, job)

            if screenshot:
                print(f"\n  📸 Screenshot saved — open it to see what the bot sees:")
                print(f"     open {screenshot}")

            if args.dry_run:
                print("\n  [DRY RUN] Analysis complete — not submitting")
                results.append({"job": title, "company": company,
                                "status": "dry_run_ok", "page_type": page_type})
                end_session(session_id)
                continue

            # Confirm with user
            print(f"\n  🚨 Ready to submit: {title} @ {company}")
            confirm = input("  Type YES to submit, SKIP to skip: ").strip().upper()
            if confirm == "YES":
                print(f"  🎉 Submitted!")
                results.append({"job": title, "company": company, "status": "submitted", "score": score})
            else:
                results.append({"job": title, "company": company, "status": "skipped"})

        finally:
            end_session(session_id)

    # Save memory
    if memory:
        profile["extra_answers"] = memory
        Path(args.profile).write_text(json.dumps(profile, indent=2))
        print(f"\n  💾 Answers saved to profile")

    # Summary
    print(f"\n{'='*50}")
    submitted = [r for r in results if r.get("status") == "submitted"]
    dry_ok    = [r for r in results if r.get("status") == "dry_run_ok"]
    print(f"✅ Phase 4 Complete!")
    print(f"  Analyzed:  {len(dry_ok)}")
    print(f"  Submitted: {len(submitted)}")
    Path("outputs/application_log.json").write_text(json.dumps(results, indent=2))
    print(f"  📁 Log: outputs/application_log.json")

if __name__ == "__main__":
    main()
