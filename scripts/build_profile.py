#!/usr/bin/env python3
import json, os, sys, argparse
from pathlib import Path
import requests

FIRECRAWL_API_KEY  = os.environ.get("FIRECRAWL_API_KEY", "")
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")
FIRECRAWL_BASE     = "https://api.firecrawl.dev/v1"
OPENROUTER_BASE    = "https://openrouter.ai/api/v1/chat/completions"
MODEL              = "anthropic/claude-sonnet-4-5"

def scrape_url(url):
    print(f"  🔥 Scraping: {url}")
    resp = requests.post(f"{FIRECRAWL_BASE}/scrape",
        headers={"Authorization": f"Bearer {FIRECRAWL_API_KEY}"},
        json={"url": url, "formats": ["markdown"]})
    data = resp.json()
    if data.get("success"):
        return data["data"].get("markdown", "")
    print(f"  ⚠️  Firecrawl error: {data}")
    return ""

def read_resume(path):
    p = Path(path)
    if not p.exists():
        print(f"  ❌ Resume file not found: {path}")
        sys.exit(1)
    if p.suffix in [".txt", ".md"]:
        return p.read_text()
    try:
        from pdfminer.high_level import extract_text
        return extract_text(path)
    except ImportError:
        print("  ⚠️  Install pdfminer: pip3 install pdfminer.six")
        sys.exit(1)

def get_portfolio(portfolio_arg):
    if not portfolio_arg:
        return ""
    p = Path(portfolio_arg)
    if p.exists():
        print(f"  📂 Reading local portfolio file")
        return p.read_text()
    return scrape_url(portfolio_arg)

def ask_claude(prompt):
    resp = requests.post(OPENROUTER_BASE,
        headers={"Authorization": f"Bearer {OPENROUTER_API_KEY}", "Content-Type": "application/json"},
        json={"model": MODEL, "messages": [{"role": "user", "content": prompt}], "max_tokens": 4000, "temperature": 0.2})
    data = resp.json()
    try:
        return data["choices"][0]["message"]["content"]
    except (KeyError, IndexError):
        print(f"  ❌ Claude API error: {data}")
        sys.exit(1)

def build_job_profile(resume_text, linkedin_text, portfolio_text):
    prompt = f"""
You are a career coach and recruiter. Based on the following information about a job seeker,
create a comprehensive, structured Job Profile JSON.

## RESUME:
{resume_text[:3000]}

## LINKEDIN PROFILE:
{linkedin_text[:2000]}

## PORTFOLIO / WEBSITE:
{portfolio_text[:2000]}

Return ONLY a valid JSON object with this exact structure, no explanation, no backticks:

{{
  "personal": {{
    "name": "",
    "email": "",
    "phone": "",
    "location": "",
    "linkedin_url": "",
    "portfolio_url": "",
    "github_url": ""
  }},
  "target_roles": [],
  "experience_level": "",
  "years_of_experience": 0,
  "hard_skills": [],
  "soft_skills": [],
  "industries": [],
  "education": [],
  "certifications": [],
  "preferred_locations": [],
  "remote_preference": "",
  "salary_range": {{"min": 0, "max": 0, "currency": "USD"}},
  "keywords": [],
  "deal_breakers": [],
  "summary": ""
}}
"""
    print("  🤖 Asking Claude to build your job profile...")
    raw = ask_claude(prompt).strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    raw = raw.strip().rstrip("```").strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"  ⚠️  JSON parse error: {e}\n{raw[:500]}")
        sys.exit(1)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--resume",    required=True)
    parser.add_argument("--linkedin",  required=True)
    parser.add_argument("--portfolio", default="")
    parser.add_argument("--output",    default="profiles/job_profile.json")
    args = parser.parse_args()

    print("\n🚀 Job Bot — Phase 1: Building Your Job Profile")
    print("=" * 50)

    if not FIRECRAWL_API_KEY:
        print("❌ FIRECRAWL_API_KEY not set. Run: export FIRECRAWL_API_KEY=your_key")
        sys.exit(1)
    if not OPENROUTER_API_KEY:
        print("❌ OPENROUTER_API_KEY not set. Run: export OPENROUTER_API_KEY=your_key")
        sys.exit(1)

    print("\n📥 Step 1: Gathering your information...")
    resume_text    = read_resume(args.resume)
    linkedin_text  = scrape_url(args.linkedin)
    portfolio_text = get_portfolio(args.portfolio)

    print(f"  ✅ Resume:    {len(resume_text)} chars")
    print(f"  ✅ LinkedIn:  {len(linkedin_text)} chars")
    if portfolio_text:
        print(f"  ✅ Portfolio: {len(portfolio_text)} chars")

    print("\n🧠 Step 2: Analyzing and building your profile...")
    profile = build_job_profile(resume_text, linkedin_text, portfolio_text)

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(profile, indent=2))

    print(f"\n✅ Job Profile saved to: {output_path}")
    print(f"\n📋 Profile Summary:")
    print(f"  Name:         {profile['personal'].get('name', 'N/A')}")
    print(f"  Target Roles: {', '.join(profile.get('target_roles', []))}")
    print(f"  Experience:   {profile.get('experience_level')} ({profile.get('years_of_experience')} yrs)")
    print(f"  Top Skills:   {', '.join(profile.get('hard_skills', [])[:5])}")
    print(f"  Remote Pref:  {profile.get('remote_preference')}")
    print(f"\n🎯 Next: Run Phase 2 to start finding and scoring jobs!")

if __name__ == "__main__":
    main()
