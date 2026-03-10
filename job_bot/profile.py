"""Profile data management, answer mapping, and tailored file resolution."""

import json
import re
from pathlib import Path

from job_bot.config import STATE_MAP, STATE_MAP_REVERSE


def find_tailored_files(company, title, apply_url=None, profile_path=None):
    """
    Find tailored resume and cover letter for a job.

    Search strategy (in order):
    1. Per-profile tailored dir (profiles/{name}/tailored/) — APPLICATION_SUMMARY + filename
    2. Global tailored dir (outputs/tailored/) — APPLICATION_SUMMARY + filename
    3. Default resume from resumes/ directory
    """
    search_dirs = []
    if profile_path:
        profile_dir = Path(profile_path).parent
        per_profile_tailored = profile_dir / "tailored"
        if per_profile_tailored.exists():
            search_dirs.append(per_profile_tailored)
    search_dirs.append(Path("outputs/tailored"))

    resume = None
    cover_letter = None

    for tailored_dir in search_dirs:
        if not tailored_dir.exists():
            continue

        # Strategy 1 & 2: Use APPLICATION_SUMMARY.json
        summary_path = tailored_dir / "00_APPLICATION_SUMMARY.json"
        if summary_path.exists():
            try:
                summary = json.loads(summary_path.read_text())
                matched_entry = None

                # Match by URL
                if apply_url:
                    for entry in summary:
                        entry_url = entry.get("apply_url", "")
                        if entry_url and (
                            entry_url == apply_url
                            or entry_url in apply_url
                            or apply_url in entry_url
                        ):
                            matched_entry = entry
                            break

                # Match by company name
                if not matched_entry:
                    company_lower = company.lower().strip()
                    for entry in summary:
                        if entry.get("company", "").lower().strip() == company_lower:
                            matched_entry = entry
                            break
                    if not matched_entry:
                        for entry in summary:
                            entry_co = entry.get("company", "").lower().strip()
                            if company_lower in entry_co or entry_co in company_lower:
                                matched_entry = entry
                                break

                if matched_entry:
                    txt_resume = matched_entry.get("resume_file", "")
                    txt_cover = matched_entry.get("cover_letter_file", "")

                    for txt_path, label in [(txt_resume, "resume"), (txt_cover, "cover_letter")]:
                        if not txt_path:
                            continue
                        candidates = [txt_path, str(tailored_dir / Path(txt_path).name)]
                        pdf_candidates = [
                            txt_path.replace(".txt", ".pdf"),
                            str(tailored_dir / Path(txt_path.replace(".txt", ".pdf")).name),
                        ]
                        for pdf_path in pdf_candidates:
                            if Path(pdf_path).exists():
                                if label == "resume":
                                    resume = str(Path(pdf_path).absolute())
                                else:
                                    cover_letter = str(Path(pdf_path).absolute())
                                break
                        if (label == "resume" and resume) or (label == "cover_letter" and cover_letter):
                            continue
                        for txt_p in candidates:
                            if Path(txt_p).exists():
                                if label == "resume":
                                    resume = str(Path(txt_p).absolute())
                                else:
                                    cover_letter = str(Path(txt_p).absolute())
                                break

                    if resume:
                        print(f"  >> Resume: {Path(resume).name}")
                        if cover_letter:
                            print(f"  >> Cover:  {Path(cover_letter).name}")
                        return resume, cover_letter

            except Exception as e:
                print(f"  !! Error reading summary: {e}")

        # Strategy 3: Direct filename search
        company_norm = re.sub(r'[^a-zA-Z0-9]+', '_', company).strip('_').lower()

        for ext in ['.pdf', '.txt']:
            for file in sorted(tailored_dir.glob(f"*_RESUME{ext}"), reverse=True):
                filename = file.stem.lower()
                if company_norm in filename.replace('.', '_'):
                    resume = str(file.absolute())
                    cover_name = file.name.replace(f"_RESUME{ext}", f"_COVER_LETTER{ext}")
                    cover_file = file.parent / cover_name
                    if cover_file.exists():
                        cover_letter = str(cover_file.absolute())
                    print(f"  >> Resume: {file.name} (filename match)")
                    if cover_letter:
                        print(f"  >> Cover:  {Path(cover_letter).name}")
                    return resume, cover_letter

    # Strategy 4: Default resume
    default_candidates = [
        "resumes/my_resume.txt", "resumes/my_resume.pdf",
        "profiles/resume.pdf", "profiles/resume.txt",
    ]
    if profile_path:
        profile_dir = Path(profile_path).parent
        for ext in [".pdf", ".txt", ".docx"]:
            for f in profile_dir.glob(f"*Resume*{ext}"):
                default_candidates.insert(0, str(f))
            for f in profile_dir.glob(f"*resume*{ext}"):
                default_candidates.insert(0, str(f))

    for candidate in default_candidates:
        if Path(candidate).exists():
            resume = str(Path(candidate).absolute())
            print(f"  >> Resume: {candidate} (default)")
            return resume, None

    print(f"  !! No resume found for {company}")
    return None, None


def build_answer_map(profile, company):
    """
    Build a mapping of field labels/IDs -> answers from the user profile.
    Returns (answers_by_id, answers_by_label).
    """
    name_parts = profile["personal"]["name"].split(" ", 1)
    first_name = name_parts[0]
    last_name = name_parts[1] if len(name_parts) > 1 else ""
    location = profile["personal"].get("location", "")
    location_parts = [p.strip() for p in location.split(",")]
    city = location_parts[0] if location_parts else ""
    state_abbrev = location_parts[1].strip() if len(location_parts) > 1 else ""
    state_full = STATE_MAP.get(state_abbrev.lower(), state_abbrev)
    state_full = state_full.title() if state_full.islower() else state_full
    location_full = f"{city}, {state_full}, United States" if city else location
    zip_code = profile["personal"].get("zip_code", "")

    # Read EEOC values from profile (with sensible defaults)
    eeoc = profile.get("eeoc", {})
    gender = eeoc.get("gender", "Male")
    hispanic_ethnicity = eeoc.get("hispanic_ethnicity", "No")
    veteran_status = eeoc.get("veteran_status", "I am not a protected veteran")
    disability_status = eeoc.get("disability_status", "No, I don't have a disability")
    race = eeoc.get("race", "Decline to self-identify")

    answers_by_id = {
        # Standard fields (by ID)
        "first_name": first_name,
        "last_name": last_name,
        "email": profile["personal"]["email"],
        "phone": profile["personal"]["phone"],
        "firstname": first_name,
        "lastname": last_name,
        "fname": first_name,
        "lname": last_name,

        # React-Select dropdowns (by ID)
        "country": "United States",
        "candidate-location": location_full,

        # EEOC fields (by ID) — read from profile
        "gender": gender,
        "hispanic_ethnicity": hispanic_ethnicity,
        "veteran_status": veteran_status,
        "disability_status": disability_status,

        # File uploads (by ID)
        "resume": "RESUME_FILE",
        "cover_letter": "COVER_LETTER_FILE",
    }

    salary_str = str(profile.get("salary_range", {}).get("min", ""))
    linkedin_url = profile["personal"].get("linkedin_url", "")
    portfolio_url = profile["personal"].get("portfolio_url", "")
    github_url = profile["personal"].get("github_url", "")
    summary_text = profile.get("summary", "")
    years_exp = str(profile.get("years_of_experience", ""))
    work_history = profile.get("work_history", [])
    current_job = work_history[0] if work_history else {}

    answers_by_label = {
        # Name fields
        "first name": first_name,
        "last name": last_name,
        "full legal name": profile["personal"]["name"],
        "full name": profile["personal"]["name"],
        "preferred first name": first_name,
        "preferred name": first_name,
        "name of candidate": profile["personal"]["name"],
        "candidate name": profile["personal"]["name"],

        # Contact
        "email address": profile["personal"]["email"],
        "email": profile["personal"]["email"],
        "phone number": profile["personal"]["phone"],
        "phone": profile["personal"]["phone"],
        "mobile": profile["personal"]["phone"],
        "cell": profile["personal"]["phone"],

        # Work Authorization
        "legally authorized to work": "Yes",
        "work authorization": "Yes",
        "authorized to work in the united states": "Yes",
        "authorized to work in the u.s": "Yes",
        "eligible to work": "Yes",
        "right to work": "Yes",
        "require sponsorship": "No",
        "need sponsorship": "No",
        "visa status": "No",
        "visa sponsorship": "No",
        "immigration sponsorship": "No",
        "work permit": "Yes",
        "citizen or permanent resident": "Yes",
        "us citizen": "Yes",
        "u.s. citizen": "Yes",

        # Referral / Source
        "how did you hear": "LinkedIn",
        "hear about this": "LinkedIn",
        "hear about us": "LinkedIn",
        "referred by": "",
        "referral source": "LinkedIn",
        "source": "LinkedIn",
        "where did you find": "LinkedIn",

        # URLs & Online Presence
        "linkedin profile": linkedin_url,
        "linkedin url": linkedin_url,
        "linkedin": linkedin_url,
        "website": portfolio_url,
        "personal website": portfolio_url,
        "portfolio": portfolio_url,
        "portfolio url": portfolio_url,
        "github": github_url,
        "github url": github_url,
        "github profile": github_url,

        # Professional Info
        "years of experience": years_exp,
        "total experience": years_exp,
        "years in": years_exp,
        "experience level": profile.get("experience_level", ""),
        "current title": current_job.get("title", ""),
        "current job title": current_job.get("title", ""),
        "current position": current_job.get("title", ""),
        "current employer": current_job.get("company", ""),
        "current company": current_job.get("company", ""),
        "most recent employer": current_job.get("company", ""),
        "most recent company": current_job.get("company", ""),

        # Salary
        "salary": salary_str,
        "desired salary": salary_str,
        "salary expectation": salary_str,
        "salary requirement": salary_str,
        "expected salary": salary_str,
        "compensation": salary_str,
        "desired compensation": salary_str,
        "minimum salary": salary_str,
        "pay expectation": salary_str,

        # Location / Address — using profile values
        "city": city,
        "state": state_full,
        "state/province": state_full,
        "zip": zip_code,
        "zip code": zip_code,
        "postal code": zip_code,
        "postcode": zip_code,
        "country": "United States",
        "location": location_full,
        "address": location_full,
        "current location": location_full,
        "which state": state_full,
        "what state": state_full,
        "state do you": state_full,
        "state of residence": state_full,
        "where are you located": location_full,
        "where do you currently reside": location_full,
        "where are you based": location_full,

        # Schedule / Availability
        "commit to this schedule": "Yes",
        "can you commute": "Yes",
        "willing to relocate": "Yes",
        "open to relocation": "Yes",
        "able to work": "Yes",
        "available to start": "Immediately",
        "start date": "Immediately",
        "when can you start": "Immediately",
        "earliest start date": "Immediately",
        "notice period": "2 weeks",
        "available for": "Full-time",
        "desired employment type": "Full-time",
        "employment type": "Full-time",

        # Background / Compliance
        "background check": "Yes",
        "willing to undergo": "Yes",
        "drug test": "Yes",
        "drug screen": "Yes",
        "non-compete": "No",
        "non-disclosure": "Yes",
        "non compete agreement": "No",
        "security clearance": "No, but willing to obtain if required",
        "clearance level": "None",
        "do you currently hold": "No, but willing to obtain if required",
        "what level clearance": "None -- willing to obtain if required",

        # Summary / Bio
        "summary": summary_text,
        "professional summary": summary_text,
        "about yourself": summary_text,
        "tell us about yourself": summary_text,
        "brief description": summary_text,
        "introduction": summary_text,
        "cover letter": "COVER_LETTER_TEXT",
        "additional information": summary_text,
        "anything else": "",

        # EEOC / Demographics — read from profile
        "gender": gender,
        "race": race,
        "ethnicity": race,
        "hispanic": hispanic_ethnicity,
        "veteran": veteran_status,
        "disability": disability_status,
        "protected veteran": veteran_status,
        "sexual orientation": "Decline to self-identify",
        "pronouns": "Decline to self-identify",

        # Social referral
        "do you know anyone": "No",
        "know anyone who currently works": "No",
        "employee referral": "No",
    }

    # Merge saved extra answers from the profile
    for key, val in profile.get("extra_answers", {}).items():
        answers_by_label[key.lower()] = val

    return answers_by_id, answers_by_label


def resolve_answer(field, answers_by_id, answers_by_label):
    """Look up the answer for a given field, trying ID match first, then label."""
    field_id = field["id"]
    label = field["label"].lower()

    if field_id in answers_by_id:
        return answers_by_id[field_id]

    for keyword, answer in answers_by_label.items():
        if keyword in label:
            return answer

    return None


def prompt_for_answer(field):
    """Ask the user for an answer when the bot doesn't know what to fill."""
    label = field["label"]
    field_type = field["type"]
    required = field["required"]

    req_tag = " (REQUIRED)" if required else " (optional)"
    type_hint = ""
    if field_type == "react-select":
        type_hint = " [dropdown]"
    elif field_type == "text":
        type_hint = " [text field]"

    print(f"\n  ?? Unknown field: {label}{req_tag}{type_hint}")
    answer = input(f"     Your answer (or SKIP to leave blank): ").strip()

    if answer.upper() == "SKIP" or answer == "":
        return None
    return answer


def save_answer_to_profile(profile, profile_path, field_label, answer):
    """Save a new answer to the profile's extra_answers for future use."""
    if "extra_answers" not in profile:
        profile["extra_answers"] = {}

    key = field_label.strip()
    if len(key) > 80:
        key = key[:80]

    profile["extra_answers"][key] = answer

    try:
        Path(profile_path).write_text(json.dumps(profile, indent=2))
        print(f"     >> Saved to profile for future use")
    except Exception as e:
        print(f"     !! Could not save to profile: {e}")
