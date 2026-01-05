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
    # --- FIX: USE PARAMS DICT ---
    # This automatically URL-encodes the special characters (&, #) in your link
    # so ScraperAPI receives the full, valid URL.
    payload = {
        'api_key': SCRAPER_API_KEY,
        'url': PCPP_URL,
        'render': 'true',                 # Force JS rendering
        'wait_for_selector': '.tr__product', # Wait for the table row to appear
        'device_type': 'desktop',         # Force desktop view
    }
    
    try:
        print("Contacting ScraperAPI...")
        # passing 'params=payload' handles the encoding magic
        response = requests.get('http://api.scraperapi.com', params=payload, timeout=60)
        
        print(f"DEBUG: Status Code: {response.status_code}")
        response.raise_for_status()
        
        soup = BeautifulSoup(response.content, "html.parser")
        
        # Select the product rows
        product_list = soup.select("tr.tr__product")
        print(f"DEBUG: Found {len(product_list)} products.")
        
        if not product_list:
            print("Error: Product list is empty.")
            print("--- DEBUG: HTML DUMP (First 2000 chars) ---")
            # If this prints, copy-paste it to me!
            print(soup.prettify()[:2000])
            print("-------------------------------------------")
            return None

        # --- SUCCESS LOGIC ---
        top_item = product_list[0]
        
        name_element = top_item.select_one("div.td__name a")
        name = name_element.get_text(strip=True)
        
        link = "https://ca.pcpartpicker.com" + name_element["href"]
        
        price_element = top_item.select_one("td.td__price")
        price = price_element.get_text(strip=True)
        
        if not price:
            price = "Check Link (Price not scraped)"

        return {"name": name, "price": price, "url": link}

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
        result = requests.post(WEBHOOK_URL, json=payload)
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