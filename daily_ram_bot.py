import requests
from bs4 import BeautifulSoup
import os
import sys
import time
import json
from datetime import datetime

# Your Filter URL
PCPP_URL = "https://ca.pcpartpicker.com/products/memory/#L=25,300&S=6000,9600&X=0,100522&Z=32768002&sort=price&page=1"
HISTORY_FILE = "price_history.json"

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
                time.sleep(5)
                continue
            
            response.raise_for_status()

            soup = BeautifulSoup(response.text, "html.parser")
            product_list = soup.select("tr.tr__product")
            
            if not product_list:
                time.sleep(5)
                continue

            for item in product_list:
                try:
                    name_element = item.find("a")
                    if not name_element: continue

                    name = name_element.get_text(strip=True)
                    link = "https://ca.pcpartpicker.com" + name_element["href"]
                    
                    # --- PRICE FIX: Scan all text in row for the biggest price ---
                    # The "Price/GB" is usually small ($3-10). The Total Price is big ($100+).
                    # We grab all price strings, convert to float, and take the biggest one.
                    prices = []
                    for text in item.stripped_strings:
                        if "$" in text and "Price" not in text:
                            try:
                                # Clean string: "$145.99" -> 145.99
                                clean_price = float(text.replace('$', '').replace(',', ''))
                                prices.append(clean_price)
                            except ValueError:
                                continue
                    
                    if not prices: continue
                    
                    # The total price is usually the maximum value found in the row
                    total_price = max(prices)
                    
                    return {"name": name, "price": total_price, "url": link}

                except Exception:
                    continue
            
            return None

        except Exception as e:
            print(f"Scraping Error: {e}")
            time.sleep(5)
    
    return None

def manage_history(current_price):
    history = []
    
    # 1. Load existing history
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, "r") as f:
                history = json.load(f)
        except:
            history = []
            
    # 2. Add today's price
    today = datetime.now().strftime("%Y-%m-%d")
    history.append({"date": today, "price": current_price})
    
    # Keep only last 30 entries
    history = history[-30:]
    
    # 3. Calculate Stats
    prices = [entry["price"] for entry in history]
    avg_price = sum(prices) / len(prices)
    
    trend = "➖"
    if len(prices) > 1:
        if current_price < prices[-2]: trend = "⬇️ (Dropping)"
        elif current_price > prices[-2]: trend = "⬆️ (Rising)"
    
    # 4. Save back to file
    with open(HISTORY_FILE, "w") as f:
        json.dump(history, f)
        
    return avg_price, trend, len(history)

def post_to_discord(item, avg_price, trend, days_tracked):
    payload = {
        "username": "RAM Bot",
        "embeds": [
            {
                "title": "Daily RAM Deal (32GB DDR5 6000+ CL30)",
                "description": "Cheapest kit on PCPartPicker (CA).",
                "color": 5814783,
                "fields": [
                    {"name": "Product", "value": item["name"], "inline": False},
                    {"name": "Price Today", "value": f"**${item['price']:.2f}**", "inline": True},
                    {"name": "Trend", "value": f"{trend}", "inline": True},
                    {"name": "Stats", "value": f"Avg: ${avg_price:.2f} (over {days_tracked} days)", "inline": False}
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
        print(f"Found: {deal['name']} @ ${deal['price']}")
        avg, trend, count = manage_history(deal['price'])
        post_to_discord(deal, avg, trend, count)
    else:
        print("No deal found.")