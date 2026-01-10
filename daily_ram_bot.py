import requests
from bs4 import BeautifulSoup
import os
import sys
import time
import json
import re
from datetime import datetime

# Use the exact fragment-based URL you provided earlier (keep filters intact)
PCPP_URL_TEMPLATE = "https://ca.pcpartpicker.com/products/memory/#L=30,300&S=6000,9600&X=0,100522&Z=32768002&sort=price&page={page}"
HISTORY_FILE = "price_history.json"

# Minimal outputs only (avoid large HTML artifacts)
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
    }
    try:
        r = requests.get("https://api.scraperapi.com/", params=payload, timeout=timeout)
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
    # Common pattern observed: URLs like /qapi/product/category/... or /qapi/product/list/...
    # We'll do a regex for "/qapi/...product...category" or "/qapi/product"
    match = re.search(r'(["\'])(/qapi(?:/product(?:/category|/list)?)[^"\']*)\1', html_text)
    if match:
        return match.group(2)
    # Another fallback: look for '/qapi/' anywhere in text and return a short path
    match2 = re.search(r'(/qapi/[^"\s\']{8,200})', html_text)
    if match2:
        return match2.group(1)
    return None


def parse_qapi_json_text(json_text):
    """
    Attempt to extract products from qapi JSON text. This is defensive:
    - Try json.loads
    - If that fails, use regex heuristics to find product objects with names/prices
    Returns a list of candidate dicts: {"name":..., "price":..., "url":...}
    """
    candidates = []

    # Try full JSON parse
    try:
        data = json.loads(json_text)
    except Exception:
        data = None

    def scan_for_products(obj):
        results = []
        if isinstance(obj, dict):
            # Common shapes: {'products': [...]}, {'results': {...'products': [...]}}
            for k, v in obj.items():
                if isinstance(v, list):
                    # if this list contains dicts with 'name' or 'product_name', treat as product list
                    if v and isinstance(v[0], dict) and any(k2 in v[0] for k2 in ("name", "product_name", "title", "part_name")):
                        results.extend(v)
                    else:
                        # scan deeper
                        for item in v:
                            results.extend(scan_for_products(item))
                elif isinstance(v, dict):
                    results.extend(scan_for_products(v))
            return results
        elif isinstance(obj, list):
            res = []
            for item in obj:
                res.extend(scan_for_products(item))
            return res
        else:
            return []

    products = []
    if data is not None:
        products = scan_for_products(data)

    # If we found some dicts that look like products, extract name & price
    for p in products:
        if not isinstance(p, dict):
            continue
        name = p.get("name") or p.get("product_name") or p.get("title") or p.get("part_name") or ""
        # Try common price fields
        price_vals = []
        for key in ("price", "min_price", "price_cents", "price_display", "priceFormatted"):
            if key in p:
                try:
                    v = p[key]
                    if isinstance(v, (int, float)):
                        price_vals.append(float(v))
                    elif isinstance(v, str):
                        # extract $ numbers
                        m = re.findall(r'\$\s*([0-9,]+(?:\.\d{1,2})?)', v)
                        for mm in m:
                            price_vals.append(float(mm.replace(',', '')))
                        # also raw numbers
                        m2 = re.findall(r'([0-9,]+\.\d{2})', v)
                        for mm in m2:
                            price_vals.append(float(mm.replace(',', '')))
                except Exception:
                    pass
        # fallback: inspect nested merchants/price lists
        if not price_vals:
            # find all dollar-looking numbers inside this product's JSON representation
            try:
                raw = json.dumps(p)
                m = re.findall(r'\$\s*([0-9,]+(?:\.\d{1,2})?)', raw)
                for mm in m:
                    price_vals.append(float(mm.replace(',', '')))
                m2 = re.findall(r'([0-9,]+\.\d{2})', raw)
                for mm in m2:
                    price_vals.append(float(mm.replace(',', '')))
            except Exception:
                pass

        # url extraction if present
        url = p.get("url") or p.get("product_url") or p.get("detail_url") or ""
        # normalize if relative
        if url and url.startswith("/"):
            url = "https://ca.pcpartpicker.com" + url

        if name and price_vals:
            candidates.append({
                "name": name.strip(),
                "price": min(price_vals),
                "url": url
            })

    # If JSON parse returned nothing, fallback to regex scanning across the raw text
    if not candidates:
        # scan for patterns like "product_name":"...","price":"$123.45" or similar
        pattern = re.compile(r'"name"\s*:\s*"([^"]{3,200})"[\s\S]{0,200}?"price"\s*:\s*"?\$?([0-9,]+\.\d{2})"?', re.IGNORECASE)
        for m in pattern.finditer(json_text):
            try:
                nm = m.group(1)
                pr = float(m.group(2).replace(',', ''))
                candidates.append({"name": nm, "price": pr, "url": ""})
            except Exception:
                pass

    return candidates


def get_cheapest_ram(max_retries=2, max_pages=3, wait_for_js=15000):
    """
    Primary strategy:
      1) fetch the page rendered (long wait_for)
      2) search HTML for qapi endpoint and try fetching that JSON directly (render=false)
      3) parse qapi response for products -> filter to 32GB DDR5 -> pick min price
    Fallback:
      - parse rendered HTML (but do not write huge files), using robust price extraction
    """

    all_candidates = []

    for page in range(1, max_pages + 1):
        page_url = PCPP_URL_TEMPLATE.format(page=page)
        print(f"[INFO] Fetching rendered PCPP page (page {page}) with wait_for {wait_for_js}ms")
        r = fetch_via_scraperapi(page_url, render=True, wait_for=wait_for_js, scroll=True, scroll_delay=3000, timeout=120)
        if r is None:
            print(f"[WARN] Rendered page fetch failed for page {page}")
            continue

        html = r.text

        # 1) Try to find the internal qapi endpoint in the HTML
        qapi_path = extract_qapi_endpoint(html)
        if qapi_path:
            qapi_url = "https://ca.pcpartpicker.com" + qapi_path
            print(f"[INFO] QAPI FOUND: {qapi_url}")
            # fetch qapi JSON (no render required)
            q = fetch_via_scraperapi(qapi_url, render=False, timeout=90)
            if q and q.status_code == 200:
                q_text = q.text
                # small log snippet
                print(f"[INFO] QAPI response snippet: {q_text[:MAX_DEBUG_PRINT_CHARS]!r}")
                candidates = parse_qapi_json_text(q_text)
                if candidates:
                    print(f"[INFO] QAPI parsed {len(candidates)} product candidates")
                    # filter for target kits and add to global list
                    for c in candidates:
                        if is_target_kit(c.get("name", "")):
                            all_candidates.append(c)
                    # If we got candidates from qapi, we can continue to next page (or stop early)
                    # we'll continue collecting across pages for completeness
                    continue
                else:
                    print("[WARN] QAPI fetch succeeded but no candidates were parsed via JSON heuristics")
            else:
                print("[WARN] QAPI fetch failed or returned non-200, falling back to HTML parsing")

        else:
            print("[INFO] QAPI NOT FOUND on page; will attempt fallback HTML parsing")

        # Fallback: parse the rendered HTML (but avoid saving full HTML)
        try:
            soup = BeautifulSoup(html, "html.parser")
            rows = soup.select("tr.tr__product")
            print(f"[INFO] FALLBACK HTML parsing: found {len(rows)} rows on page {page}")
            for item in rows:
                name_el = item.find("a")
                if not name_el:
                    continue
                raw_name = name_el.get_text(strip=True)
                name = re.sub(r'\(\d+\)$', '', raw_name).strip()
                href = name_el.get("href", "")
                link = "https://ca.pcpartpicker.com" + href if href else ""
                # apply client-side filter
                if not is_target_kit(name):
                    continue
                price_cell = item.select_one("td.td__price")
                if not price_cell:
                    continue
                raw_text = price_cell.get_text(" ", strip=True)
                # robust dollar extraction
                matches = re.findall(r'\$\s*[0-9,]+(?:\.\d{1,2})?', raw_text)
                prices = []
                for m in matches:
                    try:
                        prices.append(float(m.replace('$', '').replace(',', '').strip()))
                    except:
                        pass
                # fallback numeric matches
                if not prices:
                    nums = re.findall(r'([0-9,]+\.\d{2})', raw_text)
                    for n in nums:
                        try:
                            prices.append(float(n.replace(',', '')))
                        except:
                            pass
                if not prices:
                    continue
                all_candidates.append({"name": name, "price": min(prices), "url": link})
        except Exception as e:
            print(f"[ERROR] HTML fallback parse failed on page {page}: {e}")
            continue

    # Final aggregation
    if not all_candidates:
        print("[RESULT] No candidates found after QAPI + HTML fallback")
        return None

    # deduplicate by (name,url) roughly, keep lowest price per name
    keyed = {}
    for c in all_candidates:
        key = (c.get("name","").strip(), c.get("url",""))
        prev = keyed.get(key)
        if not prev or c["price"] < prev["price"]:
            keyed[key] = c

    final = list(keyed.values())
    final.sort(key=lambda x: x["price"])

    print(f"[RESULT] Found {len(final)} target candidates; cheapest: ${final[0]['price']:.2f} - {final[0]['name']}")
    # small snippet of raw price cell or url for debugging (not full HTML)
    print(f"[DEBUG] top candidate URL/snippet: {final[0].get('url','(no url)')}")
    return final[0]


def manage_history(current_price):
    history = []
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, "r") as f:
                history = json.load(f)
        except Exception:
            history = []
    today = datetime.now().strftime("%Y-%m-%d")
    if not history or history[-1]["date"] != today:
        history.append({"date": today, "price": current_price})
    else:
        history[-1]["price"] = current_price
    history = history[-30:]
    with open(HISTORY_FILE, "w") as f:
        json.dump(history, f)
    prices = [entry["price"] for entry in history]
    avg = sum(prices) / len(prices) if prices else current_price
    trend = "➖"
    if len(prices) > 1:
        prev = prices[-2]
        if current_price < prev:
            trend = "⬇️"
        elif current_price > prev:
            trend = "⬆️"
    return avg, trend, len(history)


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
                    {"name": "Trend", "value": trend, "inline": True},
                    {"name": "Stats", "value": f"Avg: ${avg_price:.2f} (over {days_tracked} days)", "inline": False}
                ],
                "url": item.get("url", "")
            }
        ]
    }
    try:
        requests.post(WEBHOOK_URL.strip(), json=payload, timeout=15)
        print("[INFO] Posted to Discord")
    except Exception as e:
        print(f"[ERROR] Discord post failed: {e}")


if __name__ == "__main__":
    print("[START] RAM Bot run")
    deal = get_cheapest_ram()
    if deal:
        avg, trend, count = manage_history(deal["price"])
        post_to_discord(deal, avg, trend, count)
    else:
        print("[END] No deal found")
