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
# Using the Search Page URL.
# We append timestamp to force a fresh render (ChatGPT Tip #1)
PCPP_URL = f"https://ca.pcpartpicker.com/products/memory/#L=30,300&S=6000,9600&X=0,100522&Z=32768002&sort=price&page=1&_t={TIMESTAMP}"
HISTORY_FILE = "price_history.json"

# PRICE FLOOR (ChatGPT Tip #9 Fix)
# Any number below $120 is treated as "Savings text" or "Rebate text" and ignored.
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
        "wait_for": "20000",    # INCREASED to 20s (Perplexity Tip #1)
        "country_code": "ca",
        "device_type": "desktop",
    }

    for attempt in range(max_retries):
        try:
            print(f"Contacting ScraperAPI (attempt {attempt + 1}/{max_retries})...")
            response = requests.get("https://api.scraperapi.com/", params=payload, timeout=60)
            
            if response.status_code != 200:
                print(f" > HTTP {response.status_code}. Retrying...")
                time.sleep(5)
                continue
            
            soup = BeautifulSoup(response.text, "html.parser")
            product_list = soup.select("tr.tr__product")
            
            print(f"DEBUG: Found {len(product_list)} total products")
            
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
                    # We grab the text from the Price Cell.
                    price_cell = item.select_one("td.td__price")
                    if not price_cell: continue
                    
                    # We prefer the text inside the <a> tag (the actual price link)
                    # over the general cell text (which contains "Save $XX")
                    price_link = price_cell.find("a")
                    if price_link:
                        raw_text = price_link.get_text(strip=True)
                    else:
                        raw_text = price_cell.get_text(strip=True)

                    # Regex to find all price-like numbers
                    matches = re.findall(r"(\d{1,3}(?:,\d{3})*(?:\.\d{2})?)", raw_text)
                    
                    valid_prices = []
                    for m in matches:
                        try:
                            val = float(m.replace(',', ''))
                            # THE FILTER: Ignore "Save $100" or "$10 Rebate"
                            if val >= MIN_PRICE_CAD:
                                valid_prices.append(val)
                        except:
                            continue

                    if not valid_prices: continue
                    
                    # Take the lowest VALID price found in this row
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
            
            # Sort by price
            candidates.sort(key=lambda x: x['price'])
            
            print(f"--- Top 5 Candidates ---")
            for i, c in enumerate(candidates[:5], 1):
                print(f"#{i}: ${c['price']:.2f} - {c['name']}")
            print("------------------------\n")

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
    print("Starting Bot (Creative Fix Mode)...")
    deal = get_cheapest_ram()

    if deal:
        print(f"Found: {deal['name']} @ ${deal['price']:.2f}")
        avg, trend, count = manage_history(deal['price'])
        post_to_discord(deal, avg, trend, count)
    else:
        print("No deal found.")
