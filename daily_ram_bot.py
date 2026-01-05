import requests
from bs4 import BeautifulSoup
import os
import sys
import time
import hashlib

PCPP_URL = "https://ca.pcpartpicker.com/products/memory/#L=25,300&S=6000,9600&X=0,100522&Z=32768002&sort=price&page=1"

try:
    WEBHOOK_URL = os.environ["DISCORD_WEBHOOK"]
    SCRAPER_API_KEY = os.environ["SCRAPER_API_KEY"]
except KeyError as e:
    print(f"Error: {e} environment variable not set.")
    sys.exit(1)

def _short_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest()[:12]

def _print_response_debug(resp: requests.Response):
    print("----- HTTP DEBUG -----")
    print("Final request URL:")
    print(resp.url)
    print(f"Status: {resp.status_code}")
    print(f"Content-Type: {resp.headers.get('Content-Type')}")
    print(f"Content-Length: {resp.headers.get('Content-Length')}")
    print(f"Server: {resp.headers.get('Server')}")
    print("----------------------")

def _print_html_debug(html: str, soup: BeautifulSoup):
    title = soup.title.get_text(strip=True) if soup.title else "(no title)"
    print("----- HTML DEBUG -----")
    print(f"Title: {title}")
    print(f"HTML bytes: {len(html.encode('utf-8', errors='ignore'))}")
    print(f"HTML hash: {_short_hash(html)}")
    print(f"Contains 'pcpartpicker': {'pcpartpicker' in html.lower()}")
    print(f"Contains 'captcha': {'captcha' in html.lower()}")
    print(f"Contains 'cloudflare': {'cloudflare' in html.lower()}")
    print("Selector counts:")
    print(f"  tr.tr__product: {len(soup.select('tr.tr__product'))}")
    print(f"  a (all): {len(soup.select('a'))}")
    print(f"  table (all): {len(soup.select('table'))}")
    print("----------------------")

def get_cheapest_ram():
    payload = {
        "api_key": SCRAPER_API_KEY,
        "url": PCPP_URL,
        "render": "true",
        "country_code": "ca",
        "device_type": "desktop",
    }

    try:
        print("Contacting ScraperAPI...")
        t0 = time.time()
        response = requests.get("https://api.scraperapi.com/", params=payload, timeout=60)
        dt = time.time() - t0

        print(f"DEBUG: Request duration: {dt:.2f}s")
        _print_response_debug(response)

        response.raise_for_status()

        html = response.text
        soup = BeautifulSoup(html, "html.parser")
        _print_html_debug(html, soup)

        product_list = soup.select("tr.tr__product")
        print(f"DEBUG: Found {len(product_list)} products.")

        if not product_list:
            print("Error: Product list is empty.")
            print("--- DEBUG: HTML DUMP (First 2000 chars) ---")
            print(html[:2000])
            print("--- DEBUG: HTML DUMP (Last 500 chars) ---")
            print(html[-500:])
            return None

        top_item = product_list[0]

        name_element = top_item.select_one("div.td__name a")
        if not name_element:
            print("Error: Could not find name element using selector 'div.td__name a'.")
            print("DEBUG: First row HTML (first 800 chars):")
            print(str(top_item)[:800])
            return None

        name = name_element.get_text(strip=True)
        link = "https://ca.pcpartpicker.com" + name_element.get("href", "")

        price_element = top_item.select_one("td.td__price")
        price = price_element.get_text(strip=True) if price_element else ""
        if not price:
            price = "Check Link (Price not scraped)"

        return {"name": name, "price": price, "url": link}

    except requests.exceptions.Timeout as e:
        print(f"Scraping Error: Timeout: {e}")
        return None
    except requests.exceptions.RequestException as e:
        print(f"Scraping Error: RequestException: {e}")
        if getattr(e, "response", None) is not None:
            _print_response_debug(e.response)
        return None
    except Exception as e:
        print(f"Scraping Error: {e}")
        return None

def post_to_discord(item):
    if not item:
        return

    payload = {
        "username": "RAM Bot",
        "embeds": [
            {
                "title": "Daily RAM Deal (32GB DDR5 6000+ CL30)",
                "description": "The current cheapest kit on PCPartPicker (CA).",
                "color": 5814783,
                "fields": [
                    {"name": "Product", "value": item["name"], "inline": False},
                    {"name": "Price", "value": f"**{item['price']}**", "inline": True},
                ],
                "url": item["url"],
            }
        ],
    }

    try:
        result = requests.post(WEBHOOK_URL, json=payload, timeout=20)
        print(f"DEBUG: Discord status: {result.status_code}")
        result.raise_for_status()
        print("Success: Posted to Discord.")
    except requests.exceptions.RequestException as e:
        print(f"Discord Error: {e}")

if __name__ == "__main__":
    print("Starting Bot...")
    deal = get_cheapest_ram()

    if deal:
        print(f"Found: {deal['name']} @ {deal['price']}")
        post_to_discord(deal)
    else:
        print("No deal found.")
