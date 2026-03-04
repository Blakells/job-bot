#!/usr/bin/env python3
"""
Phase 2: Job Discovery & Scoring
Searches Indeed for jobs matching your profile
Scores each job 0-100% and returns ranked results
"""

import json, os, sys, requests, argparse
from pathlib import Path
from datetime import datetime

FIRECRAWL_API_KEY  = os.environ.get("FIRECRAWL_API_KEY", "")
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")
FIRECRAWL_BASE     = "https://api.firecrawl.dev/v1"
OPENROUTER_BASE    = "https://openrouter.ai/api/v1/chat/completions"
MODEL              = "anthropic/claude-sonnet-4-5"

def search_jobs(query, location="remote", num_results=10):
    """Use Firecrawl to search Indeed for job listings."""
    print(f"  🔍 Searching Indeed: '{query}' in '{location}'")
    url = f"https://www.indeed.com/jobs?q={query.replace(' ', '+')}&l={location.replace(' ', '+')}&fromage=1&sort=date"
    resp = requests.post(f"{FIRECRAWL_BASE}/scrape",
        headers={"Authorization": f"Bearer {FIRECRAWL_API_KEY}"},
        json={"url": url, "formats": ["markdown"]})
    data = resp.json()
    if data.get("success"):
        return data["data"].get("markdown", "")
    print(f"  ⚠️  Search error: {data.get('error', 'Unknown')}")
    return ""

def score_jobs(profile, raw_listings, search_query):
    """Ask Claude to extract and score jobs from raw page content."""
    prompt = f"""
You are a job matching expert. Given a candidate's job profile and raw job listing content scraped from Indeed, extract individual job listings and score each one.

## CANDIDATE PROFILE:
{json.dumps(profile, indent=2)[:2000]}

## RAW JOB LISTINGS FROM INDEED:
{raw_listings[:4000]}

## INSTRUCTIONS:
1. Extract as many individual job listings as you can find in the raw content
2. Score each job 0-100 based on how well it matches the candidate profile
3. Consider: skills match, experience level match, role title match, industry fit

Return ONLY a JSON array, no explanation, no backticks:

[
  {{
    "title": "Job Title",
    "company": "Company Name",
    "location": "City, ST or Remote",
    "salary": "Range or Not Listed",
    "score": 85,
    "score_reason": "Strong match: 8/10 required skills align, experience level matches, remote role",
    "apply_url": "https://...",
    "key_requirements": ["req1", "req2", "req3"],
    "posted": "1 day ago"
  }}
]

If you cannot find any job listings in the content, return an empty array: []
"""
    resp = requests.post(OPENROUTER_BASE,
        headers={"Authorization": f"Bearer {OPENROUTER_API_KEY}", "Content-Type": "application/json"},
        json={"model": MODEL, "messages": [{"role": "user", "content": prompt}], "max_tokens": 4000, "temperature": 0.1})
    data = resp.json()
    try:
        raw = data["choices"][0]["message"]["content"].strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        raw = raw.strip().rstrip("```").strip()
        return json.loads(raw)
    except Exception as e:
        print(f"  ⚠️  Scoring error: {e}")
        return []

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile",   default="profiles/job_profile.json")
    parser.add_argument("--min-score", type=int, default=50)
    parser.add_argument("--limit",     type=int, default=10)
    parser.add_argument("--location",  default="remote")
    parser.add_argument("--output",    default="profiles/scored_jobs.json")
    args = parser.parse_args()

    print("\n🚀 Job Bot — Phase 2: Job Discovery & Scoring")
    print("=" * 50)

    if not FIRECRAWL_API_KEY or not OPENROUTER_API_KEY:
        print("❌ Missing API keys. Run the export commands first.")
        sys.exit(1)

    # Load profile
    profile_path = Path(args.profile)
    if not profile_path.exists():
        print(f"❌ Profile not found: {args.profile} — run Phase 1 first!")
        sys.exit(1)
    profile = json.loads(profile_path.read_text())
    print(f"  ✅ Loaded profile for: {profile['personal'].get('name')}")

    # Build search queries from target roles
    target_roles = profile.get("target_roles", ["cybersecurity analyst"])
    all_jobs = []

    print(f"\n📥 Step 1: Searching for jobs (last 24 hours)...")
    for role in target_roles[:3]:  # Limit to 3 searches to save credits
        raw = search_jobs(role, args.location)
        if raw:
            print(f"  🧠 Scoring results for: {role}")
            jobs = score_jobs(profile, raw, role)
            all_jobs.extend(jobs)
            print(f"  ✅ Found {len(jobs)} listings")

    if not all_jobs:
        print("\n⚠️  No jobs found. Indeed may be blocking. Trying backup search...")
        # Fallback: try with just the top skill
        top_skill = profile.get("hard_skills", ["cybersecurity"])[0]
        raw = search_jobs(f"{top_skill} security", args.location)
        all_jobs = score_jobs(profile, raw, top_skill) if raw else []

    # Deduplicate by title+company
    seen = set()
    unique_jobs = []
    for job in all_jobs:
        key = f"{job.get('title','')}-{job.get('company','')}"
        if key not in seen:
            seen.add(key)
            unique_jobs.append(job)

    # Filter by minimum score and sort
    qualified = [j for j in unique_jobs if j.get("score", 0) >= args.min_score]
    qualified.sort(key=lambda x: x.get("score", 0), reverse=True)
    top_jobs = qualified[:args.limit]

    # Save results
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(top_jobs, indent=2))

    print(f"\n✅ Results saved to: {args.output}")
    print(f"\n🎯 Top {len(top_jobs)} Jobs (score >= {args.min_score}%):")
    print("-" * 60)
    for i, job in enumerate(top_jobs, 1):
        print(f"\n  #{i} [{job.get('score')}%] {job.get('title')}")
        print(f"      {job.get('company')} — {job.get('location')}")
        print(f"      Salary: {job.get('salary', 'Not listed')}")
        print(f"      Why: {job.get('score_reason', '')}")
    print(f"\n🎯 Next: Run Phase 3 to tailor your resume for each job!")

if __name__ == "__main__":
    main()

def find_direct_apply_url(company, job_title, firecrawl_key):
    """Search for the direct company careers page URL."""
    search_query = f"{company} {job_title} careers site:{company.lower().replace(' ','')}.com"
    print(f"  🔍 Finding direct URL for {company}...")
    resp = requests.post(f"{FIRECRAWL_BASE}/search",
        headers={"Authorization": f"Bearer {firecrawl_key}"},
        json={"query": search_query, "limit": 3})
    data = resp.json()
    if data.get("success") and data.get("data"):
        for result in data["data"]:
            url = result.get("url", "")
            # Prefer direct company URLs over job boards
            if company.lower().replace(" ","") in url.lower() or "greenhouse" in url or "lever.co" in url or "workday" in url:
                return url
    return ""
