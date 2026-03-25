#!/usr/bin/env python3
"""
Job Bot - Auto-Apply Engine v5.0
Thin CLI wrapper around the job_bot package.

Usage:
  python3 scripts/auto_apply.py --url "https://..." --profile profiles/alex/profile.json
  python3 scripts/auto_apply.py --jobs profiles/alex/scored_jobs.json --profile profiles/alex/profile.json
  python3 scripts/auto_apply.py --jobs profiles/alex/scored_jobs.json --single 3 --dry-run
"""

import json
import logging
import sys
import argparse
from pathlib import Path

# Ensure job_bot package is importable when running from any directory
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from job_bot.profile import find_tailored_files
from job_bot.applier import run_application


def main():
    parser = argparse.ArgumentParser(description="Job Bot Auto-Apply v5.0")
    parser.add_argument("--jobs", default="profiles/scored_jobs.json")
    parser.add_argument("--profile", default="profiles/alex/profile.json")
    parser.add_argument("--min-score", type=int, default=50)
    parser.add_argument("--dry-run", action="store_true",
                        help="Analyze and fill-plan only, don't submit")
    parser.add_argument("--single", type=int, default=None,
                        help="Run only job at this number (1-based, matches dashboard #)")
    parser.add_argument("--url", type=str, default=None,
                        help="Apply to a single URL directly")
    parser.add_argument("--resume", type=str, default=None,
                        help="Path to resume file (PDF/DOCX)")
    parser.add_argument("--cover-letter", type=str, default=None,
                        help="Path to cover letter file (PDF/DOCX)")
    parser.add_argument("--verbose", action="store_true",
                        help="Enable DEBUG-level logging")
    args = parser.parse_args()

    # Configure logging
    log_level = logging.DEBUG if args.verbose else logging.INFO
    log_format = "%(asctime)s [%(name)s] %(levelname)s: %(message)s"
    log_handlers = [logging.StreamHandler()]

    # Also log to file for comparing dry runs vs live runs
    Path("outputs").mkdir(exist_ok=True)
    log_handlers.append(logging.FileHandler("outputs/run.log", mode="a"))

    logging.basicConfig(level=log_level, format=log_format, handlers=log_handlers)
    logger = logging.getLogger(__name__)

    print("\n>> Job Bot -- Auto-Apply Engine v5.0")
    print("=" * 60)
    print("  Browser: Local (Playwright)")
    if args.dry_run:
        print("  DRY RUN MODE -- will NOT submit\n")

    profile = json.loads(Path(args.profile).read_text())

    # Single URL mode
    if args.url:
        job_title = "Direct Application"
        job_company = "Unknown"
        scored_jobs_path = Path(args.jobs)
        if scored_jobs_path.exists():
            try:
                scored = json.loads(scored_jobs_path.read_text())
                for sj in scored:
                    sj_url = sj.get("apply_url", "")
                    if sj_url and (sj_url == args.url or sj_url in args.url or args.url in sj_url):
                        job_title = sj.get("title", job_title)
                        job_company = sj.get("company", job_company)
                        print(f"  >> Matched job: {job_title} @ {job_company}")
                        break
            except Exception:
                pass

        job = {
            "title": job_title,
            "company": job_company,
            "apply_url": args.url,
            "score": 100
        }

        resume_path = args.resume
        cover_letter_path = args.cover_letter

        if not resume_path:
            resume_path, cover_letter_path = find_tailored_files(
                job_company, job_title, apply_url=args.url, profile_path=args.profile
            )
        else:
            print(f"  >> Resume: {Path(resume_path).name} (CLI)")
            if cover_letter_path:
                print(f"  >> Cover:  {Path(cover_letter_path).name} (CLI)")

        if not resume_path:
            print(f"  !! No resume found -- use --resume flag or place files in outputs/tailored/")

        result = run_application(
            job, profile, args.profile, resume_path, cover_letter_path, args.dry_run
        )
        print(f"\n  >> Result: {result.status}")
        logger.info("Application result: %s", result.status)
        return

    # Batch mode
    jobs = json.loads(Path(args.jobs).read_text())
    qualified = [j for j in jobs if j.get("score", 0) >= args.min_score]

    if args.single is not None:
        idx = args.single - 1
        if 0 <= idx < len(qualified):
            qualified = [qualified[idx]]
        else:
            print(f"  !! Job #{args.single} out of range (1-{len(qualified)})")
            return

    results = []
    print(f"  >> {len(qualified)} jobs to process\n")

    for i, job in enumerate(qualified, 1):
        title = job.get('title', '')
        company = job.get('company', '')
        score = job.get('score', 0)
        url = job.get('apply_url', '')

        print(f"\n{'='*60}")
        print(f"  [{i}/{len(qualified)}] {title} @ {company} ({score}%)")
        print(f"{'='*60}")

        if not url:
            results.append({"job": title, "company": company, "status": "no_url"})
            continue

        resume_path, cover_letter_path = find_tailored_files(
            company, title, apply_url=url, profile_path=args.profile
        )
        if not resume_path:
            results.append({"job": title, "company": company, "status": "no_resume"})
            continue

        result = run_application(
            job, profile, args.profile, resume_path, cover_letter_path, args.dry_run
        )
        results.append({
            "job": title, "company": company, "status": result.status, "score": score
        })
        print(f"\n  >> Result: {result.status}")
        logger.info("Job %d/%d result: %s (%s @ %s)", i, len(qualified),
                     result.status, title, company)

    # Save results
    Path("outputs").mkdir(exist_ok=True)
    Path("outputs/application_log.json").write_text(json.dumps(results, indent=2))

    print(f"\n{'='*60}")
    print(f"Complete!\n")

    for r in results:
        print(f"  {r['company']} -> {r['status']}")

    print(f"\n  Screenshots: open outputs/screenshots/")


if __name__ == "__main__":
    main()
