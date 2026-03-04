#!/usr/bin/env python3
"""
Phase 2: Job Discovery & Scoring (Google Search version)
Searches Google for jobs, extracts direct company URLs
"""

import json, os, sys, argparse, re
from pathlib import Path
import requests

FIRECRAWL_KEY   = os.environ.get("FIRECRAWL_API_KEY", "")
OPENROUTER_KEY  = os.environ.get("OPENROUTER_API_KEY", "")
FIRECRAWL_BASE  = "https://api.firecrawl.dev/v1"
OPENROUTER_BASE = "https://openrouter.ai/api/v1/chat/completions"
MODEL           = "anthropic/claude-sonnet-4-5"

def ask_claude(prompt):
    resp = requests.post(OPENROUTER_BASE,
        headers={"Authorization": f"Bearer {OPENROUTER_KEY}", "Content-Type": "application/json"},
        json={"model": MODEL, "messages": [{"role": "user", "content": prompt}],
              "max_tokens": 3000, "temperature": 0.1})
    return resp.json()["choices"][0]["message"]["content"].strip()

def google_search_jobs(query, limit=5):
    """Use Firecrawl search to find jobs — returns direct URLs."""
    print(f"    🔍 Searching: {query}")
    resp = requests.post(f"{FIRECRAWL_BASE}/search",
        headers={"Authorization": f"Bearer {FIRECRAWL_KEY}", "Content-Type": "application/json"},
        json={"query": query, "limit": limit})
    data = resp.json()
    results = []
    for r in data.get("data", []):
        url = r.get("url", "")
        # Skip job boards — we want direct company pages
        skip = ["indeed.com", "linkedin.com", "glassdoor.com",
                "ziprecruiter.com", "monster.com", "careerbuilder.com",
                "simplyhired.com", "dice.com"]
        if any(s in url for s in skip):
            continue
        results.append({
            "title":   r.get("title", ""),
            "url":     url,
            "snippet": r.get("description", r.get("markdown", ""))[:500]
        })
    return results

def scrape_job_page(url):
    """Scrape the actual job page for details."""
    try:
        resp = requests.post(f"{FIRECRAWL_BASE}/scrape",
            headers={"Authorization": f"Bearer {FIRECRAWL_KEY}", "Content-Type": "application/json"},
            json={"url": url, "formats": ["markdown"], "onlyMainContent": True},
            timeout=30)
        data = resp.json()
        return data.get("data", {}).get("markdown", "")[:3000]
    except:
        return ""

def score_job(job_content, job_url, job_title_guess, profile):
    """Ask Claude to score this job against the profile."""
    prompt = f"""
Score this job for the candidate. Return ONLY JSON.

## CANDIDATE PROFILE:
Target roles: {profile.get('target_roles', [])}
Experience: {profile.get('years_of_experience')} years
Skills: {profile.get('hard_skills', [])}
Salary target: {profile.get('salary_range', {})}
Remote preference: {profile.get('remote_preference', '')}
Deal breakers: {profile.get('deal_breakers', [])}

## JOB PAGE CONTENT:
URL: {job_url}
{job_content[:2000]}

Return ONLY JSON:
{{
  "title": "exact job title",
  "company": "company name",
  "location": "job location",
  "salary": "salary if listed or Not Listed",
  "score": 75,
  "reasoning": "2-3 sentence explanation",
  "is_relevant": true,
  "apply_url": "{job_url}"
}}
"""
    raw = ask_claude(prompt).strip()
    if "```" in raw:
        raw = raw.split("```")[1].lstrip("json").strip().rstrip("```")
    try:
        result = json.loads(raw)
        # Always preserve the real URL
        result["apply_url"] = job_url
        return result
    except:
        return None

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile",   default="profiles/job_profile.json")
    parser.add_argument("--output",    default="profiles/scored_jobs.json")
    parser.add_argument("--min-score", type=int, default=50)
    parser.add_argument("--location",  default="remote")
    args = parser.parse_args()

    print("\n🔍 Job Bot — Phase 2: Job Discovery & Scoring")
    print("=" * 50)

    profile = json.loads(Path(args.profile).read_text())
    print(f"  ✅ Profile: {profile['personal'].get('name')}")

    target_roles = profile.get("target_roles", [])[:3]
    all_jobs = []
    seen_urls = set()

    print(f"\n  📡 Searching Google for direct job postings...\n")

    for role in target_roles:
        # Search Google for direct company postings
        queries = [
            f"{role} job remote US site:greenhouse.io OR site:lever.co OR site:workday.com 2025 2026",
            f"{role} remote US job opening apply -indeed -linkedin -glassdoor",
        ]
        for query in queries:
            results = google_search_jobs(query, limit=5)
            print(f"    Found {len(results)} direct URLs for: {role}")

            for r in results:
                url = r.get("url", "")
                if url in seen_urls or not url:
                    continue
                seen_urls.add(url)

                print(f"    📄 Scraping: {url[:60]}...")
                content = scrape_job_page(url)
                if not content or len(content) < 100:
                    print(f"    ⚠️  Empty page, skipping")
                    continue

                print(f"    🧠 Scoring...")
                job = score_job(content, url, r.get("title",""), profile)
                if job and job.get("is_relevant") and job.get("score", 0) >= args.min_score:
                    all_jobs.append(job)
                    print(f"    ✅ [{job.get('score')}%] {job.get('title')} @ {job.get('company')}")
                elif job:
                    print(f"    ⏭️  [{job.get('score',0)}%] Too low — skipping")

    # Sort by score
    all_jobs.sort(key=lambda x: x.get("score", 0), reverse=True)

    # Save
    Path(args.output).parent.mkdir(exist_ok=True)
    Path(args.output).write_text(json.dumps(all_jobs, indent=2))

    print(f"\n  ✅ Found {len(all_jobs)} qualifying jobs")
    print(f"\n  🏆 Top Jobs (score >= {args.min_score}%):")
    print(f"  {'─'*55}")
    for i, job in enumerate(all_jobs[:5], 1):
        print(f"\n  #{i} [{job.get('score')}%] {job.get('title')} @ {job.get('company')}")
        print(f"      {job.get('location')} | {job.get('salary')}")
        print(f"      URL: {job.get('apply_url','')[:60]}")
        print(f"      Why: {job.get('reasoning','')[:120]}")

    print(f"\n  📁 Saved to: {args.output}")
    print(f"\n  ➡️  Next: Run Phase 3 to tailor your resume!")

if __name__ == "__main__":
    main()
