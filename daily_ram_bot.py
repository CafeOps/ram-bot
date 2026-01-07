import requests
from bs4 import BeautifulSoup
import os
import sys
import time
import json
import re
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

            candidates = []
            
            for i, item in enumerate(product_list):
                try:
                    name_element = item.find("a")
                    if not name_element: continue

                    # Clean Name: Remove the "(16)" rating counts using Regex
                    raw_name = name_element.get_text(strip=True)
                    # Removes anything looking like (123) at the end of the string
                    name = re.sub(r'\(\d+\)$', '', raw_name).strip()
                    
                    link = "https://ca.pcpartpicker.com" + name_element["href"]
                    
                    # Find Price: Grab all dollar amounts, ignore "Price/GB" (usually small)
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
                    
                    # Use max() to get the Total Price (avoids Price/GB), 
                    # but logic below sorts candidates to find the true cheapest kit.
                    total_price = max(prices)
                    
                    candidates.append({"name": name, "price": total_price, "url": link})

                except Exception:
                    continue
            
            if not candidates:
                return None
            
            # --- THE FIX ---
            # PCPartPicker sometimes puts expensive "Featured" items at the top.
            # We explicitly SORT the list by price to find the real cheapest item.
            candidates.sort(key=lambda x: x['price'])
            
            # Debug: Show the top 3 after sorting
            print("\n--- Top 3 Cheapest Found ---")
            for c in candidates[:3]:
                print(f"${c['price']}: {c['name']}")
            print("----------------------------\n")

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
    
    # Avoid duplicate entries for the same day
    if not history or history[-1]["date"] != today:
        history.append({"date": today, "price": current_price})
    else:
        # Update today's price if it changed
        history[-1]["price"] = current_price
    
    history = history[-30:]
    
    prices = [entry["price"] for entry in history]
    avg_price = sum(prices) / len(prices)
    
    trend = "➖"
    if len(prices) > 1:
        # Compare against the PREVIOUS day (index -2)
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
        print(f"Found: {deal['name']} @ ${deal['price']}")
        avg, trend, count = manage_history(deal['price'])
        post_to_discord(deal, avg, trend, count)
    else:
        print("No deal found.")