# Multi-Page Form Navigation Upgrade

## Overview
Add ability to handle multi-page forms (Greenhouse, Workday, etc.) that have Continue/Next buttons before the final Submit.

## Changes Required:

### 1. Update get_form_fields() to detect Continue vs Submit

Add to the return JSON structure:
```python
{
  "form_fields": [...],
  "submit_button": "Submit Application",
  "continue_button": "",  # NEW: "Continue" or "Next" if intermediate page
  "is_final_page": true   # NEW: false if Continue button exists
}
```

Update the prompt to include:
```
If this page has a "Continue" or "Next" button (not a final Submit), set:
- "continue_button": "exact button text"
- "is_final_page": false

If this is the FINAL page with Submit, set:
- "continue_button": ""
- "is_final_page": true
```

### 2. Wrap form processing in a multi-page loop

Replace the single form processing section with a loop:

```python
# ── STEP 5: Application form (MULTI-PAGE) ────────────────────
if info["page_type"] in ["application_form", "individual_job_page"]:
    page_number = 1
    max_pages = 10  # Safety limit
    
    while page_number <= max_pages:
        print(f"\n  📄 Page {page_number}")
        print(f"  {'─'*50}")
        
        page_text = page.inner_text("body")
        form = get_form_fields(page_text, profile, job, resume_path, cover_letter_path)
        fields = form.get("form_fields", [])
        is_final = form.get("is_final_page", True)
        continue_btn = form.get("continue_button", "")
        
        print(f"  ✅ Found {len(fields)} fields")
        print(f"  📍 {'Final page' if is_final else f'Intermediate page (Continue: {continue_btn})'}")
        
        # Ask user for uncertain answers (only once per session)
        uncertain = [f for f in fields if not f.get("confident") and f.get("type") != "file"]
        extra = ask_user(uncertain, all_answers)
        new_answers.update(extra)
        all_answers.update(extra)
        
        # Show fill plan
        print(f"\n  📋 Fill plan:")
        print(f"  {'─'*50}")
        for f in fields:
            ans = f.get("answer", "")
            if ans == "UNCERTAIN":
                ans = all_answers.get(f.get("label",""), "⚠️ NO ANSWER")
            elif ans == "RESUME_FILE":
                ans = f"📄 {Path(resume_path).name if resume_path else 'NO FILE'}"
            elif ans == "COVER_LETTER_FILE":
                ans = f"📄 {Path(cover_letter_path).name if cover_letter_path else 'NO FILE'}"
            icon = "✅" if f.get("confident") else "📝"
            print(f"  {icon} {f.get('label','')}: {str(ans)[:60]}")
        print(f"  {'─'*50}")
        
        if dry_run:
            screenshot(page, f"{slug}_page{page_number}_preview")
            print(f"\n  [DRY RUN] Page {page_number} analyzed")
            
            # If not final page and in dry run, simulate clicking Continue
            if not is_final and continue_btn:
                print(f"  [DRY RUN] Would click: {continue_btn}")
                page_number += 1
                continue
            else:
                print(f"\n  [DRY RUN] Reached final page — not submitting")
                browser.close()
                return "dry_run_ok", new_answers
        
        # Fill fields (same code as before)
        print(f"\n  ✏️  Filling fields...")
        for f in fields:
            label = f.get("label", "")
            answer = f.get("answer", "")
            selector = f.get("selector", "")
            ftype = f.get("type", "text")
            
            if answer == "UNCERTAIN":
                answer = all_answers.get(label, "")
            
            if not answer:
                continue
            
            # [FILE UPLOAD CODE - keep existing]
            if ftype == "file":
                # ... existing file upload code ...
                continue
            
            # [TEXT/SELECT FIELDS - keep existing]
            try:
                el = None
                if selector:
                    el = page.locator(selector)
                if not el or el.count() == 0:
                    el = page.get_by_label(label)
                if el and el.count() > 0:
                    if ftype == "select":
                        el.first.select_option(answer)
                    else:
                        el.first.fill(str(answer))
                    print(f"    ✅ {label}")
            except Exception as e:
                print(f"    ⚠️  {label}: {e}")
        
        screenshot(page, f"{slug}_page{page_number}_filled")
        
        # If intermediate page, click Continue
        if not is_final and continue_btn:
            print(f"\n  ➡️  Clicking: {continue_btn}")
            clicked = False
            for pattern in [continue_btn, "Continue", "Next", "Next Page"]:
                try:
                    btn = page.get_by_role("button", name=pattern)
                    if btn.count() == 0:
                        btn = page.get_by_role("link", name=pattern)
                    if btn.count() > 0:
                        btn.first.click()
                        time.sleep(3)
                        page_number += 1
                        clicked = True
                        print(f"  ✅ Clicked {pattern}")
                        break
                except:
                    continue
            
            if not clicked:
                print(f"  ⚠️  Could not find Continue button")
                browser.close()
                return "continue_button_error", new_answers
            
            # Loop continues to next page
            continue
        
        # Final page - ask to submit
        print(f"\n  📸 Check filled form:")
        print(f"     open outputs/screenshots/{slug}_page{page_number}_filled.png")
        
        confirm = input("\n  Type YES to submit, SKIP to skip: ").strip().upper()
        if confirm == "YES":
            submit = form.get("submit_button", "Submit")
            for pattern in [submit, "Submit Application", "Submit", "Apply"]:
                try:
                    btn = page.get_by_role("button", name=pattern)
                    if btn.count() > 0:
                        btn.first.click()
                        time.sleep(3)
                        screenshot(page, f"{slug}_submitted")
                        print(f"  🎉 Submitted!")
                        browser.close()
                        return "submitted", new_answers
                except:
                    continue
            browser.close()
            return "submit_error", new_answers
        else:
            browser.close()
            return "user_skipped", new_answers
    
    # Max pages exceeded
    print(f"  ⚠️  Exceeded max pages ({max_pages})")
    browser.close()
    return "max_pages_exceeded", new_answers
```

### 3. Update icons in main()

Add new status icons:
```python
icons = {"submitted":"🎉","dry_run_ok":"✅","user_skipped":"⏭️",
         "login_required":"🔐","no_job_found":"🔍","error":"❌","no_resume":"⚠️",
         "continue_button_error":"⚠️", "max_pages_exceeded":"⚠️"}
```

## Testing Plan

1. Dry run on CyberSheath (known multi-page form)
2. Verify it detects all pages
3. Verify Continue button detection works
4. Verify final Submit button detected correctly
