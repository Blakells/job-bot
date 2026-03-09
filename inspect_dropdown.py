#!/usr/bin/env python3
"""
Inspect Greenhouse dropdown structure
"""
import os, time
from playwright.sync_api import sync_playwright

BROWSERBASE_API_KEY = os.environ.get("BROWSERBASE_API_KEY", "")
BROWSERBASE_PROJECT = os.environ.get("BROWSERBASE_PROJECT_ID", "")

def inspect_dropdowns():
    # Create session
    import requests
    resp = requests.post(
        "https://www.browserbase.com/v1/sessions",
        headers={"x-bb-api-key": BROWSERBASE_API_KEY, "Content-Type": "application/json"},
        json={"projectId": BROWSERBASE_PROJECT, "browserSettings": {"stealth": True}})
    data = resp.json()
    session_id = data.get("id")
    connect_url = data.get("connectUrl") or f"wss://connect.browserbase.com?apiKey={BROWSERBASE_API_KEY}&sessionId={session_id}"
    
    print(f"Session: {session_id}")
    
    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(connect_url)
        ctx = browser.contexts[0] if browser.contexts else browser.new_context()
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        
        # Load page
        print("Loading Human Interest job page...")
        page.goto("https://job-boards.greenhouse.io/humaninterest/jobs/7565471", wait_until="domcontentloaded")
        time.sleep(3)
        
        # Click Apply
        print("Clicking Apply button...")
        apply_btn = page.get_by_role("button", name="Apply")
        if apply_btn.count() == 0:
            apply_btn = page.get_by_role("link", name="Apply")
        
        if apply_btn.count() > 0:
            apply_btn.first.click()
            time.sleep(3)
            print("Form opened!")
        
        # Find the work authorization dropdown
        print("\n" + "="*60)
        print("INSPECTING WORK AUTHORIZATION DROPDOWN")
        print("="*60)
        
        # Try to find by label
        label = "Are you legally authorized to work in the United States?"
        
        # Get all select elements
        selects = page.locator("select").all()
        print(f"\nFound {len(selects)} <select> elements total")
        
        for i, select in enumerate(selects, 1):
            name = select.get_attribute("name") or "no-name"
            id_attr = select.get_attribute("id") or "no-id"
            print(f"\nSelect {i}:")
            print(f"  Name: {name}")
            print(f"  ID: {id_attr}")
            
            # Get the options
            options = select.locator("option").all()
            print(f"  Options ({len(options)}):")
            for opt in options[:5]:  # First 5 options
                value = opt.get_attribute("value") or ""
                text = opt.inner_text()
                print(f"    - value='{value}' text='{text}'")
        
        # Check if there are custom dropdowns (non-select)
        print("\n" + "="*60)
        print("CHECKING FOR CUSTOM DROPDOWNS")
        print("="*60)
        
        # Look for common custom dropdown patterns
        comboboxes = page.locator("[role='combobox']").all()
        print(f"\nFound {len(comboboxes)} elements with role='combobox'")
        
        # Look for divs that might be custom dropdowns
        custom_dropdowns = page.locator("div.select, div.dropdown, [class*='select'], [class*='dropdown']").all()
        print(f"Found {len(custom_dropdowns)} elements with dropdown-like classes")
        
        # Get the full HTML of the form for analysis
        print("\n" + "="*60)
        print("GETTING FORM HTML")
        print("="*60)
        
        form = page.locator("form").first
        if form:
            html = form.inner_html()
            # Save to file
            with open("outputs/greenhouse_form.html", "w") as f:
                f.write(html)
            print("Saved form HTML to outputs/greenhouse_form.html")
            
            # Look for the work auth field specifically
            if "authorized to work" in html.lower():
                print("\n✅ Found 'authorized to work' text in form HTML")
                # Extract just that section
                start = html.lower().find("authorized to work") - 500
                end = html.lower().find("authorized to work") + 500
                section = html[max(0,start):min(len(html), end)]
                
                print("\nHTML around 'authorized to work':")
                print("-"*60)
                print(section[:1000])
        
        browser.close()
    
    # Clean up session
    requests.delete(f"https://www.browserbase.com/v1/sessions/{session_id}",
        headers={"x-bb-api-key": BROWSERBASE_API_KEY})

if __name__ == "__main__":
    inspect_dropdowns()
