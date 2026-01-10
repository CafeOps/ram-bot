import requests
from bs4 import BeautifulSoup
import os
import sys
import time
import json
import re
from datetime import datetime

# Config
BASE_URL = "https://ca.pcpartpicker.com/products/memory/"
# keep the same PCPartPicker filters as you had in the fragment
FRAGMENT = "L=30,300&S=6000,9600&X=0,100522&Z=32768002&sort=price"
HISTORY_FILE = "price_history.json"
SEARCH_STRING = "Patriot Viper Elite"  # the product string we want to detect

try:
    WEBHOOK_URL = os.environ["DISCORD_WEBHOOK"]
    SCRAPER_API_KEY = os.environ["SCRAPER_API_KEY"]
except KeyError as e:
    print(f"Error: {e} environment variable not set.")
    sys.exit(1)


def fetch_product_detail_page(relative_href):
    """
    Fetch a PCPP product detail page and save it to disk for inspection.
    """
    target = "https://ca.pcpartpicker.com" + relative_href + "?_=" + str(int(time.time()))
    payload = {
        "api_key": SCRAPER_API_KEY,
        "url": target,
        "render": "true",
        "wait_for": "3000",
        "country_code": "ca",
    }
    try:
        r = requests.get("https://api.scraperapi.com/", params=payload, timeout=90)
        r.raise_for_status()
        safe_name = relative_href.strip("/").replace("/", "_")
        fname = f"detail_{safe_name}.html"
        with open(fname, "w", encoding="utf-8") as f:
            f.write(r.text)
        print(f"DIAG: wrote detail page to {fname}")
        return r.text
    except Exception as e:
        print(f"DIAG: error fetching detail page {relative_href}: {e}")
        return None


def get_cheapest_ram(max_retries=3, max_pages=3):
    """
    Robust scraping:
    - pages through up to max_pages
    - cache-busts the target URL
    - extracts all $ amounts by regex and chooses the min
    - dumps combined HTML to debug_page.html for offline inspection
    - if SEARCH_STRING not found, fetches per-product detail pages and writes them to disk
    """
    candidates = []
    seen_hrefs = set()
    combined_html = ""
    found_search = False

    for page in range(1, max_pages + 1):
        full_target = f"{BASE_URL}?page={page}&{FRAGMENT}&_={int(time.time())}"
        payload = {
            "api_key": SCRAPER_API_KEY,
            "url": full_target,
            "render": "true",
            "scroll": "true",
            "scroll_delay": "3000",
            "wait_for": "5000",
            "country_code": "ca",
            # "device_type": "desktop"  # can add if needed
        }

        for attempt in range(max_retries):
            try:
                print(f"Contacting ScraperAPI page {page} (attempt {attempt + 1}/{max_retries})...")
                response = requests.get("https://api.scraperapi.com/", params=payload, timeout=120)

                if response.status_code == 500:
                    print("ScraperAPI 500 error, retrying...")
                    time.sleep(5)
                    continue

                response.raise_for_status()
                response_text = response.text
                combined_html += response_text

                # Quick presence test for the missing product on this page
                if SEARCH_STRING in response_text:
                    print(f"DIAG: FOUND product string '{SEARCH_STRING}' on page {page}")
                    found_search = True
                else:
                    print(f"DIAG: product string '{SEARCH_STRING}' not on page {page}")

                soup = BeautifulSoup(response_text, "html.parser")
                product_list = soup.select("tr.tr__product")

                print(f"DEBUG: page {page} - Found {len(product_list)} products")

                if not product_list:
                    # No products on this page; break out of page loop
                    break

                for i, item in enumerate(product_list):
                    try:
                        name_element = item.find("a")
                        if not name_element:
                            continue

                        raw_name = name_element.get_text(strip=True)
                        name = re.sub(r'\(\d+\)$', '', raw_name).strip()
                        href = name_element.get("href", "")
                        if href:
                            seen_hrefs.add(href)

                        link = "https://ca.pcpartpicker.com" + href

                        price_cell = item.select_one("td.td__price")
                        if not price_cell:
                            # Log for diagnostics
                            print(f"DEBUG SKIP: no price cell for '{name}'")
                            continue

                        raw_text = price_cell.get_text(" ", strip=True)
                        # Extract all dollar amounts via regex
                        matches = re.findall(r'\$\s*[0-9,]+(?:\.\d{1,2})?', raw_text)
                        prices = []
                        for m in matches:
                            try:
                                p = float(m.replace('$', '').replace(',', '').strip())
                                if p > 10:
                                    prices.append(p)
                            except Exception:
                                continue

                        # Fallback: numbers like 479.99 without $ sign
                        if not prices:
                            nums = re.findall(r'[0-9,]+\.\d{2}', raw_text)
                            for n in nums:
                                try:
                                    p = float(n.replace(',', ''))
                                    if p > 10:
                                        prices.append(p)
                                except:
                                    pass

                        if not prices:
                            print(f"DEBUG SKIP: could not parse prices for '{name}' (raw: {raw_text[:120]})")
                            continue

                        total_price = min(prices)

                        candidates.append({
                            "name": name,
                            "price": total_price,
                            "url": link,
                            "raw_price_cell": raw_text
                        })

                    except Exception as e:
                        print(f"Item parse error (ignored): {e}")
                        continue

                # success for this page -> break retry loop
                break

            except Exception as e:
                print(f"Scraping Error page {page}: {e}")
                import traceback
                traceback.print_exc()
                time.sleep(5)
                continue

        # continue to next page

    # Save combined HTML for offline inspection
    try:
        with open("debug_page.html", "w", encoding="utf-8") as f:
            f.write(combined_html)
        print("DIAG: Combined raw HTML saved to debug_page.html")
    except Exception as e:
        print(f"DIAG: error saving debug HTML: {e}")

    # Final presence check across combined HTML
    if SEARCH_STRING in combined_html:
        print(f"DIAG: FOUND product string '{SEARCH_STRING}' in combined HTML")
    else:
        print(f"DIAG: MISSING product string '{SEARCH_STRING}' in combined HTML - proceeding to fetch detail pages for inspection")
        # fetch detail pages for all seen product hrefs (this can produce multiple files)
        for href in list(seen_hrefs)[:50]:  # limit to first 50 to avoid too many calls
            fetch_product_detail_page(href)

    if not candidates:
        print("No valid candidates found.")
        return None

    candidates.sort(key=lambda x: x['price'])

    print(f"--- Top 10 Cheapest (from {len(candidates)} total) ---")
    for i, c in enumerate(candidates[:10], 1):
        print(f"#{i}: ${c['price']:.2f} - {c['name']} (raw: {c['raw_price_cell'][:80]}...)")
    print("----------------------------\n")

    return candidates[0]


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
        if current_price < prev_price:
            trend = "⬇️"
        elif current_price > prev_price:
            trend = "⬆️"

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
