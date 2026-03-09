"""
Add this as a new function in auto_apply.py to handle Location autocomplete fields
"""

def fill_location_autocomplete(page, label, location_value):
    """
    Fill React-Select autocomplete fields like Location/City
    Types the value and selects from dropdown suggestions
    """
    try:
        # Find the label to get the input ID
        label_el = page.locator(f"label:has-text('{label}')").first
        
        if label_el.count() == 0:
            # Try with just "Location" or "City"
            if 'location' in label.lower():
                label_el = page.locator("label:has-text('Location')").first
            elif 'city' in label.lower():
                label_el = page.locator("label:has-text('City')").first
        
        if label_el.count() > 0:
            input_id = label_el.get_attribute("for")
            
            if input_id:
                # Find the autocomplete input
                autocomplete = page.locator(f"#{input_id}")
                
                if autocomplete.count() > 0:
                    # Click to focus
                    autocomplete.click()
                    time.sleep(0.3)
                    
                    # Type the location - start with city name
                    # Extract just the city from "Florence, SC"
                    city = location_value.split(',')[0].strip()
                    autocomplete.type(city, delay=100)  # Type with delay
                    time.sleep(1.2)  # Wait for autocomplete suggestions
                    
                    # Try to find an option with state name
                    state_options = page.locator("div[class*='option']:has-text('South Carolina')").all()
                    if len(state_options) > 0:
                        # Click first South Carolina option
                        state_options[0].click()
                        return True
                    
                    # If no specific state match, type full location
                    autocomplete.fill("")  # Clear
                    autocomplete.type(location_value, delay=100)
                    time.sleep(1.2)
                    
                    # Click first option
                    first_option = page.locator("div[class*='option']").first
                    if first_option.count() > 0 and first_option.is_visible():
                        first_option.click()
                        return True
        
        return False
    except Exception as e:
        print(f"    Location autocomplete error: {e}")
        return False
