import requests
from bs4 import BeautifulSoup
import os
import sys
import time
import json
import re
from datetime import datetime

PCPP_URL = "https://ca.pcpartpicker.com/products/memory/#L=30,300&S=6000,9600&X=0,100522&Z=32768002&sort=price&page=1"
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
        "scroll": "true",
        "scroll_delay": "3000",
        "wait_for": "5000",
        "country_code": "ca",
    }

    for attempt in range(max_retries):
        try:
            print(f"Contacting ScraperAPI (attempt {attempt + 1}/{max_retries})...")
            response = requests.get("https://api.scraperapi.com/", params=payload, timeout=120)
            
            if response.status_code == 500:
                print("ScraperAPI 500 error, retrying...")
                time.sleep(10)
                continue
            
            response.raise_for_status()

            soup = BeautifulSoup(response.text, "html.parser")
            product_list = soup.select("tr.tr__product")
            
            print(f"DEBUG: Found {len(product_list)} total products\n")
            
            if not product_list:
                print("No products found.")
                time.sleep(5)
                continue

            candidates = []
            
            for i, item in enumerate(product_list):
                try:
                    name_element = item.find("a")
                    if not name_element: 
                        continue

                    raw_name = name_element.get_text(strip=True)
                    name = re.sub(r'\(\d+\)$', '', raw_name).strip()
                    
                    link = "https://ca.pcpartpicker.com" + name_element["href"]
                    
                    price_cell = item.select_one("td.td__price")
                    if not price_cell:
                        continue
                    
                    prices = []
                    for text in price_cell.stripped_strings:
                        if "$" in text and "Price" not in text and "/" not in text:
                            try:
                                clean_price = float(text.replace('$', '').replace(',', '').replace('+', ''))
                                if clean_price > 50:
                                    prices.append(clean_price)
                            except ValueError:
                                continue
                    
                    if not prices: 
                        continue
                    
                    total_price = min(prices)
                    
                    candidates.append({
                        "name": name, 
                        "price": total_price, 
                        "url": link
                    })

                except Exception as e:
                    continue
            
            if not candidates:
                print("No valid candidates found.")
                return None
            
            candidates.sort(key=lambda x: x['price'])
            
            print(f"--- Top 10 Cheapest (from {len(candidates)} total) ---")
            for i, c in enumerate(candidates[:10], 1):
                print(f"#{i}: ${c['price']:.2f} - {c['name']}")
            print("----------------------------\n")

            return candidates[0]

        except Exception as e:
            print(f"Scraping Error: {e}")
            import traceback
            traceback.print_exc()
            time.sleep(10)
    
    return None

def manage_history(current_price):
    history = []
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, "r") as f:
                history = json.load(f)
        except:
            history = []
            
    today = datetime.now().strftime("%Y-%m-%d")
    
    if not history or history[-1]["date"] != today:
        history.append({"date": today, "price": current_price})
    else:
        history[-1]["price"] = current_price
    
    history = history[-30:]
    
    prices = [entry["price"] for entry in history]
    avg_price = sum(prices) / len(prices)
    
    trend = "➖"
    if len(prices) > 1:
        prev_price = prices[-2]
        if current_price < prev_price: trend = "⬇️"
        elif current_price > prev_price: trend = "⬆️"
    
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
        print(f"Found: {deal['name']} @ ${deal['price']:.2f}")
        avg, trend, count = manage_history(deal['price'])
        post_to_discord(deal, avg, trend, count)
    else:
        print("No deal found.")
