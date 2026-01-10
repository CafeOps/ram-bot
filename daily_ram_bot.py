import requests
from bs4 import BeautifulSoup
import os
import sys
import time
import json
import re
from datetime import datetime

# Use the exact fragment-based URL (keep filters intact)
PCPP_URL_TEMPLATE = "https://ca.pcpartpicker.com/products/memory/#L=30,300&S=6000,9600&X=0,100522&Z=32768002&sort=price&page={page}"
HISTORY_FILE = "price_history.json"

# Minimal outputs only
MAX_DEBUG_PRINT_CHARS = 800

# Product filter: ensure we only post 32GB DDR5 kits
def is_target_kit(name: str) -> bool:
    if not name:
        return False
    n = name.upper()
    has_32 = bool(re.search(r'\b32\s*GB\b', n)) or '32GB' in n
    has_ddr5 = 'DDR5' in n
    return has_32 and has_ddr5

# Env
try:
    WEBHOOK_URL = os.environ["DISCORD_WEBHOOK"]
    SCRAPER_API_KEY = os.environ["SCRAPER_API_KEY"]
except KeyError as e:
    print(f"[FATAL] Missing environment variable: {e}")
    sys.exit(1)

def fetch_via_scraperapi(target_url, render=False, wait_for=0, scroll=False, scroll_delay=0, timeout=60):
    """
    Generic ScraperAPI fetch wrapper.
    """
    payload = {
        "api_key": SCRAPER_API_KEY,
        "url": target_url,
        "render": "true" if render else "false",
        "wait_for": str(wait_for) if render else "0",
        "scroll": "true" if scroll else "false",
        "scroll_delay": str(scroll_delay) if scroll else "0",
        "country_code": "ca",
        "device_type": "desktop", # Force desktop to ensure QAPI links generate correctly
    }
    try:
        r = requests.get("https://api.scraperapi.com/", params=payload, timeout=timeout)
        if r.status_code == 500:
            return r # Return 500 so caller can decide to retry
        r.raise_for_status()
        return r
    except Exception as e:
        print(f"[ERROR] ScraperAPI request failed for {target_url!r}: {e}")
        return None

def extract_qapi_endpoint(html_text):
    """
    Find a likely qapi endpoint in the page HTML.
    Returns a full path (starting with /qapi/...) if found, else None.
    """
    # Look for the full query string version first
    match = re.search(r'(["\'])(/qapi(?:/product(?:/category|/list)?)[^"\']*)\1', html_text)
    if match:
        return match.group(2)
    # Fallback: look for generic qapi path
    match2 = re.search(r'(/qapi/[^"\s\']{8,200})', html_text)
    if match2:
        return match2.group(1)
    return None

def parse_qapi_json_text(json_text):
    """
    Attempt to extract products from qapi JSON text.
    Returns a list of candidate dicts: {"name":..., "price":..., "url":...}
    """
    candidates = []
    try:
        data = json.loads(json_text)
    except Exception:
        data = None

    def scan_for_products(obj):
        results = []
        if isinstance(obj, dict):
            for k, v in obj.items():
                if isinstance(v, list):
                    if v and isinstance(v[0], dict) and any(k2 in v[0] for k2 in ("name", "product_name", "title", "part_name")):
                        results.extend(v)
                    else:
                        for item in v:
                            results.extend(scan_for_products(item))
                elif isinstance(v, dict):
                    results.extend(scan_for_products(v))
        elif isinstance(obj, list):
            for item in obj:
                results.extend(scan_for_products(item))
        return results

    products = []
    if data is not None:
        products = scan_for_products(data)

    for p in products:
        if not isinstance(p, dict): continue
        name = p.get("name") or p.get("product_name") or p.get("title") or p.get("part_name") or ""
        
        # Extract Price
        price_vals = []
        for key in ("price", "min_price", "price_cents", "price_display", "priceFormatted"):
            if key in p:
                try:
                    v = p[key]
                    if isinstance(v, (int, float)):
                        price_vals.append(float(v))
                    elif isinstance(v, str):
                        # Clean string prices
                        m = re.findall(r'[0-9,]+\.\d{2}', v)
                        for mm in m: price_vals.append(float(mm.replace(',', '')))
                except: pass
        
        # Fallback: regex search the raw JSON dump of this object
        if not price_vals:
            try:
                raw = json.dumps(p)
                m = re.findall(r'\$\s*([0-9,]+(?:\.\d{1,2})?)', raw)
                for mm in m: price_vals.append(float(mm.replace(',', '')))
            except: pass

        url = p.get("url") or p.get("product_url") or p.get("detail_url") or ""
        if url and url.startswith("/"):
            url = "https://ca.pcpartpicker.com" + url

        if name and price_vals:
            candidates.append({
                "name": name.strip(),
                "price": min(price_vals),
                "url": url
            })

    # Fallback Regex Scanning if JSON structure failed
    if not candidates:
        pattern = re.compile(r'"name"\s*:\s*"([^"]{3,200})"[\s\S]{0,200}?"price"\s*:\s*"?\$?([0-9,]+\.\d{2})"?', re.IGNORECASE)
        for m in pattern.finditer(json_text):
            try:
                nm = m.group(1)
                pr = float(m.group(2).replace(',', ''))
                candidates.append({"name": nm, "price": pr, "url": ""})
            except: pass

    return candidates

def get_cheapest_ram(max_retries=2, max_pages=3, wait_for_js=15000):
    all_candidates = []

    for page in range(1, max_pages + 1):
        page_url = PCPP_URL_TEMPLATE.format(page=page)
        print(f"[INFO] Fetching rendered PCPP page (page {page})...")
        r = fetch_via_scraperapi(page_url, render=True, wait_for=wait_for_js, scroll=True, scroll_delay=3000, timeout=120)
        
        if r is None or r.status_code != 200:
            print(f"[WARN] Rendered page fetch failed for page {page}")
            continue

        html = r.text
        qapi_path = extract_qapi_endpoint(html)
        
        if qapi_path:
            qapi_url = "https://ca.pcpartpicker.com" + qapi_path
            print(f"[INFO] QAPI FOUND: {qapi_url}")
            
            # 1. Try Direct Fetch (Fastest, cheapest)
            q = fetch_via_scraperapi(qapi_url, render=False, timeout=90)
            
            # 2. CRITICAL RETRY LOGIC: If Direct fails, use Render (Bypass IP Blocks)
            if not q or q.status_code != 200:
                print(f"[WARN] QAPI Direct Fetch failed (Code: {q.status_code if q else 'None'}). Retrying with Render...")
                q = fetch_via_scraperapi(qapi_url, render=True, wait_for=5000, timeout=120)

            if q and q.status_code == 200:
                candidates = parse_qapi_json_text(q.text)
                if candidates:
                    print(f"[INFO] QAPI parsed {len(candidates)} candidates")
                    for c in candidates:
                        if is_target_kit(c.get("name", "")):
                            all_candidates.append(c)
                    continue # Success! Skip HTML fallback for this page
                else:
                    print("[WARN] QAPI fetch succeeded but found no candidates.")
            else:
                print("[WARN] QAPI Retry also failed.")

        # Fallback HTML Parsing
        print("[INFO] Fallback to HTML parsing...")
        try:
            soup = BeautifulSoup(html, "html.parser")
            rows = soup.select("tr.tr__product")
            for item in rows:
                name_el = item.find("a")
                if not name_el: continue
                name = re.sub(r'\(\d+\)$', '', name_el.get_text(strip=True)).strip()
                if not is_target_kit(name): continue
                
                price_cell = item.select_one("td.td__price")
                if not price_cell: continue
                
                raw_text = price_cell.get_text(" ", strip=True)
                matches = re.findall(r'\$\s*([0-9,]+(?:\.\d{1,2})?)', raw_text)
                prices = [float(m.replace(',', '')) for m in matches]
                
                if prices:
                    link = "https://ca.pcpartpicker.com" + name_el.get("href", "")
                    all_candidates.append({"name": name, "price": min(prices), "url": link})
        except Exception as e:
            print(f"[ERROR] HTML parsing error: {e}")

    if not all_candidates:
        return None

    # Sort by Price
    keyed = {}
    for c in all_candidates:
        key = (c.get("name","").strip(), c.get("url",""))
        if not keyed.get(key) or c["price"] < keyed[key]["price"]:
            keyed[key] = c

    final = list(keyed.values())
    final.sort(key=lambda x: x["price"])

    print(f"[RESULT] Found {len(final)} items. Cheapest: ${final[0]['price']:.2f} - {final[0]['name']}")
    return final[0]

def manage_history(current_price):
    history = []
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, "r") as f: history = json.load(f)
        except: pass
            
    today = datetime.now().strftime("%Y-%m-%d")
    if not history or history[-1]["date"] != today:
        history.append({"date": today, "price": current_price})
    else:
        history[-1]["price"] = current_price
    
    history = history[-30:]
    with open(HISTORY_FILE, "w") as f: json.dump(history, f)
    
    prices = [e["price"] for e in history]
    avg = sum(prices) / len(prices) if prices else current_price
    
    trend = "➖"
    if len(prices) > 1:
        if current_price < prices[-2]: trend = "⬇️"
        elif current_price > prices[-2]: trend = "⬆️"
    return avg, trend, len(history)

def post_to_discord(item, avg_price, trend, days_tracked):
    payload = {
        "username": "RAM Bot",
        "embeds": [{
            "title": "Daily RAM Deal (32GB DDR5 6000+ CL30)",
            "description": "Cheapest kit on PCPartPicker (CA).",
            "color": 5814783,
            "fields": [
                {"name": "Product", "value": item["name"], "inline": False},
                {"name": "Price Today", "value": f"**${item['price']:.2f}**", "inline": True},
                {"name": "Trend", "value": trend, "inline": True},
                {"name": "Stats", "value": f"Avg: ${avg_price:.2f} (over {days_tracked} days)", "inline": False}
            ],
            "url": item.get("url", "")
        }]
    }
    requests.post(WEBHOOK_URL.strip(), json=payload, timeout=15)
    print("[INFO] Posted to Discord")

if __name__ == "__main__":
    print("[START] RAM Bot run")
    deal = get_cheapest_ram()
    if deal:
        avg, trend, count = manage_history(deal["price"])
        post_to_discord(deal, avg, trend, count)
    else:
        print("[END] No deal found")
