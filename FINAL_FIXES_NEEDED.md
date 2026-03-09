# Final Fixes for 100% Automation

## Issue #1: Location Field is React-Select Autocomplete
**Current:** Treated as text field, `.fill()` called but doesn't work
**Problem:** It's a React-Select combobox (`id="candidate-location"`) that needs:
  1. Click to focus
  2. Type the city name
  3. Wait for autocomplete suggestions
  4. Click the matching option from dropdown

**Fix:** Add special handling for autocomplete/combobox fields that aren't yes/no dropdowns:
```python
# For autocomplete fields like Location
if 'location' in label.lower() or 'city' in label.lower():
    combobox.click()
    combobox.type(answer)  # Type to trigger autocomplete
    time.sleep(1)
    # Click first option or exact match
    option = page.locator("div[class*='option']").first
    option.click()
```

## Issue #2: Missing Fields
**Current:** Claude detects 10 fields, but form has ~15 fields
**Missing:**
- How did you hear about this job? (question_63021726)
- LinkedIn Profile URL (question_63021727)
- Do you know anyone at Human Interest? (question_63021728)
- Full legal name (question_63021729)
- EEO fields (optional but present)

**Fix:** Tell Claude to detect ALL fields, not limit to 10. Update prompt to say "Return ALL fields found, no limit"

## Questions for User:

1. **For "How did you hear about this job?" field** - What should we answer?
   Options:
   - "Job board" / "Online job search"
   - "Company website"
   - "Referral" (needs name)
   - Store in profile as "job_source_answer"

2. **For "Do you know anyone at Human Interest?"** - What should we answer?
   - Probably "No" or "N/A"
   - Store in profile

3. **LinkedIn Profile URL** - Do we have this in the profile?
   - Check job_profile.json for LinkedIn URL
   - If not, should we add it?

4. **Full legal name** - We have "Alex J. Carter" - is this correct?
   - Should match resume exactly
