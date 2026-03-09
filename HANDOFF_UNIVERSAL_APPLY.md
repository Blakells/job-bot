# Job Bot — Handoff Document for Next Session
## Written: March 5, 2026

---

## WHO IS THE USER

Blake. Mac Mini (macOS). Located in Florence, South Carolina. Building a job application bot as a cybersecurity portfolio project for himself and his wife Hannah. Has mock profiles using the name "Alex J. Carter".

---

## WHAT WAS ACCOMPLISHED THIS SESSION

### Major Features Built

1. **Multi-User Profile Builder v2** (`scripts/build_profile_v2.py`)
   - Interactive startup menu: "New person or existing?"
   - Reads resume (.txt, .pdf, .docx), cover letter, HTML portfolio
   - Claude extracts skills, roles, experience from documents
   - Suggests 3 adjacent roles: "Would you also like to search for these?"
   - Interactive Q&A: remote pref, locations, salary (supports "85k" shorthand), deal breakers
   - Pre-fills common application answers (learn-as-you-go)
   - Saves to `profiles/{name}/profile.json`
   - Validates required docs: "You said yes, but we can't find your Cover Letter"

2. **LinkedIn Job Scraper** (`scripts/find_jobs.py`)
   - Uses Scrapling 0.4.1 `StealthySession` for stealth browsing
   - Logs into LinkedIn (user handles login/2FA manually, presses Enter)
   - Searches all target roles from profile with time/location filters
   - Extracts job cards from logged-in LinkedIn (`.scaffold-layout__list-item`)
   - Pulls title from `<strong>`, company/location from `<span>` elements
   - Detail pages: title+company parsed from `<title>` tag (bulletproof)
   - Description collected from elements after "About the job" heading
   - Claude scores each job (0-100) against the profile
   - Configurable score threshold: "Minimum score to save?"
   - Deduplicates by LinkedIn job ID (not full URL — handles tracking params)
   - Easy Apply jobs marked as `status: "manual_apply"`
   - Merges into `profiles/{name}/scored_jobs.json`

3. **Universal Form Filler** (added to `scripts/auto_apply_v4.py`)
   - JavaScript injection extracts ALL form fields from any page
   - Auto-maps common fields (name, email, phone, LinkedIn, work auth) — no AI needed
   - Claude maps remaining fields via structured prompt
   - Generic Playwright fill: text, select, checkbox, file upload
   - Cookie banner auto-dismisser (handles "Accept all", "OK", "Got it", etc.)
   - Auto-clicks Apply button before prompting user
   - Manual fallback: user navigates to form, bot fills it
   - Cookie/session saving per ATS platform (login once, reuse for all jobs on same ATS)

4. **Local Browser Mode** (updated `scripts/auto_apply_v4.py`)
   - Default is now `--local` — launches Chromium locally, no Browserbase needed
   - `--cloud` flag still available if Browserbase is preferred
   - Eliminates the Browserbase subscription cost

5. **Multi-User Dashboard v2** (`scripts/dashboard.py` + `scripts/dashboard_template.html`)
   - Profile selector dropdown in header (switch between Alex, Hannah, etc.)
   - "Easy Apply" filter button for LinkedIn Easy Apply jobs
   - "Strong Match" stat card (score >= 70%)
   - Column sorting (click any header)
   - Profile bar shows name + target roles as tags
   - Auto-saves per profile (status changes, notes)
   - Reads from `profiles/{name}/scored_jobs.json`

### Infrastructure Changes

- **Python 3.13** installed via Homebrew (`/opt/homebrew/bin/python3.13`)
  - Required for Scrapling 0.4.1 (needs Python 3.10+)
  - Old Python 3.9 still used for other scripts (they work fine on 3.9)
  - `find_jobs.py` must be run with `python3.13`
  - All other scripts can use `python3`
- **Scrapling 0.4.1** installed with fetchers: `python3.13 -m pip install "scrapling[fetchers]"`
- **API keys** saved in `~/.zshrc`:
  - `OPENROUTER_API_KEY` — for Claude API (scoring + tailoring)
  - `BROWSERBASE_API_KEY` — optional, only for `--cloud` mode
  - `BROWSERBASE_PROJECT_ID` — optional, only for `--cloud` mode

---

## CURRENT STATE OF ALL SCRIPTS

| Script | Status | Run With | Purpose |
|--------|--------|----------|---------|
| `build_profile_v2.py` | ✅ DONE | `python3` | Multi-user profile builder |
| `find_jobs.py` | ✅ DONE | `python3.13` | LinkedIn job scraper + scorer |
| `tailor_resume.py` | ✅ DONE | `python3` | Tailors resume + cover letter per job |
| `convert_to_pdf.py` | ✅ DONE | `python3` | Converts .txt → .pdf |
| `auto_apply_v4.py` | ✅ DONE | `python3` | Auto-fills application forms |
| `dashboard.py` | ✅ DONE | `python3` | Web dashboard at localhost:5050 |
| `score_jobs.py` | 🔴 LEGACY | — | Old scraper, replaced by find_jobs.py |
| `build_profile.py` | 🔴 LEGACY | — | Old profile builder, replaced by v2 |

### Full Pipeline Command Sequence

```bash
# Step 1: Build profile (drop docs in profiles/alex/ first)
python3 scripts/build_profile_v2.py --name alex

# Step 2: Find and score jobs on LinkedIn
python3.13 scripts/find_jobs.py --profile profiles/alex/profile.json --max-pages 2 --max-detail 20

# Step 3: Tailor resumes for high-scoring jobs
python3 scripts/tailor_resume.py --jobs profiles/alex/scored_jobs.json --resume profiles/alex/Alex_Carter_Resume_2.txt --profile profiles/alex/profile.json --min-score 70

# Step 4: Convert to PDF
python3 scripts/convert_to_pdf.py

# Step 5: Auto-apply (dry run first)
python3 scripts/auto_apply_v4.py --jobs profiles/alex/scored_jobs.json --profile profiles/alex/profile.json --dry-run

# Step 5b: Auto-apply for real (remove --dry-run)
python3 scripts/auto_apply_v4.py --jobs profiles/alex/scored_jobs.json --profile profiles/alex/profile.json

# Dashboard: view everything
python3 scripts/dashboard.py
```

---

## DIRECTORY STRUCTURE

```
job-bot/
├── profiles/
│   ├── alex/
│   │   ├── Alex_Carter_Resume_2.txt      # Base resume
│   │   ├── Alex_Carter_CoverLetter.docx  # Base cover letter
│   │   ├── Alex_Carter_Portfolio_1.html   # HTML portfolio
│   │   ├── profile.json                  # Generated by build_profile_v2
│   │   └── scored_jobs.json              # 38 scored jobs (27 old + 11 from LinkedIn)
│   ├── .browser_sessions/                # Saved ATS login cookies
│   │   └── icims_session.json            # (created on first iCIMS login)
│   ├── job_profile.json                  # OLD - legacy location
│   └── scored_jobs.json                  # OLD - legacy location (27 jobs)
├── scripts/
│   ├── build_profile_v2.py               # ✅ Multi-user profile builder
│   ├── find_jobs.py                      # ✅ LinkedIn scraper (Scrapling)
│   ├── tailor_resume.py                  # ✅ Resume/cover letter tailoring
│   ├── convert_to_pdf.py                 # ✅ TXT → PDF converter
│   ├── auto_apply_v4.py                  # ✅ Universal form filler + Greenhouse
│   ├── dashboard.py                      # ✅ Flask dashboard backend
│   ├── dashboard_template.html           # ✅ Dashboard frontend
│   ├── score_jobs.py                     # 🔴 Legacy (replaced by find_jobs.py)
│   └── build_profile.py                  # 🔴 Legacy (replaced by v2)
├── outputs/
│   ├── tailored/                         # 60+ tailored resume/cover letter pairs
│   │   ├── 00_APPLICATION_SUMMARY.json   # Maps apply_url → file paths
│   │   ├── 01_..._RESUME.txt + .pdf
│   │   ├── 01_..._COVER_LETTER.txt + .pdf
│   │   └── ...
│   ├── screenshots/                      # Auto-apply screenshots
│   └── application_log.json              # Application results log
├── resumes/
│   └── my_resume.txt                     # OLD location — use profiles/alex/ instead
└── [many legacy test/debug files]
```

---

## THE PROFILE (`profiles/alex/profile.json`)

- Name: Alex Carter
- 8 target roles: Cybersecurity Analyst, Penetration Tester, Security Engineer, Red Team Specialist, SOC Analyst, Threat Hunter, Security Operations Engineer, Application Security Analyst
- 95 hard skills (extracted from resume + portfolio)
- Location: Florence, SC | Willing to work: Remote, Florida, South Carolina
- Remote preference: Open to all
- Salary: $85,000+ minimum
- Certifications: Security+, CEH, AWS Security Specialty, CySA+ (in progress)
- 3 pre-filled application answers saved

---

## SCORED JOBS (`profiles/alex/scored_jobs.json`)

Blake's local version has 38 jobs (the zip uploaded mid-session had 27):
- Sources: ats_direct (12), linkedin (9+), unknown (6)
- Score range: 62-95%
- Average score: ~76%
- All status: "found" (none applied yet in real mode)
- 30 tailored resume/cover letter pairs generated

---

## KNOWN BUGS & ISSUES TO FIX NEXT SESSION

### Universal Form Filler Issues

1. **Only filled 9/14 fields on Workable (ProSync)**
   - 2 fields had blank labels → skipped (need better label extraction for unlabeled fields)
   - 1 file field skipped (couldn't detect if it was resume or cover letter)
   - "Summary" was skipped — should be filled with profile summary
   - Cover letter was mapped to textarea but might need to be pasted as text, not uploaded
   - Location field unclear: may have put "Florence, SC" when form wanted city/state/country separately

2. **Required fields not prompting user**
   - "If so, what level clearance do you currently..." showed "❓ will ask" in dry run
   - In live mode, this SHOULD prompt the user — verify it actually does
   - Answer should be saved to `extra_answers` for future use

3. **Field label extraction incomplete**
   - Some fields show blank labels in the fill plan
   - The JS extractor should also check `aria-describedby`, nearby `<span>` elements, and form group headers

4. **Location handling**
   - Address fields sometimes want just city, sometimes city+state, sometimes full address
   - Need to detect whether it's a single field or multi-field (city/state/zip separately)
   - Claude mapping sometimes puts "Florence, SC" in a field that wants "United States"

### LinkedIn Scraper Issues

5. **Logged-in search returns ~8 jobs per page (not 25)**
   - StealthySession with login seems to get fewer results than expected
   - May need to scroll/load more results on each page
   - The first run (before selectors were fixed) got more jobs — investigate why

6. **Some jobs from LinkedIn have no external apply URL**
   - Detail page extraction doesn't always find the external link
   - Jobs default to LinkedIn URL as apply_url, which auto_apply can't fill
   - Need to handle LinkedIn "Apply" button → redirect to company site

### Dashboard Issues

7. **Route parameter naming** was fragile
   - Had to manually fix `<n>` vs `name` mismatch with a Python one-liner
   - If Blake re-downloads dashboard.py, make sure routes use `<name>` consistently

### Pipeline Issues

8. **`--single` flag uses 0-indexed but confusing**
   - Blake thought `--single 21` would get job #21 but it's actually 0-indexed
   - Should either switch to 1-indexed or use `--url` instead

9. **tailor_resume.py outputs to `outputs/tailored/` (global)**
   - Should be per-profile: `profiles/alex/tailored/`
   - Currently all users' tailored files would mix together

---

## WHAT TO BUILD NEXT SESSION

### Priority 1: Fix Universal Form Filler
- Improve field label extraction (handle blank labels)
- Detect separate city/state/zip vs combined address
- Fill "Summary" with profile summary
- Handle cover letter as text (textarea) vs file upload
- Test on more sites: try Robert Half, Netflix, Meta, Paylocity

### Priority 2: Hannah's Profile
- Test the multi-user flow end to end
- She's a Senior Technical Writer — completely different role/skills
- Verify the profile builder works for a non-cybersecurity person
- Run find_jobs.py with her profile
- Verify dashboard shows both profiles

### Priority 3: Cron Job
- Set up daily 9 AM run of find_jobs.py
- Needs to handle LinkedIn login somehow (saved cookies? headless with stored session?)
- `crontab -e` → add the line
- Log output to `logs/daily_scrape.log`

### Priority 4: Move tailor_resume.py to per-profile output
- Output to `profiles/{name}/tailored/` instead of global `outputs/tailored/`
- Update auto_apply_v4.py to look there too

### Priority 5: iCIMS Support
- Cookie session saving is built but untested
- Need Blake to create an iCIMS account on one site (e.g., Teksynap)
- Test that cookies persist and work for Docusign, Amyx, Peraton

---

## TECH STACK (CURRENT)

| Component | Tool | Notes |
|-----------|------|-------|
| Profile builder | Python + Claude API | Interactive terminal script |
| Job scraping | Scrapling 0.4.1 (StealthySession) | Requires Python 3.13 |
| Job scoring | Claude via OpenRouter | ~$0.01 per job scored |
| Resume tailoring | Claude via OpenRouter | ~$0.03 per job (2 calls) |
| Form automation (Greenhouse) | Playwright (local) | Deterministic DOM parser, no AI |
| Form automation (universal) | Playwright + Claude | AI maps unknown fields |
| Browser | Local Chromium (default) | Browserbase optional with `--cloud` |
| Dashboard | Flask + vanilla JS | Port 5050 |
| PDF conversion | ReportLab | .txt → .pdf |

### Environment Variables Required
```bash
export OPENROUTER_API_KEY=sk-or-v1-...    # Required for scoring + tailoring
export BROWSERBASE_API_KEY=...             # Optional (only for --cloud mode)
export BROWSERBASE_PROJECT_ID=...          # Optional (only for --cloud mode)
```

### Python Versions
- **Python 3.9** (system) — used for all scripts except find_jobs.py
- **Python 3.13** (Homebrew) — required for find_jobs.py (Scrapling 0.4.1)
  - Path: `/opt/homebrew/bin/python3.13`

---

## IMPORTANT CONTEXT FOR THE NEW CHAT

1. **Blake is building this for both himself AND his wife** — multi-user support is important
2. **This is a portfolio project** for cybersecurity jobs — code quality and security awareness matter
3. **Python 3.13 for Scrapling, Python 3.9 for everything else** — don't try to upgrade all scripts
4. **Don't touch auto_apply_v4.py Greenhouse logic** — it works perfectly (tested on Human Interest, CyberSheath, Canopy)
5. **The universal form filler is NEW and needs iteration** — test on more sites, fix the 9/14 issue
6. **Blake prefers iterative testing** — make a change, he runs it, pastes output, we fix
7. **Local browser is default now** — no Browserbase dependency
8. **Scrapling's `css_first()` does NOT exist** — use `css()` and take `[0]` instead
9. **LinkedIn logged-in pages use obfuscated CSS classes** — extract data from tag structure, not class names
10. **Cookie banner dismissal is built** — handles "Accept all", "OK", "Got it", common CSS selectors

---

## FILES TO REQUEST IF NOT UPLOADED

Key files to ask for if Blake uploads a new zip:
- `scripts/auto_apply_v4.py` (the main bot — 2200+ lines)
- `scripts/find_jobs.py` (LinkedIn scraper)
- `scripts/build_profile_v2.py` (profile builder)
- `scripts/dashboard.py` + `scripts/dashboard_template.html`
- `profiles/alex/profile.json`
- `profiles/alex/scored_jobs.json`

---

## SUMMARY

**What's done:** Profile builder ✅, LinkedIn scraper ✅, Resume tailoring ✅, PDF conversion ✅, Greenhouse auto-apply ✅, Universal form filler ✅ (needs polish), Dashboard ✅, Local browser ✅, Cookie session saving ✅ (untested)

**What's next:** Fix universal filler (9/14 → 14/14), test Hannah's profile, set up cron job, test iCIMS with saved cookies, move tailored output to per-profile folders.
