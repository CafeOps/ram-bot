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

# 1. PCPartPicker URL
PCPP_URL = f"https://ca.pcpartpicker.com/products/memory/#L=30,300&S=6000,9600&X=0,100522&Z=32768002&sort=price&page=1&_t={TIMESTAMP}"

# 2. Newegg URL 
NEWEGG_URL = "https://www.newegg.ca/p/pl?N=100007610%20601459359%20601424507%20601410928%20601410054%20601409314%20601409984%20601334734%20601407112%20601397651%20601397653%20601397951%20601275378%20500002048%20601413261&Order=1"

HISTORY_FILE = "price_history.json"
DEBUG_PCPP_FILE = "debug_pcpp.html"
DEBUG_NEWEGG_FILE = "debug_newegg.html"

# PRICE FLOOR: Safety net to ignore cables/accessories
MIN_PRICE_CAD = 120.00 

try:
    WEBHOOK_URL = os.environ["DISCORD_WEBHOOK"]
    SCRAPER_API_KEY = os.environ["SCRAPER_API_KEY"]
except KeyError as e:
    print(f"Error: {e} environment variable not set.")
    sys.exit(1)

def scrape_pcpartpicker(max_retries=2):
    """Attempts to scrape PCPartPicker using Residential IPs."""
    print(f"\n--- Checking PCPartPicker ---")
    
    payload = {
        "api_key": SCRAPER_API_KEY,
        "url": PCPP_URL,
        "render": "true",
        "wait_for": "20000",
        "country_code": "ca",
        "device_type": "desktop",
        "residential": "true"  # Crucial for PCPP
    }

    for attempt in range(max_retries):
        try:
            print(f" > Attempt {attempt+1}/{max_retries}...")
            response = requests.get("https://api.scraperapi.com/", params=payload, timeout=90)
            
            if response.status_code != 200:
                print(f" > HTTP {response.status_code} (Failed)")
                continue

            # Save debug file
            with open(DEBUG_PCPP_FILE, "w", encoding="utf-8") as f:
                f.write(response.text)
            
            soup = BeautifulSoup(response.text, "html.parser")
            rows = soup.select("tr.tr__product")
            
            if not rows:
                print(" > No products found (PCPP likely blocking).")
                continue

            candidates = []
            for row in rows:
                try:
                    name_tag = row.find("a")
                    if not name_tag: continue
                    name = re.sub(r'\(\d+\)$', '', name_tag.get_text(strip=True)).strip()
                    link = "https://ca.pcpartpicker.com" + name_tag["href"]
                    
                    # Price extraction
                    price_cell = row.select_one("td.td__price")
                    if not price_cell: continue
                    
                    raw_text = price_cell.get_text(strip=True)
                    matches = re.findall(r"(\d{1,3}(?:,\d{3})*(?:\.\d{2})?)", raw_text)
                    
                    valid_vals = []
                    for m in matches:
                        v = float(m.replace(',', ''))
                        if v >= MIN_PRICE_CAD: valid_vals.append(v)
                    
                    if valid_vals:
                        candidates.append({"name": name, "price": min(valid_vals), "url": link, "source": "PCPP"})
                except:
                    continue
            
            if candidates:
                print(f" > Found {len(candidates)} items on PCPP.")
                return candidates
            
        except Exception as e:
            print(f" > Error: {e}")
            time.sleep(2)
            
    return []

def scrape_newegg(max_retries=2):
    """Attempts to scrape Newegg using Residential IPs."""
    print(f"\n--- Checking Newegg CA ---")
    
    payload = {
        "api_key": SCRAPER_API_KEY,
        "url": NEWEGG_URL,
        "country_code": "ca",
        "device_type": "desktop",
        "residential": "true"
    }

    for attempt in range(max_retries):
        try:
            print(f" > Attempt {attempt+1}/{max_retries}...")
            response = requests.get("https://api.scraperapi.com/", params=payload, timeout=90)
            
            if response.status_code != 200:
                print(f" > HTTP {response.status_code} (Failed)")
                continue

            with open(DEBUG_NEWEGG_FILE, "w", encoding="utf-8") as f:
                f.write(response.text)
            
            soup = BeautifulSoup(response.text, "html.parser")
            items = soup.select("div.item-cell")
            
            if not items:
                print(" > No items found on Newegg.")
                continue

            candidates = []
            for item in items:
                try:
                    title_tag = item.select_one("a.item-title")
                    if not title_tag: continue
                    name = title_tag.get_text(strip=True)
                    link = title_tag['href']
                    
                    price_wrap = item.select_one(".price-current")
                    if not price_wrap: continue
                    
                    # Clean hidden text
                    for junk in price_wrap.select(".price-note, .price-was"):
                        junk.decompose()
                        
                    strong = price_wrap.find("strong")
                    sup = price_wrap.find("sup")
                    if strong and sup:
                        p_str = f"{strong.get_text(strip=True)}{sup.get_text(strip=True)}"
                    else:
                        p_str = price_wrap.get_text(strip=True)
                        
                    val = float(re.sub(r"[^\d.]", "", p_str))
                    
                    if val >= MIN_PRICE_CAD:
                        candidates.append({"name": name, "price": val, "url": link, "source": "Newegg"})
                except:
                    continue
            
            if candidates:
                print(f" > Found {len(candidates)} items on Newegg.")
                return candidates

        except Exception as e:
            print(f" > Error: {e}")
            time.sleep(2)

    return []

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
    color = 5814783 if item['source'] == "PCPP" else 16750848 # PCPP Blue vs Newegg Orange
    
    payload = {
        "username": "RAM Bot",
        "embeds": [
            {
                "title": f"Daily RAM Deal ({item['source']})",
                "description": "Good morning. This is currently the cheapest 2x16GB 6000+ MHz CL30 or faster kit I could find.",
                "color": color,
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
    print("Starting Multi-Source RAM Bot...")
    
    # 1. Gather all candidates from both sources
    pcpp_deals = scrape_pcpartpicker()
    newegg_deals = scrape_newegg()
    
    all_deals = pcpp_deals + newegg_deals
    
    if all_deals:
        # 2. Sort by price (Lowest First)
        all_deals.sort(key=lambda x: x['price'])
        winner = all_deals[0]
        
        print(f"\nWINNER: {winner['name']} @ ${winner['price']:.2f} (Source: {winner['source']})")
        
        # 3. Post
        avg, trend, count = manage_history(winner['price'])
        post_to_discord(winner, avg, trend, count)
    else:
        print("\nNo valid deals found from any source.")
