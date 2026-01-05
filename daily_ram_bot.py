import requests
from bs4 import BeautifulSoup
import os
import sys
import time

PCPP_URL = "https://ca.pcpartpicker.com/products/memory/#L=25,300&S=6000,9600&X=0,100522&Z=32768002&sort=price&page=1"

try:
    WEBHOOK_URL = os.environ["DISCORD_WEBHOOK"]
    SCRAPER_API_KEY = os.environ["SCRAPER_API_KEY"]
except KeyError as e:
    print(f"Error: {e} environment variable not set.")
    sys.exit(1)

def get_cheapest_ram(max_retries=3):
    payload = {
        "api_key": SCRAPER_API_KEY,
        "url": PCPP_URL,
        "render": "true",
        "country_code": "ca",
        "device_type": "desktop",
    }

    for attempt in range(max_retries):
        try:
            print(f"Contacting ScraperAPI (attempt {attempt + 1}/{max_retries})...")
            response = requests.get("https://api.scraperapi.com/", params=payload, timeout=90)
            
            if response.status_code == 500:
                print(f"ScraperAPI 500 error. Retrying...")
                time.sleep(5)
                continue
            
            response.raise_for_status()

            soup = BeautifulSoup(response.text, "html.parser")
            product_list = soup.select("tr.tr__product")
            print(f"DEBUG: Found {len(product_list)} products.")
            
            if not product_list:
                print("Error: Product list is empty. Retrying...")
                time.sleep(5)
                continue

            # --- "LAZY" PARSING LOOP ---
            for i, item in enumerate(product_list):
                try:
                    # 1. NAME: Just grab the first link in the row
                    name_element = item.find("a")
                    
                    # 2. PRICE: Look for any text in the row that has a '$'
                    price = None
                    for text in item.stripped_strings:
                        if "$" in text and "Price" not in text:
                            price = text
                            break
                    
                    # --- DEBUGGING IF FAILS ---
                    # If this is the first row and we missed data, dump the HTML so we can see it!
                    if i == 0 and (not name_element or not price):
                        print("\n--- DEBUG: RAW HTML OF ROW 0 ---")
                        print(item.prettify())
                        print("--------------------------------\n")

                    if not name_element or not price:
                        continue

                    name = name_element.get_text(strip=True)
                    # Handle relative links
                    href = name_element["href"]
                    if href.startswith("/"):
                        link = "https://ca.pcpartpicker.com" + href
                    else:
                        link = href

                    # Success!
                    return {"name": name, "price": price, "url": link}

                except Exception:
                    continue
            
            print("Error: Parsed rows but found no valid products.")
            return None

        except Exception as e:
            print(f"Scraping Error: {e}")
            time.sleep(5)
    
    print("Max retries reached.")
    return None

def post_to_discord(item):
    if not item:
        return

    payload = {
        "username": "RAM Bot",
        "embeds": [
            {
                "title": "Daily RAM Deal (32GB DDR5 6000+ CL30)",
                "description": "The current cheapest kit on PCPartPicker (CA).",
                "color": 5814783,
                "fields": [
                    {"name": "Product", "value": item["name"], "inline": False},
                    {"name": "Price", "value": f"**{item['price']}**", "inline": True},
                ],
                "url": item["url"],
            }
        ],
    }

    try:
        requests.post(WEBHOOK_URL.strip(), json=payload, timeout=15)
        print("Success: Posted to Discord.")
    except Exception as e:
        print(f"Discord Error: {e}")

if __name__ == "__main__":
    print("Starting Bot...")
    deal = get_cheapest_ram()

    if deal:
        print(f"Found: {deal['name']} @ {deal['price']}")
        post_to_discord(deal)
    else:
        print("No deal found.")