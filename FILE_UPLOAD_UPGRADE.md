# File Upload Upgrade for auto_apply.py

## Changes Needed:

### 1. Add file-finding function (insert after `screenshot()` function, around line 70):

```python
def find_tailored_files(company, title):
    """Find the tailored resume and cover letter for this job."""
    tailored_dir = Path("outputs/tailored")
    if not tailored_dir.exists():
        print("  ⚠️  No tailored directory found")
        return None, None
    
    # Normalize company and title for matching
    import re
    company_norm = re.sub(r'[^a-zA-Z0-9]+', '_', company).strip('_')
    
    resume = None
    cover_letter = None
    
    # Search for matching files - look for files containing company name
    for file in tailored_dir.glob("*_RESUME.txt"):
        filename = file.stem.lower()
        
        # Check if company appears in filename
        if company_norm.lower() in filename:
            # Also check if key words from title appear
            title_words = [w.lower() for w in title.split() if len(w) > 3]
            if any(word in filename for word in title_words[:3]):
                resume = str(file.absolute())
                # Look for corresponding cover letter
                cover_file = file.parent / file.name.replace("_RESUME.txt", "_COVER_LETTER.txt")
                if cover_file.exists():
                    cover_letter = str(cover_file.absolute())
                print(f"  📄 Found resume: {file.name}")
                if cover_letter:
                    print(f"  📄 Found cover letter: {cover_file.name}")
                break
    
    if not resume:
        print(f"  ⚠️  No tailored resume found for {company} - {title}")
    
    return resume, cover_letter
```

### 2. Update `get_form_fields()` function signature (line ~120):

BEFORE:
```python
def get_form_fields(page_text, profile, job):
```

AFTER:
```python
def get_form_fields(page_text, profile, job, resume_path, cover_letter_path):
```

### 3. Add to prompt in `get_form_fields()` (after candidate info, before IMPORTANT RULES):

```python
FILE UPLOADS AVAILABLE:
- Resume file: {"YES" if resume_path else "NO"}
- Cover letter file: {"YES" if cover_letter_path else "NO"}
```

### 4. Add to IMPORTANT RULES in prompt:

```python
- For file upload fields (Resume/CV), set type="file" and answer="RESUME_FILE"
- For cover letter uploads, set type="file" and answer="COVER_LETTER_FILE"
```

### 5. Update example in prompt to include file upload example:

```python
    {{
      "label": "Resume/CV",
      "type": "file",
      "answer": "RESUME_FILE",
      "confident": true,
      "selector": "input[type='file'][name='resume']"
    }},
```

### 6. Update `run_application()` signature (line ~180):

BEFORE:
```python
def run_application(connect_url, job, profile, memory, dry_run):
```

AFTER:
```python
def run_application(connect_url, job, profile, memory, dry_run, resume_path, cover_letter_path):
```

### 7. Update form field analysis call (around line ~290):

BEFORE:
```python
form = get_form_fields(page_text, profile, job)
```

AFTER:
```python
form = get_form_fields(page_text, profile, job, resume_path, cover_letter_path)
```

### 8. Update display logic in "Show fill plan" section (around line ~300):

ADD after uncertain field filtering:
```python
# Show fill plan with file uploads
for f in fields:
    ans = f.get("answer", "")
    if ans == "UNCERTAIN":
        ans = all_answers.get(f.get("label",""), "⚠️ NO ANSWER")
    elif ans == "RESUME_FILE":
        ans = f"📄 {Path(resume_path).name if resume_path else 'NO FILE'}"
    elif ans == "COVER_LETTER_FILE":
        ans = f"📄 {Path(cover_letter_path).name if cover_letter_path else 'NO FILE'}"
```

### 9. Add file upload handling to field filling loop (around line ~330, BEFORE text field filling):

```python
                # Fill fields
                print(f"\n  ✏️  Filling fields...")
                for f in fields:
                    label    = f.get("label", "")
                    answer   = f.get("answer", "")
                    selector = f.get("selector", "")
                    ftype    = f.get("type", "text")
                    
                    if answer == "UNCERTAIN":
                        answer = all_answers.get(label, "")
                    
                    if not answer:
                        continue
                    
                    # Handle file uploads
                    if ftype == "file":
                        file_path = None
                        if answer == "RESUME_FILE" and resume_path:
                            file_path = resume_path
                        elif answer == "COVER_LETTER_FILE" and cover_letter_path:
                            file_path = cover_letter_path
                        
                        if file_path:
                            try:
                                # Try multiple selectors for file inputs
                                el = None
                                selectors_to_try = [
                                    selector,
                                    "input[type='file']",
                                    "input[type='file'][name*='resume']",
                                    "input[type='file'][name*='cv']",
                                    "input[type='file'][id*='resume']",
                                    "input[type='file'][id*='cv']"
                                ] if "resume" in label.lower() or "cv" in label.lower() else [
                                    selector,
                                    "input[type='file']",
                                    "input[type='file'][name*='cover']",
                                    "input[type='file'][id*='cover']"
                                ]
                                
                                for sel in selectors_to_try:
                                    if sel:
                                        try:
                                            el = page.locator(sel).first
                                            if el.count() > 0:
                                                break
                                        except:
                                            continue
                                
                                if el and el.count() > 0:
                                    el.set_input_files(file_path)
                                    print(f"    ✅ {label} (uploaded {Path(file_path).name})")
                                else:
                                    print(f"    ⚠️  {label}: Could not find file input")
                            except Exception as e:
                                print(f"    ⚠️  {label}: {e}")
                        continue
                    
                    # Handle regular text/select fields (existing code continues here)
```

###10. Update main() to find files and pass them (around line ~470):

ADD after URL check:
```python
        # Find tailored files
        resume_path, cover_letter_path = find_tailored_files(company, title)
        
        if not resume_path:
            print(f"  ⚠️  No resume found - skipping")
            results.append({"job": title, "company": company, "status": "no_resume"})
            continue
```

UPDATE the run_application call:
```python
            status, new_answers = run_application(
                connect_url, job, profile, memory, args.dry_run, resume_path, cover_letter_path)
```

UPDATE icons dict:
```python
    icons = {"submitted":"🎉","dry_run_ok":"✅","user_skipped":"⏭️",
             "login_required":"🔐","no_job_found":"🔍","error":"❌","no_resume":"⚠️"}
```

### 11. Add `import re` to imports at top of file
