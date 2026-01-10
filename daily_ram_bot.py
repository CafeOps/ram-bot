import requests
from bs4 import BeautifulSoup
import os
import sys
import time
import json
import re
from datetime import datetime

# --- CONFIG ---
# TIMESTAMP ensures we don't get a cached search page
TIMESTAMP = int(time.time())
PCPP_SEARCH_URL = f"https://ca.pcpartpicker.com/products/memory/#L=30,300&S=6000,9600&X=0,100522&Z=32768002&sort=price&page=1&_t={TIMESTAMP}"
HISTORY_FILE = "price_history.json"

try:
    WEBHOOK_URL = os.environ["DISCORD_WEBHOOK"]
    SCRAPER_API_KEY = os.environ["SCRAPER_API_KEY"]
except KeyError as e:
    print(f"Error: {e} environment variable not set.")
    sys.exit(1)

def get_scraper_response(url):
    """
    Helper to fetch any URL via ScraperAPI with retries.
    """
    payload = {
        "api_key": SCRAPER_API_KEY,
        "url": url,
        "render": "true",       # Essential for JS
        "wait_for": "5000",     # 5s is usually enough for data to hydrate
        "country_code": "ca",
        "device_type": "desktop",
    }
    
    for attempt in range(3):
        try:
            print(f"Fetching {url[:60]}... (Attempt {attempt+1})")
            r = requests.get("https://api.scraperapi.com/", params=payload, timeout=60)
            if r.status_code == 200:
                return r
            elif r.status_code == 500:
                print(" > ScraperAPI 500. Retrying...")
                time.sleep(5)
                continue
            else:
                print(f" > HTTP {r.status_code}")
        except Exception as e:
            print(f" > Error: {e}")
            time.sleep(5)
    return None

def get_top_candidate():
    """
    Step 1: Get the #1 result URL from the search page.
    We TRUST PCPartPicker has sorted by price (ascending).
    We DO NOT parse the price here to avoid 'Save $100' errors.
    """
    response = get_scraper_response(PCPP_SEARCH_URL)
    if not response: return None
    
    soup = BeautifulSoup(response.text, "html.parser")
    # Select the first product row
    first_row = soup.select_one("tr.tr__product")
    if not first_row: 
        print("Error: No product rows found in search results.")
        return None
    
    name_el = first_row.find("a")
    if not name_el: return None
    
    # Clean name
    raw_name = name_el.get_text(strip=True)
    name = re.sub(r'\(\d+\)$', '', raw_name).strip()
    
    # Construct absolute URL
    link = "https://ca.pcpartpicker.com" + name_el["href"]
    
    print(f"Search Result #1: {name}")
    print(f"Link: {link}")
    
    return {"name": name, "url": link}

def get_verified_price(product_url):
    """
    Step 2: Visit the product page and read the JSON-LD.
    This bypasses all visual formatting noise.
    """
    response = get_scraper_response(product_url)
    if not response: return None
    
    soup = BeautifulSoup(response.text, "html.parser")
    
    # Strategy A: JSON-LD (Standard for Google Shopping)
    scripts = soup.find_all("script", type="application/ld+json")
    for s in scripts:
        try:
            data = json.loads(s.string)
            # We look for the "Product" schema
            if "@type" in data and data["@type"] == "Product":
                if "offers" in data:
                    offer = data["offers"]
                    
                    # 'offers' can be a list or a single object
                    if isinstance(offer, list):
                        # Find the lowest price in the list of offers
                        prices = []
                        for o in offer:
                            if "price" in o:
                                prices.append(float(o["price"]))
                        if prices: 
                            found = min(prices)
                            print(f"JSON-LD Verified Price: ${found}")
                            return found
                            
                    elif isinstance(offer, dict):
                        if "price" in offer:
                            found = float(offer["price"])
                            print(f"JSON-LD Verified Price: ${found}")
                            return found
        except:
            continue
            
    # Strategy B: OpenGraph/Meta Tags (Backup)
    # <meta property="product:price:amount" content="479.99" />
    meta_price = soup.find("meta", property="product:price:amount")
    if meta_price and meta_price.get("content"):
        try:
            found = float(meta_price["content"])
            print(f"Meta-Tag Verified Price: ${found}")
            return found
        except:
            pass
            
    print("Error: Could not extract structured price from product page.")
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

def post_to_discord(item, price, avg_price, trend, days_tracked):
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
                        "value": f"**${price:.2f}**", 
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
    print("Starting Bot (Two-Step Verification Mode)...")
    
    # Step 1: Find the winner
    candidate = get_top_candidate()
    
    if candidate:
        # Step 2: Verify the price
        real_price = get_verified_price(candidate["url"])
        
        if real_price:
            print(f"Final Result: {candidate['name']} @ ${real_price:.2f}")
            avg, trend, count = manage_history(real_price)
            post_to_discord(candidate, real_price, avg, trend, count)
        else:
            print("Failed to verify price on product page.")
    else:
        print("No candidates found in search.")
