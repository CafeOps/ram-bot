import requests
from bs4 import BeautifulSoup
import os
import sys

# Your Filter URL
PCPP_URL = "https://ca.pcpartpicker.com/products/memory/#L=25,300&S=6000,9600&X=0,100522&Z=32768002&sort=price&page=1"

# Load Secrets
try:
    WEBHOOK_URL = os.environ["DISCORD_WEBHOOK"]
    SCRAPER_API_KEY = os.environ["SCRAPER_API_KEY"]
except KeyError as e:
    print(f"Error: {e} environment variable not set.")
    sys.exit(1)

def get_cheapest_ram():
    # --- CONFIG THAT WORKED ---
    # We removed 'country_code' because it was causing timeouts.
    # We put back 'wait_for_selector' because it ensures the table is actually there.
    payload = {
        'api_key': SCRAPER_API_KEY,
        'url': PCPP_URL,
        'render': 'true',
        'wait_for_selector': '.tr__product',
        'device_type': 'desktop',
    }
    
    try:
        print("Contacting ScraperAPI...")
        # Increased timeout to 80s just to be safe
        response = requests.get('http://api.scraperapi.com', params=payload, timeout=80)
        
        print(f"DEBUG: Status Code: {response.status_code}")
        response.raise_for_status()
        
        soup = BeautifulSoup(response.content, "html.parser")
        
        product_list = soup.select("tr.tr__product")
        print(f"DEBUG: Found {len(product_list)} products.")
        
        if not product_list:
            print("Error: Product list is empty.")
            return None

        # --- SMART LOOP (Fixes the crash) ---
        for i, item in enumerate(product_list):
            try:
                # 1. Find the name
                name_element = item.select_one("div.td__name a")
                if not name_element:
                    continue

                # 2. Find the price
                price_element = item.select_one("td.td__price")
                if not price_element:
                    continue
                    
                # 3. Extract text
                name = name_element.get_text(strip=True)
                link = "https://ca.pcpartpicker.com" + name_element["href"]
                price = price_element.get_text(strip=True)
                
                # 4. Validate Price (Skip "Price" header or empty)
                if not price or "Price" in price:
                    continue

                # Found a valid one!
                return {"name": name, "price": price, "url": link}

            except Exception:
                continue
        
        print("Error: No valid products found in the list.")
        return None

    except Exception as e:
        print(f"Scraping Error: {e}")
        return None

def post_to_discord(item):
    if not item:
        return
    
    payload = {
        "username": "RAM Bot",
        "embeds": [
            {
                "title": "Daily RAM Deal (32GB DDR5 6000+ CL30)",
                "description": f"The current cheapest kit on PCPartPicker (CA).",
                "color": 5814783, 
                "fields": [
                    {
                        "name": "Product",
                        "value": item['name'],
                        "inline": False
                    },
                    {
                        "name": "Price",
                        "value": f"**{item['price']}**",
                        "inline": True
                    }
                ],
                "url": item['url']
            }
        ]
    }
    
    try:
        # STRIP fixes any accidental newlines in the webhook URL
        clean_webhook = WEBHOOK_URL.strip()
        result = requests.post(clean_webhook, json=payload)
        result.raise_for_status()
        print("Success: Posted to Discord.")
    except requests.exceptions.RequestException as e:
        print(f"Discord Error: {e}")

if __name__ == "__main__":
    print("Starting Bot...")
    deal = get_cheapest_ram()
    
    if deal:
        print(f"Found: {deal['name']} @ {deal['price']}")
        post_to_discord(deal)
    else:
        print("No deal found.")