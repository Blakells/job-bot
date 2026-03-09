#!/usr/bin/env python3
"""
Phase 2: Job Discovery & Scoring
Sources: Indeed RSS, LinkedIn (stealth), Google/ATS direct
All funnel into: title + company → Google → direct apply URL
"""

import json, os, sys, argparse, re, time
from pathlib import Path
from urllib.parse import quote_plus, urljoin
import requests

FIRECRAWL_KEY   = os.environ.get("FIRECRAWL_API_KEY", "")
OPENROUTER_KEY  = os.environ.get("OPENROUTER_API_KEY", "")
BROWSERBASE_KEY = os.environ.get("BROWSERBASE_API_KEY", "")
BROWSERBASE_PRJ = os.environ.get("BROWSERBASE_PROJECT_ID", "")
FIRECRAWL_BASE  = "https://api.firecrawl.dev/v1"
OPENROUTER_BASE = "https://openrouter.ai/api/v1/chat/completions"
MODEL           = "anthropic/claude-sonnet-4-5"

# ── Helpers ──────────────────────────────────────────────────────────────────

def ask_claude(prompt, max_tokens=2000):
    resp = requests.post(OPENROUTER_BASE,
        headers={"Authorization": f"Bearer {OPENROUTER_KEY}",
                 "Content-Type": "application/json"},
        json={"model": MODEL,
              "messages": [{"role": "user", "content": prompt}],
              "max_tokens": max_tokens, "temperature": 0.1})
    try:
        return resp.json()["choices"][0]["message"]["content"].strip()
    except Exception as e:
        print(f"    ❌ Claude error: {e}")
        return ""

def parse_json(raw):
    raw = raw.strip()
    if "```" in raw:
        raw = raw.split("```")[1].lstrip("json").strip().rstrip("```")
    try:
        return json.loads(raw)
    except:
        return None

def firecrawl_search(query, limit=5):
    """Firecrawl Google search — returns direct URLs."""
    try:
        resp = requests.post(f"{FIRECRAWL_BASE}/search",
            headers={"Authorization": f"Bearer {FIRECRAWL_KEY}",
                     "Content-Type": "application/json"},
            json={"query": query, "limit": limit}, timeout=30)
        return resp.json().get("data", [])
    except Exception as e:
        print(f"    ⚠️  Search error: {e}")
        return []

def firecrawl_scrape(url):
    """Scrape a URL and return markdown content."""
    try:
        resp = requests.post(f"{FIRECRAWL_BASE}/scrape",
            headers={"Authorization": f"Bearer {FIRECRAWL_KEY}",
                     "Content-Type": "application/json"},
            json={"url": url, "formats": ["markdown"],
                  "onlyMainContent": True}, timeout=30)
        return resp.json().get("data", {}).get("markdown", "")[:3000]
    except:
        return ""

# ── Source 1: Indeed via Browserbase stealth ─────────────────────────────────

def fetch_indeed_jobs(query, location="remote", limit=10):
    """
    Scrape Indeed using Browserbase stealth browser.
    Extracts title + company + snippet, then we find direct apply URLs.
    """
    if not BROWSERBASE_KEY or not BROWSERBASE_PRJ:
        print("    ⚠️  Skipping Indeed (no Browserbase keys)")
        return []

    print(f"    🔍 Indeed stealth: {query}")
    jobs = []

    try:
        resp = requests.post(
            "https://www.browserbase.com/v1/sessions",
            headers={"x-bb-api-key": BROWSERBASE_KEY,
                     "Content-Type": "application/json"},
            json={"projectId": BROWSERBASE_PRJ,
                  "browserSettings": {"stealth": True}})
        data = resp.json()
        session_id  = data.get("id")
        connect_url = data.get("connectUrl") or                       f"wss://connect.browserbase.com?apiKey={BROWSERBASE_KEY}&sessionId={session_id}"
        if not session_id:
            print("    ⚠️  Indeed: could not create session")
            return []

        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.connect_over_cdp(connect_url)
            ctx  = browser.contexts[0] if browser.contexts else browser.new_context()
            page = ctx.pages[0] if ctx.pages else ctx.new_page()

            encoded_q   = quote_plus(query)
            encoded_loc = quote_plus(location)
            url = (f"https://www.indeed.com/jobs?q={encoded_q}"
                   f"&l={encoded_loc}&sort=date&fromage=3")

            page.goto(url, wait_until="domcontentloaded", timeout=30000)
            time.sleep(4)

            # Take screenshot for debugging
            Path("outputs/screenshots").mkdir(parents=True, exist_ok=True)
            page.screenshot(path=f"outputs/screenshots/indeed_search_{query[:20].replace(' ','_')}.png")

            # Try multiple card selectors
            cards = page.query_selector_all("[data-testid='slider_item']")
            if not cards:
                cards = page.query_selector_all(".job_seen_beacon")
            if not cards:
                cards = page.query_selector_all(".resultContent")
            print(f"    Found {len(cards)} Indeed cards")

            for card in cards[:limit]:
                try:
                    title_el   = card.query_selector("h2 a span, [data-testid='jobTitle'] span, h2 span")
                    company_el = card.query_selector("[data-testid='company-name'], .companyName")
                    loc_el     = card.query_selector("[data-testid='text-location'], .companyLocation")
                    desc_el    = card.query_selector(".job-snippet, [data-testid='job-snippet']")
                    link_el    = card.query_selector("h2 a, a[data-testid='job-title-link']")

                    title   = title_el.inner_text().strip()   if title_el   else ""
                    company = company_el.inner_text().strip() if company_el else ""
                    loc     = loc_el.inner_text().strip()     if loc_el     else location
                    desc    = desc_el.inner_text().strip()    if desc_el    else ""
                    href    = link_el.get_attribute("href")   if link_el    else ""

                    if href and not href.startswith("http"):
                        href = f"https://www.indeed.com{href}"

                    if title and company:
                        jobs.append({
                            "title":       title,
                            "company":     company,
                            "location":    loc,
                            "description": desc,
                            "source_url":  href,
                            "source":      "indeed"
                        })
                except:
                    continue

            browser.close()

        requests.delete(
            f"https://www.browserbase.com/v1/sessions/{session_id}",
            headers={"x-bb-api-key": BROWSERBASE_KEY})

        print(f"    ✅ Indeed: {len(jobs)} listings")

    except Exception as e:
        print(f"    ⚠️  Indeed error: {e}")

    return jobs

# ── Source 2: LinkedIn via Browserbase stealth ────────────────────────────────

def fetch_linkedin_jobs(query, location="United States", limit=10):
    """
    Scrape LinkedIn public job search using Browserbase stealth browser.
    Only grabs title + company + location — no login needed.
    Skips Easy Apply jobs since those require LinkedIn auth.
    """
    if not BROWSERBASE_KEY or not BROWSERBASE_PRJ:
        print("    ⚠️  Skipping LinkedIn (no Browserbase keys)")
        return []

    print(f"    🔍 LinkedIn stealth: {query}")
    jobs = []

    try:
        # Create stealth session
        resp = requests.post(
            "https://www.browserbase.com/v1/sessions",
            headers={"x-bb-api-key": BROWSERBASE_KEY,
                     "Content-Type": "application/json"},
            json={"projectId": BROWSERBASE_PRJ,
                  "browserSettings": {"stealth": True}})
        data = resp.json()
        session_id  = data.get("id")
        connect_url = data.get("connectUrl") or \
                      f"wss://connect.browserbase.com?apiKey={BROWSERBASE_KEY}&sessionId={session_id}"

        if not session_id:
            print(f"    ⚠️  LinkedIn: could not create session")
            return []

        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.connect_over_cdp(connect_url)
            ctx  = browser.contexts[0] if browser.contexts else browser.new_context()
            page = ctx.pages[0] if ctx.pages else ctx.new_page()

            encoded_q   = quote_plus(query)
            encoded_loc = quote_plus(location)
            url = (f"https://www.linkedin.com/jobs/search/"
                   f"?keywords={encoded_q}&location={encoded_loc}"
                   f"&f_TPR=r604800&sortBy=DD")  # Last 7 days, sorted by date

            page.goto(url, wait_until="domcontentloaded", timeout=30000)
            time.sleep(4)

            # Extract job cards
            cards = page.query_selector_all(".job-search-card, .jobs-search__results-list li")
            print(f"    Found {len(cards)} LinkedIn cards")

            for card in cards[:limit]:
                try:
                    title_el   = card.query_selector("h3, .job-search-card__title")
                    company_el = card.query_selector("h4, .job-search-card__company-name")
                    loc_el     = card.query_selector(".job-search-card__location")
                    link_el    = card.query_selector("a")

                    title   = title_el.inner_text().strip()   if title_el   else ""
                    company = company_el.inner_text().strip() if company_el else ""
                    loc     = loc_el.inner_text().strip()     if loc_el     else ""
                    li_url  = link_el.get_attribute("href")   if link_el    else ""

                    # Skip Easy Apply (requires LinkedIn login)
                    easy_apply = card.query_selector(".job-search-card__easy-apply-label, .easy-apply-label")
                    if easy_apply:
                        print(f"    ⏭️  Skipping Easy Apply: {title}")
                        continue

                    if title and company:
                        jobs.append({
                            "title":      title,
                            "company":    company,
                            "location":   loc,
                            "source_url": li_url,
                            "source":     "linkedin"
                        })
                except:
                    continue

            browser.close()

        # Clean up session
        requests.delete(
            f"https://www.browserbase.com/v1/sessions/{session_id}",
            headers={"x-bb-api-key": BROWSERBASE_KEY})

        print(f"    ✅ LinkedIn: {len(jobs)} non-Easy-Apply listings")

    except Exception as e:
        print(f"    ⚠️  LinkedIn error: {e}")

    return jobs

# ── Source 3: Google → ATS direct ────────────────────────────────────────────

def fetch_ats_direct(query, limit=5):
    """Search Google for direct Greenhouse/Lever/Workday job postings."""
    print(f"    🔎 ATS direct: {query}")
    results = firecrawl_search(
        f"{query} site:greenhouse.io OR site:lever.co OR site:workday.com"
        f" OR site:icims.com OR site:smartrecruiters.com remote 2026",
        limit=limit)
    jobs = []
    skip = ["indeed.com", "linkedin.com", "glassdoor.com",
            "ziprecruiter.com", "monster.com"]
    for r in results:
        url = r.get("url", "")
        if any(s in url for s in skip):
            continue
        jobs.append({
            "title":      r.get("title", ""),
            "company":    "",
            "location":   "Remote",
            "source_url": url,
            "description": r.get("description", "")[:300],
            "source":     "ats_direct"
        })
    print(f"    ✅ ATS direct: {len(jobs)} listings")
    return jobs

# ── Find direct apply URL ─────────────────────────────────────────────────────

def find_direct_url(title, company, existing_url=""):
    """
    Given a job title + company, find the direct application URL.
    Strategy:
      1. If URL is already a direct ATS link, use it
      2. Otherwise search Google for company + job title + apply
    """
    # Already a direct ATS URL?
    ats_domains = ["greenhouse.io", "lever.co", "workday.com",
                   "icims.com", "smartrecruiters.com", "taleo.net",
                   "myworkdayjobs.com", "applytojob.com"]
    if existing_url and any(d in existing_url for d in ats_domains):
        return existing_url

    # Search Google for direct URL
    query = f'"{company}" "{title}" apply job -linkedin -indeed -glassdoor'
    results = firecrawl_search(query, limit=3)
    for r in results:
        url = r.get("url", "")
        if any(d in url for d in ats_domains):
            return url
        # Company careers page is also fine
        company_slug = company.lower().replace(" ", "").replace(",","").replace(".","")
        if company_slug[:8] in url.lower() and "career" in url.lower():
            return url

    # Last resort: return original URL
    return existing_url

# ── Score a job ───────────────────────────────────────────────────────────────

def score_job(title, company, location, description, apply_url, profile):
    """Ask Claude to score this job against the profile."""
    prompt = f"""
Score this job for the candidate. Return ONLY JSON.

## CANDIDATE:
Target roles: {profile.get('target_roles', [])}
Experience: {profile.get('years_of_experience')} years
Skills: {profile.get('hard_skills', [])}
Remote preference: {profile.get('remote_preference', '')}
Deal breakers: {profile.get('deal_breakers', [])}
Salary target: {profile.get('salary_range', {})}

## JOB:
Title: {title}
Company: {company}
Location: {location}
Description: {description[:1500]}
Apply URL: {apply_url}

Return ONLY JSON:
{{
  "title": "exact job title",
  "company": "company name",
  "location": "{location}",
  "salary": "salary if mentioned or Not Listed",
  "score": 75,
  "reasoning": "2-3 sentences",
  "is_relevant": true,
  "apply_url": "{apply_url}"
}}
"""
    raw = ask_claude(prompt)
    result = parse_json(raw)
    if result:
        result["apply_url"] = apply_url  # Always preserve real URL
        result["source"]    = ""
    return result

# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile",   default="profiles/job_profile.json")
    parser.add_argument("--output",    default="profiles/scored_jobs.json")
    parser.add_argument("--min-score", type=int, default=50)
    parser.add_argument("--location",  default="remote")
    parser.add_argument("--sources",   default="ats,linkedin",
        help="Comma-separated: rss, linkedin, ats (default: rss,ats)")
    args = parser.parse_args()

    print("\n🔍 Job Bot — Phase 2: Job Discovery & Scoring")
    print("=" * 55)

    profile = json.loads(Path(args.profile).read_text())
    print(f"  ✅ Profile: {profile['personal'].get('name')}")

    sources      = [s.strip() for s in args.sources.split(",")]
    target_roles = profile.get("target_roles", [])[:3]
    raw_listings = []

    print(f"\n  📡 Fetching from sources: {', '.join(sources)}\n")

    for role in target_roles:
        print(f"  🎯 Role: {role}")

        if "rss" in sources:
            raw_listings += fetch_indeed_jobs(role, args.location)

        if "linkedin" in sources:
            raw_listings += fetch_linkedin_jobs(role, "United States")

        if "ats" in sources:
            raw_listings += fetch_ats_direct(role)

        print()

    # Deduplicate by title+company
    seen = set()
    unique = []
    for job in raw_listings:
        key = f"{job.get('title','').lower().strip()}|{job.get('company','').lower().strip()}"
        if key not in seen and job.get("title"):
            seen.add(key)
            unique.append(job)

    print(f"  📋 {len(unique)} unique listings found across all sources\n")
    print(f"  🔗 Finding direct apply URLs + scoring...\n")

    scored = []
    for i, job in enumerate(unique, 1):
        title   = job.get("title", "")
        company = job.get("company", "")
        loc     = job.get("location", args.location)
        desc    = job.get("description", "")
        src_url = job.get("source_url", "")
        source  = job.get("source", "")

        print(f"  [{i}/{len(unique)}] {title} @ {company or 'Unknown'}")

        # For RSS/LinkedIn, scrape description if we only have a snippet
        if source in ["indeed_rss", "linkedin"] and len(desc) < 200:
            print(f"    🔍 Finding direct URL...")
            direct_url = find_direct_url(title, company, src_url)
            if direct_url and direct_url != src_url:
                print(f"    ✅ Direct URL: {direct_url[:60]}...")
                print(f"    📄 Scraping job details...")
                desc = firecrawl_scrape(direct_url) or desc
                apply_url = direct_url
            else:
                apply_url = src_url
        else:
            apply_url = src_url

        # Score the job
        result = score_job(title, company, loc, desc, apply_url, profile)
        if not result:
            print(f"    ⚠️  Could not score, skipping")
            continue

        result["source"] = source
        score = result.get("score", 0)

        if result.get("is_relevant") and score >= args.min_score:
            scored.append(result)
            print(f"    ✅ [{score}%] {result.get('title')} @ {result.get('company')}")
        else:
            print(f"    ⏭️  [{score}%] Too low or not relevant")

    # Sort by score
    scored.sort(key=lambda x: x.get("score", 0), reverse=True)

    # Save
    Path(args.output).parent.mkdir(exist_ok=True)
    existing = []
    if Path(args.output).exists():
        try:
            existing = json.loads(Path(args.output).read_text())
        except:
            pass

    # Merge with existing, avoiding duplicates
    existing_keys = {f"{j.get('title','').lower()}|{j.get('company','').lower()}"
                     for j in existing}
    new_jobs = [j for j in scored
                if f"{j.get('title','').lower()}|{j.get('company','').lower()}"
                not in existing_keys]
    all_jobs = sorted(existing + new_jobs,
                      key=lambda x: x.get("score", 0), reverse=True)

    # Add status field for dashboard
    for job in all_jobs:
        if "status" not in job:
            job["status"] = "found"
        if "date_found" not in job:
            from datetime import date
            job["date_found"] = str(date.today())

    Path(args.output).write_text(json.dumps(all_jobs, indent=2))

    print(f"\n{'='*55}")
    print(f"  ✅ {len(new_jobs)} new jobs added | {len(all_jobs)} total")
    print(f"\n  🏆 Top Jobs (score >= {args.min_score}%):")
    print(f"  {'─'*55}")
    for i, job in enumerate(all_jobs[:5], 1):
        print(f"\n  #{i} [{job.get('score')}%] {job.get('title')} @ {job.get('company')}")
        print(f"      {job.get('location')} | {job.get('salary','Not Listed')}")
        print(f"      Source: {job.get('source','')}")
        print(f"      URL: {job.get('apply_url','')[:65]}")
        print(f"      {job.get('reasoning','')[:100]}")

    print(f"\n  📁 Saved: {args.output}")
    print(f"  ➡️  Next: python3 scripts/tailor_resume.py")

if __name__ == "__main__":
    main()
