#!/usr/bin/env python3
"""
Phase 3: Resume & Cover Letter Tailor
Takes scored jobs + your base resume and generates
a tailored resume + cover letter for each job
"""

import json, sys, argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from job_bot.ai import ask_claude
from job_bot.config import OPENROUTER_API_KEY

def tailor_resume(base_resume, job, profile):
    prompt = f"""
You are an expert resume writer and career coach.

Rewrite the candidate's resume to be specifically tailored for this job posting.
Keep all facts truthful — only reorder, reword, and emphasize relevant experience.

## TARGET JOB:
Title: {job.get('title')}
Company: {job.get('company')}
Location: {job.get('location')}
Key Requirements: {', '.join(job.get('key_requirements', []))}
Match Score: {job.get('score')}%
Score Reason: {job.get('score_reason')}

## CANDIDATE'S BASE RESUME:
{base_resume}

## INSTRUCTIONS:
1. Move the most relevant skills and experience to the top
2. Reword bullet points to mirror the job's language and keywords
3. Add a targeted professional summary at the top specific to this role and company
4. Keep all dates, titles, and companies EXACTLY the same (do not fabricate)
5. Format as clean plain text, ready to paste

Return ONLY the tailored resume text. No explanation.
"""
    return ask_claude(prompt)

def write_cover_letter(base_resume, job, profile):
    prompt = f"""
You are an expert cover letter writer.

Write a compelling, specific cover letter for this job application.
It must feel personal, not generic — reference the company and role specifically.

## TARGET JOB:
Title: {job.get('title')}
Company: {job.get('company')}
Location: {job.get('location')}
Key Requirements: {', '.join(job.get('key_requirements', []))}
Score Reason: {job.get('score_reason')}

## CANDIDATE PROFILE:
Name: {profile['personal'].get('name')}
Email: {profile['personal'].get('email')}
Phone: {profile['personal'].get('phone')}
Summary: {profile.get('summary')}
Top Skills: {', '.join(profile.get('hard_skills', [])[:8])}
Certifications: {', '.join(profile.get('certifications', []))}

## BASE RESUME (for context):
{base_resume[:2000]}

## INSTRUCTIONS:
1. Opening paragraph: show genuine excitement about THIS company and role specifically
2. Body paragraph 1: highlight 2-3 specific achievements most relevant to the job requirements
3. Body paragraph 2: explain why you are a great culture/mission fit for this company
4. Closing: confident call to action
5. Keep it under 400 words
6. Format as clean plain text

Return ONLY the cover letter text. No explanation.
"""
    return ask_claude(prompt)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--jobs",    default="profiles/scored_jobs.json")
    parser.add_argument("--resume",  default="resumes/my_resume.txt")
    parser.add_argument("--profile", default="profiles/job_profile.json")
    parser.add_argument("--min-score", type=int, default=50)
    parser.add_argument("--output",  default=None,
                        help="Output dir (default: profiles/{name}/tailored/)")
    args = parser.parse_args()

    print("\n🚀 Job Bot — Phase 3: Tailoring Resume & Cover Letters")
    print("=" * 55)

    if not OPENROUTER_API_KEY:
        print("!! OPENROUTER_API_KEY not set.")
        return

    # Load files
    jobs    = json.loads(Path(args.jobs).read_text())
    resume  = Path(args.resume).read_text()
    profile = json.loads(Path(args.profile).read_text())

    # Determine output directory: per-profile by default, --output as override
    if args.output:
        output_dir = Path(args.output)
    else:
        # Auto-detect from --profile path: profiles/alex/profile.json → profiles/alex/tailored/
        profile_dir = Path(args.profile).parent
        if profile_dir.name != "profiles" and (profile_dir / "profile.json").exists():
            output_dir = profile_dir / "tailored"
        else:
            # Fallback for legacy paths like profiles/job_profile.json
            output_dir = Path("outputs/tailored")
    print(f"  📁 Output: {output_dir}/")

    # Filter by score
    qualified = [j for j in jobs if j.get("score", 0) >= args.min_score]
    print(f"  ✅ {len(qualified)} jobs qualify (score >= {args.min_score}%)")

    output_dir.mkdir(parents=True, exist_ok=True)

    summary = []

    for i, job in enumerate(qualified, 1):
        title   = job.get('title', 'Unknown').replace('/', '-')
        company = job.get('company', 'Unknown').replace('/', '-')
        score   = job.get('score', 0)
        slug    = f"{i:02d}_{company}_{title}".replace(' ', '_')[:60]

        print(f"\n📝 [{i}/{len(qualified)}] Tailoring for: {title} @ {company} ({score}%)")

        # Tailor resume
        print(f"  ✏️  Rewriting resume...")
        tailored_resume = tailor_resume(resume, job, profile)
        resume_path = output_dir / f"{slug}_RESUME.txt"
        resume_path.write_text(tailored_resume)
        print(f"  ✅ Resume saved: {resume_path.name}")

        # Write cover letter
        print(f"  ✉️  Writing cover letter...")
        cover_letter = write_cover_letter(resume, job, profile)
        cover_path = output_dir / f"{slug}_COVER_LETTER.txt"
        cover_path.write_text(cover_letter)
        print(f"  ✅ Cover letter saved: {cover_path.name}")

        summary.append({
            "rank": i,
            "score": score,
            "title": job.get('title'),
            "company": job.get('company'),
            "location": job.get('location'),
            "salary": job.get('salary'),
            "apply_url": job.get('apply_url', 'N/A'),
            "resume_file": str(resume_path),
            "cover_letter_file": str(cover_path)
        })

    # Save summary index
    summary_path = output_dir / "00_APPLICATION_SUMMARY.json"
    summary_path.write_text(json.dumps(summary, indent=2))

    print(f"\n{'='*55}")
    print(f"✅ All done! {len(summary)} application packages created")
    print(f"📁 Files saved to: {output_dir}/")
    print(f"\n📋 Application Summary:")
    for app in summary:
        print(f"\n  #{app['rank']} [{app['score']}%] {app['title']} @ {app['company']}")
        print(f"  📍 {app['location']}  |  💰 {app['salary']}")
        print(f"  🔗 {app['apply_url']}")
    print(f"\n🎯 Next: Review your files in outputs/tailored/ then run Phase 4 to auto-apply!")

if __name__ == "__main__":
    main()
