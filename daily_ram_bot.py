import requests
from bs4 import BeautifulSoup
import os
import sys
import time
import json
import re
from datetime import datetime

# --- CONFIG ---
TIMESTAMP = int(time.time())
PCPP_URL = f"https://ca.pcpartpicker.com/products/memory/#L=30,300&S=6000,9600&X=0,100522&Z=32768002&sort=price&page=1&_t={TIMESTAMP}"
HISTORY_FILE = "price_history.json"
DEBUG_HTML_FILE = "residential_debug.html"

# PRICE FLOOR: Filters out "Save $100" or "$10 Rebate" text.
MIN_PRICE_CAD = 120.00 

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
        "wait_for": "20000",       # 20s Wait for hydration
        "country_code": "ca",
        "device_type": "desktop",
        "premium": "true"          # <--- THE FIX: FORCE RESIDENTIAL IP (Cost: ~25 credits)
    }

    for attempt in range(max_retries):
        try:
            print(f"Contacting ScraperAPI (Premium Residential Attempt {attempt + 1}/{max_retries})...")
            response = requests.get("https://api.scraperapi.com/", params=payload, timeout=60)
            
            if response.status_code != 200:
                print(f" > HTTP {response.status_code}. Retrying...")
                time.sleep(5)
                continue
            
            # --- CRITICAL: SAVE EVIDENCE ---
            # If this run fails, this file proves WHY.
            with open(DEBUG_HTML_FILE, "w", encoding="utf-8") as f:
                f.write(response.text)
            print(f" > Saved debug HTML to {DEBUG_HTML_FILE} ({len(response.text)} bytes)")
            # -------------------------------

            soup = BeautifulSoup(response.text, "html.parser")
            product_list = soup.select("tr.tr__product")
            
            print(f"DEBUG: Found {len(product_list)} total products (Goal: ~60)")
            
            if not product_list:
                print("No products found. Retrying...")
                time.sleep(5)
                continue

            candidates = []
            
            for item in product_list:
                try:
                    # 1. Get Name
                    name_element = item.find("a")
                    if not name_element: continue

                    raw_name = name_element.get_text(strip=True)
                    name = re.sub(r'\(\d+\)$', '', raw_name).strip()
                    link = "https://ca.pcpartpicker.com" + name_element["href"]
                    
                    # 2. Get Price (STRICT PARSING)
                    price_cell = item.select_one("td.td__price")
                    if not price_cell: continue
                    
                    price_link = price_cell.find("a")
                    if price_link:
                        raw_text = price_link.get_text(strip=True)
                    else:
                        raw_text = price_cell.get_text(strip=True)

                    matches = re.findall(r"(\d{1,3}(?:,\d{3})*(?:\.\d{2})?)", raw_text)
                    
                    valid_prices = []
                    for m in matches:
                        try:
                            val = float(m.replace(',', ''))
                            if val >= MIN_PRICE_CAD:
                                valid_prices.append(val)
                        except:
                            continue

                    if not valid_prices: continue
                    
                    final_price = min(valid_prices)
                    
                    candidates.append({
                        "name": name, 
                        "price": final_price, 
                        "url": link
                    })

                except Exception:
                    continue
            
            if not candidates:
                print("No valid candidates after filtering.")
                return None
            
            candidates.sort(key=lambda x: x['price'])
            
            print(f"--- Top 5 Candidates (Premium Run) ---")
            for i, c in enumerate(candidates[:5], 1):
                print(f"#{i}: ${c['price']:.2f} - {c['name']}")
            print("--------------------------------------\n")

            return candidates[0]

        except Exception as e:
            print(f"Scraping Error: {e}")
            time.sleep(5)
    
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
                    {
                        "name": "Product", 
                        "value": f"[{item['name']}]({item['url']})", 
                        "inline": False
                    },
                    {
                        "name": "Price Today", 
                        "value": f"**${item['price']:.2f}**", 
                        "inline": True
                    },
                    {
                        "name": "Trend", 
                        "value": f"{trend}", 
                        "inline": True
                    },
                    {
                        "name": "Stats", 
                        "value": f"Avg: ${avg_price:.2f} (over {days_tracked} days)", 
                        "inline": False
                    }
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
    print("Starting Bot (OPTION A: PREMIUM RESIDENTIAL MODE)...")
    deal = get_cheapest_ram()

    if deal:
        print(f"Found: {deal['name']} @ ${deal['price']:.2f}")
        avg, trend, count = manage_history(deal['price'])
        post_to_discord(deal, avg, trend, count)
    else:
        print("No deal found.")
