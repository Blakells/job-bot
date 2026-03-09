# Job Bot — Update Changelog
## March 9, 2026

---

## Bug Fixes

### Bug #7: Dashboard Route Parameters (dashboard.py)
**Problem:** Routes used `<n>` but function signatures expected `name`, causing Flask to throw a TypeError on every API call.
**Fix:** Changed all three route decorators to use `<name>` to match the function parameters.
- `/api/profile/<name>` → `def api_profile(name)`
- `/api/jobs/<name>` (GET) → `def api_get_jobs(name)`
- `/api/jobs/<name>` (POST) → `def api_save_jobs(name)`

### Bug #8: --single Flag Now 1-Based (auto_apply_v4.py)
**Problem:** `--single 21` was 0-indexed, which was confusing since the dashboard shows 1-based numbers.
**Fix:** `--single` is now 1-based. `--single 1` runs the first job, `--single 21` runs job #21.
- Help text updated to say "(1-based, matches dashboard #)"
- Error message shows valid range as "1-N" instead of "0-N"

### Bug #9: Per-Profile Tailored Output (tailor_resume.py)
**Problem:** All tailored files went to `outputs/tailored/` regardless of profile, so Alex and Hannah's files would mix.
**Fix:** Output now defaults to `profiles/{name}/tailored/` based on the `--profile` path.
- `--profile profiles/alex/profile.json` → outputs to `profiles/alex/tailored/`
- `--output` flag still works as a manual override
- Falls back to `outputs/tailored/` for legacy profile paths

**Also updated auto_apply_v4.py:** `find_tailored_files()` now accepts a `profile_path` parameter and searches per-profile `tailored/` directories first, then falls back to the global `outputs/tailored/`.

---

## Universal Form Filler Improvements (auto_apply_v4.py)

### 1. Massively Improved Label Extraction (EXTRACT_FIELDS_JS)
The JavaScript field extractor now tries **11 strategies** instead of 6 to find a label for every field:

1. Explicit `<label for="id">` (same as before)
2. Parent `<label>` — now clones and strips input children for cleaner text
3. `aria-label` attribute
4. `aria-labelledby` — now handles space-separated multi-ID references
5. **NEW:** `aria-describedby` — commonly used for field descriptions
6. **NEW:** `data-*` attributes (`data-automation-id`, `data-field-name`, `data-qa`, `data-testid`, `data-label`, `data-name`) — catches Workday, Lever, custom ATS fields
7. Placeholder text
8. **IMPROVED:** Preceding sibling scan — now checks up to 3 siblings and accepts `<span>`, `<div>`, `<p>`, `<h3>`, `<h4>`, `<h5>`, `<legend>` tags
9. **NEW:** Parent container label scan — looks for label/span/div children inside `.field`, `.form-group`, `.form-field`, `.question`, `[class*="field"]`, `MuiFormControl-root`, etc.
10. **NEW:** Section header detection — finds nearest heading above the field (within 200px)
11. `name` attribute — now cleans up camelCase (e.g., `firstName` → `first Name`)

**Also added:**
- `parentClass` and `section` context passed alongside each field for smarter mapping
- Radio button option extraction (reads labels of all radios with same `name`)
- Cleaned label output (strips asterisks, "(required)", excess whitespace)

### 2. Comprehensive Auto-Mapping (build_answer_map)
Went from **~25 keyword mappings** to **100+** covering:

- **Name variants:** `firstname`, `fname`, `candidate name`, etc.
- **Contact:** `email address`, `mobile`, `cell`, etc.
- **Work auth:** 15+ variants including `eligible to work`, `right to work`, `u.s. citizen`
- **URLs:** `linkedin`, `portfolio`, `personal website`, `github profile`
- **Professional:** `current title`, `current employer`, `most recent company`, `experience level`
- **Salary:** 8+ variants including `compensation`, `pay expectation`, `minimum salary`
- **Location:** City, state, country, zip handled separately + combined variants
- **Availability:** `when can you start`, `notice period`, `employment type`
- **Background:** `background check`, `drug test`, `non-compete`, `security clearance`
- **Summary/Bio:** `professional summary`, `about yourself`, `tell us about yourself`, `introduction`, `cover letter` (as text)
- **EEOC:** All common demographic fields with "Decline to self-identify" defaults
- **Source:** `referral source`, `where did you find`, etc.

### 3. Smarter Auto-Mapping Logic (run_universal_application)
The mapping loop now has **7 strategies** instead of 3:

1. Direct ID/name exact match
2. **NEW:** Fuzzy ID/name match — normalizes away dashes, underscores, dots, numbers (catches `first-name`, `first_name`, `firstName`)
3. Label keyword match
4. **NEW:** Placeholder/name keyword match — catches fields with blank labels
5. **IMPROVED:** File field detection — uses `parentClass`, `section`, and positional logic (first file → resume, second → cover letter)
6. **NEW:** Textarea cover letter / summary detection — detects textarea fields that want cover letter text or a professional summary
7. **NEW:** Smart location field splitting — detects whether a field wants just city, just state, just country, or combined

### 4. Cover Letter as Text
**Problem:** Some forms have a textarea for "Cover Letter" instead of a file upload, and it was being skipped.
**Fix:** New `COVER_LETTER_TEXT` magic value:
- Auto-detected when a textarea label contains "cover letter", "cover_letter", etc.
- `fill_generic_field()` reads the cover letter .txt file and pastes its content
- Fill plan shows "✉️ Cover letter text (pasted)" for these fields

### 5. Better Select Dropdown Matching (fill_generic_field)
- Added partial text matching as a fallback when exact label/value match fails
- Tries: exact label → exact value → partial text overlap

### 6. Tab/Blur After Fill
- Text fields now press Tab after filling to trigger validation events
- Prevents forms from showing "field required" errors after the bot fills them

### 7. Enhanced Claude Prompt (claude_map_fields)
- Now includes: work history, current role/company, summary, location components (city/state separately), salary
- Explicit instruction to fill BOTH required AND optional fields
- Better guidance for EEOC fields (pick declining option from available options)
- Tells Claude about `COVER_LETTER_TEXT` for textarea fields
- Passes field `name` and `section` attributes for better context

---

## Updated Pipeline Commands

```bash
# Tailoring now auto-outputs to per-profile directory:
python3 scripts/tailor_resume.py --jobs profiles/alex/scored_jobs.json \
  --resume profiles/alex/Alex_Carter_Resume_2.txt \
  --profile profiles/alex/profile.json --min-score 70
# → Saves to profiles/alex/tailored/  (not outputs/tailored/)

# --single is now 1-based:
python3 scripts/auto_apply_v4.py --jobs profiles/alex/scored_jobs.json \
  --profile profiles/alex/profile.json --single 1  # First job, not zeroth
```

---

## Files Changed

| File | Lines Before | Lines After | What Changed |
|------|-------------|-------------|--------------|
| `scripts/auto_apply_v4.py` | 2,220 | 2,656 | Form filler upgrade, per-profile tailored lookup, --single 1-indexed |
| `scripts/tailor_resume.py` | 172 | 185 | Per-profile output directory |
| `scripts/dashboard.py` | 139 | 139 | Route parameter fix |

---

## What to Test

1. **Dashboard:** Run `python3 scripts/dashboard.py` and verify the profile selector / job list loads
2. **Dry run on Workable (ProSync):** Test the improved form filler — should now get 13-14/14 fields instead of 9/14
3. **Dry run on any new site:** Check that blank-label fields are now being detected and filled
4. **tailor_resume.py:** Run it with `--profile profiles/alex/profile.json` and verify output goes to `profiles/alex/tailored/`
5. **--single flag:** Verify `--single 1` gets the first job (not `--single 0`)
