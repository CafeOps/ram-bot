import requests
from bs4 import BeautifulSoup
import os
import sys
import time
import json
import re
from datetime import datetime
from random import randint

PCPP_URL = "https://ca.pcpartpicker.com/products/memory/#L=30,300&S=6000,9600&X=0,100522&Z=32768002&sort=price&page=1"
HISTORY_FILE = "price_history.json"
EXPECTED_MIN_PRODUCTS = 56

try:
    WEBHOOK_URL = os.environ["DISCORD_WEBHOOK"]
    SCRAPER_API_KEY = os.environ["SCRAPER_API_KEY"]
except KeyError as e:
    print(f"Error: {e} environment variable not set.")
    sys.exit(1)

def get_cheapest_ram(max_retries=5):
    for attempt in range(max_retries):
        cache_buster = f"&_={int(time.time())}{randint(1000,9999)}"
        url_with_cache_buster = PCPP_URL + cache_buster
        
        wait_time = 5000 + (attempt * 2000)
        scroll_delay = 3000 + (attempt * 1000)
        
        payload = {
            "api_key": SCRAPER_API_KEY,
            "url": url_with_cache_buster,
            "render": "true",
            "scroll": "true",
            "scroll_delay": str(scroll_delay),
            "wait_for": str(wait_time),
            "country_code": "ca",
            "keep_headers": "true",
        }

        try:
            print(f"Attempt {attempt + 1}/{max_retries} - Wait: {wait_time}ms, Scroll: {scroll_delay}ms")
            response = requests.get("https://api.scraperapi.com/", params=payload, timeout=120)
            
            if response.status_code == 500:
                print("ScraperAPI 500 error, retrying...")
                time.sleep(5)
                continue
            
            response.raise_for_status()

            soup = BeautifulSoup(response.text, "html.parser")
            product_list = soup.select("tr.tr__product")
            
            print(f"Found {len(product_list)} products (expected {EXPECTED_MIN_PRODUCTS}+)")
            
            if len(product_list) < EXPECTED_MIN_PRODUCTS and attempt < max_retries - 1:
                print(f"⚠️  Incomplete load - only got {len(product_list)}/{EXPECTED_MIN_PRODUCTS}. Retrying with longer waits...")
                time.sleep(3)
                continue
            
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
            
            print(f"\n✓ Successfully scraped {len(candidates)} products")
            print(f"--- Top 10 Cheapest ---")
            for i, c in enumerate(candidates[:10], 1):
                print(f"#{i}: ${c['price']:.2f} - {c['name']}")
            print("----------------------------\n")

            return candidates[0]

        except Exception as e:
            print(f"Scraping Error: {e}")
            import traceback
            traceback.print_exc()
            time.sleep(5)
    
    print("❌ Failed to load all products after all retries")
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
