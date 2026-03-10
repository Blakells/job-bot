# Job Bot — Claude Code Guidelines

## Project Overview
Automated job application bot (v5.0) that fills web forms using Playwright browser automation. Supports Greenhouse ATS and a universal form filler for any website. Uses Claude (via OpenRouter) for AI-assisted field mapping.

## Architecture
```
job_bot/
  applier.py      — Orchestrator: runs the fill loop, toggle/dropdown sweeps, post-fill verification
  form_filler.py  — Core filling logic: text, email, selects, toggles, file uploads, dropdown sweeps
  fields.py       — DOM field extraction JS, Greenhouse parser, Claude field mapper
  profile.py      — Profile loading, answer map building, field resolution
  browser.py      — Playwright setup, session management, screenshots
  react_select.py — React-select component handling (Greenhouse-specific)
  ai.py           — Claude API via OpenRouter
  config.py       — Env vars, STATE_MAP, settings
scripts/
  auto_apply.py   — CLI entry point
profiles/
  alex/profile.json — Test profile (Alex Carter, cybersecurity analyst)
```

## Critical Rules

### 1. Bug Fixing Workflow
When a bug is reported, do NOT start by trying to fix it. Instead:
1. **Write a test that reproduces the bug** — prove the bug exists with a failing test
2. **Use subagents to fix the bug** — have them implement the fix and prove it with a passing test
3. Only consider the bug fixed when the test passes

### 2. Minimal, Targeted Changes Only
Every code change risks regressions. The form filler interacts with live websites where small logic errors cascade (e.g., a skip check that's too broad silently skips ALL fields). When fixing a bug:
- Change the fewest lines possible
- Never rewrite working code "while you're in there"
- Test the exact scenario that was failing
- Verify existing behavior still works

### 3. Never Trust DOM Parent Walks
Walking up the DOM from an input to find context (labels, containers, values) is the #1 source of bugs in this codebase. A parent walk that works on one site will match unrelated elements on another. Lessons learned:
- **Prescan uses top-down approach**: Only mark inputs as react-select if they have `role="combobox"` or `aria-autocomplete` attributes. Never use broad class-name substring matching (`css-`, `-container`) to walk up from inputs.
- **Scope searches to component containers**: When looking for a displayed value, search within the specific component, not the entire page.
- The scrapling prescan (`prescan_page_with_scrapling()`) runs once before any interaction to map the page structure.

### 4. React Form Filling
Paylocity and similar React-based ATS sites require special handling:
- `el.fill("")` + `el.type()` is the standard approach for text fields (fires real keyboard events)
- React-select/autocomplete fields: `el.fill("")` → `el.type(answer, delay=50)` → `el.press("Enter")`
- Email fields: Resume upload may auto-fill a wrong email. Must clear first, then type fresh.
- JS `nativeSetter` + `dispatchEvent` does NOT clear validation errors — real keyboard events do
- Custom dropdowns (Paylocity `rw-widget`): click trigger → read options → determine answer → click option

### 5. Dropdown Answer Determination
`_determine_dropdown_answer()` in form_filler.py handles dynamic dropdown filling. When adding new rules:
- Yes/No detection strips asterisks and special chars (Paylocity uses "Yes*")
- Profile-based answers use keyword matching against the dropdown label
- Options are read AFTER opening the dropdown (they're not in the DOM until opened)
- `READ_DROPDOWN_OPTIONS_JS` prioritizes `role="option"` inside `role="listbox"` containers

### 6. The Fill Pipeline
```
1. Extract fields (fields.py)
2. Auto-map answers (applier.py — profile + keyword matching)
3. Claude maps remaining fields (via OpenRouter)
4. Scrapling prescan (form_filler.py — top-down react-select detection)
5. Fill loop (form_filler.py — fill_generic_field per field)
6. Post-fill sweep:
   a. Toggle buttons (YES/NO keyword rules)
   b. Standard <select> dropdowns (Phase 1)
   c. Custom rw-widget dropdowns showing "--" (Phase 2)
7. Post-fill verification (applier.py — check for validation errors)
```

## Tech Stack
- **Python** >= 3.10 (project .venv uses 3.13)
- **Playwright** for browser automation
- **Scrapling** v0.4.2 — `from scrapling import Selector` (NOT `Adaptor` — that was v0.2.x)
  - Constructor: `Selector(html_string)` (positional arg, not `text=`)
  - No `css_first()` — use `css()[0] if css() else None`
- **OpenRouter** API for Claude calls (field mapping)

## Testing
Run against Paylocity test URL:
```bash
python3 scripts/auto_apply.py \
  --url "https://recruiting.paylocity.com/recruiting/jobs/Apply/3510651/GEOGRAPHIC-SOLUTIONS-INC/Information-Security-Analyst-I" \
  --profile profiles/alex/profile.json
```
Check terminal output for: prescan summary, fill results, post-fill verification issues.

## Known Issues Being Worked
- Email validation error on Paylocity (React validation not clearing after programmatic fill)
- Education section `<select>` elements (Degree Obtained, School Type) may need a Phase 3 sweep
- Post-fill verification reports false positives for react-select hidden inputs
