"""
Greenhouse-specific dropdown code to add to auto_apply.py

Replace Strategy 5 (combobox) with this React-Select specific logic:
"""

# Strategy 5: React-Select (Greenhouse specific)
if not filled:
    try:
        # Greenhouse uses React-Select with role="combobox" and type="text"
        # The input has an ID like "question_63021724" and clicking it opens options
        
        # Try to find the combobox input by label
        input_el = page.get_by_label(label, exact=False)
        if input_el.count() > 0:
            # Get the first matching input with role="combobox"
            combobox = input_el.filter(has=page.locator("[role='combobox']")).first
            
            if combobox.count() == 0:
                # Try direct role match
                combobox = page.locator(f"[role='combobox'][aria-labelledby*='{label.lower()}']").first
           
            if combobox.count() == 0:
                # Try by ID if we have it from selector
                if selector:
                    combobox = page.locator(selector).first
                else:
                    # Last resort: find any combobox near the label text
                    label_el = page.locator(f"label:has-text('{label}')").first
                    if label_el.count() > 0:
                        # Get the ID from the label's "for" attribute
                        for_id = label_el.get_attribute("for")
                        if for_id:
                            combobox = page.locator(f"#{for_id}").first
            
            if combobox.count() > 0:
                # Click to open the dropdown
                combobox.click()
                time.sleep(0.8)  # Wait for options to render
                
                # Now click the option with our answer text
                # React-Select renders options as divs with specific class
                try:
                    # Try exact match first
                    option = page.locator(f"div[class*='option']:has-text('{answer}')").first
                    if option.count() > 0 and option.is_visible():
                        option.click()
                        filled = True
                        print(f"    ✅ {label} (strategy 5: React-Select)")
                except:
                    pass
                
                # If exact match failed, try role="option"
                if not filled:
                    try:
                        option = page.get_by_role("option", name=answer).first
                        if option.is_visible():
                            option.click()
                            filled = True
                            print(f"    ✅ {label} (strategy 5: React-Select option)")
                    except Exception as e:
                        error_msg = str(e)
        
    except Exception as e:
        error_msg = str(e)
