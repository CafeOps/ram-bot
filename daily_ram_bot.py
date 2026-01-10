import requests
from bs4 import BeautifulSoup
import os
import sys
import time
import json
import re
from datetime import datetime

# --- CONFIG ---
# URL: Provided by user (Newegg CA, Specific Filters, Sorted by Lowest Price)
NEWEGG_URL = "https://www.newegg.ca/p/pl?N=100007610%20601459359%20601424507%20601410928%20601410054%20601409314%20601409984%20601334734%20601407112%20601397651%20601397653%20601397951%20601275378%20500002048%20601413261&Order=1"
HISTORY_FILE = "price_history.json"
DEBUG_HTML_FILE = "newegg_debug.html"

# PRICE FLOOR: Avoids cables, fans, or "open box" junk if scraper gets confused
MIN_PRICE_CAD = 130.00 

try:
    WEBHOOK_URL = os.environ["DISCORD_WEBHOOK"]
    SCRAPER_API_KEY = os.environ["SCRAPER_API_KEY"]
except KeyError as e:
    print(f"Error: {e} environment variable not set.")
    sys.exit(1)

def get_cheapest_ram(max_retries=3):
    # Newegg is generally easier than PCPP, but we keep 'residential' for safety.
    payload = {
        "api_key": SCRAPER_API_KEY,
        "url": NEWEGG_URL,
        "country_code": "ca",
        "device_type": "desktop",
        "residential": "true" 
    }

    for attempt in range(max_retries):
        try:
            print(f"Contacting ScraperAPI (Newegg Target - Attempt {attempt + 1}/{max_retries})...")
            response = requests.get("https://api.scraperapi.com/", params=payload, timeout=60)
            
            if response.status_code != 200:
                print(f" > HTTP {response.status_code}. Retrying...")
                time.sleep(5)
                continue
            
            # Save debug HTML just in case
            with open(DEBUG_HTML_FILE, "w", encoding="utf-8") as f:
                f.write(response.text)
            print(f" > Saved debug HTML to {DEBUG_HTML_FILE}")

            soup = BeautifulSoup(response.text, "html.parser")
            
            # Newegg stores products in "div.item-cell"
            items = soup.select("div.item-cell")
            print(f"DEBUG: Found {len(items)} items on page.")
            
            if not items:
                print("No items found. Retrying...")
                continue

            candidates = []
            
            for item in items:
                try:
                    # 1. Get Name
                    title_tag = item.select_one("a.item-title")
                    if not title_tag: continue
                    
                    name = title_tag.get_text(strip=True)
                    link = title_tag['href']
                    
                    # 2. Get Price
                    # Newegg structure: <li class="price-current"> <strong>479</strong> <sup>.99</sup> </li>
                    price_wrap = item.select_one(".price-current")
                    if not price_wrap: continue

                    # Remove "Save: 10%" text or other hidden junk
                    for junk in price_wrap.select(".price-note, .price-was"):
                        junk.decompose()

                    # Extract the raw numbers from strong/sup tags
                    strong = price_wrap.find("strong")
                    sup = price_wrap.find("sup")
                    
                    if strong and sup:
                        price_str = f"{strong.get_text(strip=True)}{sup.get_text(strip=True)}"
                    else:
                        # Fallback regex if structure changes
                        price_str = price_wrap.get_text(strip=True)
                    
                    # Clean string "$ 479 .99" -> "479.99"
                    price_val = float(re.sub(r"[^\d.]", "", price_str))
                    
                    # Filter out junk/shipping costs
                    if price_val < MIN_PRICE_CAD: 
                        continue

                    candidates.append({
                        "name": name,
                        "price": price_val,
                        "url": link
                    })

                except Exception:
                    continue
            
            if not candidates:
                print("No valid candidates found.")
                return None
                
            # Sort strictly by price
            candidates.sort(key=lambda x: x['price'])
            
            print(f"--- Top 5 Candidates (Newegg) ---")
            for i, c in enumerate(candidates[:5], 1):
                print(f"#{i}: ${c['price']:.2f} - {c['name'][:40]}...")
            print("-----------------------------------")
            
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
                "title": "Daily RAM Deal (Newegg CA)",
                "description": "Cheapest 32GB DDR5 kit found.",
                "color": 16750848, # Newegg Orange
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
    print("Starting Bot (Target: Newegg Canada)...")
    deal = get_cheapest_ram()

    if deal:
        print(f"Found: {deal['name']} @ ${deal['price']:.2f}")
        avg, trend, count = manage_history(deal['price'])
        post_to_discord(deal, avg, trend, count)
    else:
        print("No deal found.")
