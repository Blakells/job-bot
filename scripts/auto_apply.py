#!/usr/bin/env python3
"""
Phase 4: Auto-Apply Engine (Multi-step navigation)
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
- Years experience: {profile.get('years_of_experience')}
- Skills: {', '.join(profile.get('hard_skills', [])[:10])}
- Education: {json.dumps(profile.get('education', []))}
- Saved answers: {json.dumps(profile.get('extra_answers', {}))}

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
      "selector": "input[name='firstName']"
    }},
    {{
      "label": "Require visa sponsorship?",
      "type": "select",
      "answer": "UNCERTAIN",
      "confident": false,
      "question": "Do you need visa sponsorship to work in the US?",
      "selector": ""
    }}
  ],
  "submit_button": "Submit Application"
}}
"""
    raw = ask_claude(prompt).strip()
    if "```" in raw:
        raw = raw.split("```")[1].lstrip("json").strip().rstrip("```")
    try:
        return json.loads(raw)
    except:
        return {"form_fields": [], "submit_button": "Submit"}

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

def run_application(connect_url, job, profile, memory, dry_run):
    title   = job.get("title", "")
    company = job.get("company", "")
    url     = job.get("apply_url", "")
    slug    = company.replace(" ", "_")
    all_answers = dict(memory)
    new_answers = {}

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
                        # Try exact text match first
                        link = page.get_by_text(job_title_on_page, exact=False).first
                        link.click(timeout=10000)
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

            # ── STEP 5: Application form ─────────────────────────────────
            if info["page_type"] in ["application_form", "individual_job_page"]:
                print(f"  📋 Analyzing form fields...")
                form = get_form_fields(page_text, profile, job)
                fields = form.get("form_fields", [])
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
                    print(f"  {icon} {f.get('label','')}: {str(ans)[:60]}")
                print(f"  {'─'*50}")

                if dry_run:
                    screenshot(page, f"{slug}_04_form_preview")
                    print(f"\n  [DRY RUN] Would fill {len(fields)} fields — not submitting")
                    browser.close()
                    return "dry_run_ok", new_answers

                # Fill fields
                print(f"\n  ✏️  Filling fields...")
                for f in fields:
                    label    = f.get("label", "")
                    answer   = f.get("answer", "")
                    selector = f.get("selector", "")
                    ftype    = f.get("type", "text")
                    if answer == "UNCERTAIN":
                        answer = all_answers.get(label, "")
                    if not answer:
                        continue
                    try:
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
                    except Exception as e:
                        print(f"    ⚠️  {label}: {e}")

                screenshot(page, f"{slug}_05_filled")
                print(f"\n  📸 Check filled form:")
                print(f"     open outputs/screenshots/{slug}_05_filled.png")

                confirm = input("\n  Type YES to submit, SKIP to skip: ").strip().upper()
                if confirm == "YES":
                    submit = form.get("submit_button", "Submit")
                    for pattern in [submit, "Submit Application", "Submit", "Apply"]:
                        try:
                            btn = page.get_by_role("button", name=pattern)
                            if btn.count() > 0:
                                btn.first.click()
                                time.sleep(3)
                                screenshot(page, f"{slug}_06_submitted")
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
            else:
                print(f"  ⚠️  Ended on unexpected page type: {info['page_type']}")
                screenshot(page, f"{slug}_unexpected")
                browser.close()
                return f"unexpected_{info['page_type']}", new_answers

    except Exception as e:
        print(f"  ❌ Error: {e}")
        import traceback; traceback.print_exc()
        return "error", new_answers

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--jobs",      default="profiles/scored_jobs.json")
    parser.add_argument("--profile",   default="profiles/job_profile.json")
    parser.add_argument("--min-score", type=int, default=50)
    parser.add_argument("--dry-run",   action="store_true")
    args = parser.parse_args()

    print("\n🚀 Job Bot — Phase 4: Auto-Apply Engine")
    print("=" * 50)

    if args.dry_run:
        print("  ⚠️  DRY RUN — analyze only, no submission\n")

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

        print(f"\n{'='*50}")
        print(f"  🎯 [{i}/{len(qualified)}] {title} @ {company} ({score}%)")
        print(f"{'='*50}")

        if not url:
            results.append({"job": title, "company": company, "status": "no_url"})
            continue

        session_id, connect_url = create_session()
        if not session_id:
            results.append({"job": title, "company": company, "status": "session_error"})
            continue

        try:
            status, new_answers = run_application(
                connect_url, job, profile, memory, dry_run=args.dry_run)
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

    print(f"\n{'='*50}")
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
