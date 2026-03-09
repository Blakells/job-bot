# Dropdown Filling Fix

## Problem
Current code fails to fill dropdown/select fields silently. Uses:
```python
if ftype == "select":
    el.first.select_option(answer)
```

This doesn't work because:
1. `get_by_label()` might not find the select element
2. Greenhouse may use custom dropdowns (not standard `<select>`)
3. Errors are caught but not properly logged

## Solution - Multi-Strategy Approach

Try multiple strategies in order:

### Strategy 1: Standard Select by Label
```python
el = page.get_by_label(label)
if el.count() > 0:
    el.first.select_option(label=answer)
```

### Strategy 2: Select by CSS Selector
```python
el = page.locator(f"select[name*='{label_slug}']")
if el.count() > 0:
    el.first.select_option(label=answer)
```

### Strategy 3: Custom Dropdown (Click + Select)
```python
# For Greenhouse custom dropdowns
dropdown = page.get_by_label(label)
dropdown.click()  # Open dropdown
page.get_by_text(answer, exact=True).click()  # Select option
```

### Strategy 4: Combobox Pattern
```python
combobox = page.locator(f"[role='combobox'][aria-label*='{label}']")
if combobox.count() > 0:
    combobox.click()
    page.get_by_role("option", name=answer).click()
```

## Implementation
Replace the select filling section with enhanced logic that:
1. Logs which strategy is being tried
2. Tries each strategy until one succeeds
3. Reports clear error if all fail
4. Adds screenshot on dropdown failures
