import requests
from bs4 import BeautifulSoup
import os
import sys
import time
import re

# CONFIG
# We append a random timestamp to FORCE ScraperAPI to fetch a fresh copy
TIMESTAMP = int(time.time())
PCPP_URL = f"https://ca.pcpartpicker.com/products/memory/#L=30,300&S=6000,9600&X=0,100522&Z=32768002&sort=price&page=1&_t={TIMESTAMP}"

try:
    WEBHOOK_URL = os.environ["DISCORD_WEBHOOK"]
    SCRAPER_API_KEY = os.environ["SCRAPER_API_KEY"]
except KeyError as e:
    print(f"Error: {e} environment variable not set.")
    sys.exit(1)

def run_fast_diagnostic():
    print(f"[START] Fast Diagnostic Run")
    print(f"[INFO] URL (Cache Busted): {PCPP_URL}")

    payload = {
        "api_key": SCRAPER_API_KEY,
        "url": PCPP_URL,
        "render": "true",       # Essential for JS
        "wait_for": "10000",    # 10s is safer than 5s for full hydration
        "scroll": "true",       # Trigger lazy load
        "scroll_delay": "2000",
        "country_code": "ca",
        "device_type": "desktop",
    }

    try:
        t0 = time.time()
        r = requests.get("https://api.scraperapi.com/", params=payload, timeout=60)
        duration = time.time() - t0
        print(f"[INFO] Request finished in {duration:.2f}s (Status: {r.status_code})")
        
        if r.status_code != 200:
            print(f"[ERROR] ScraperAPI failed: {r.text}")
            return

        html = r.text
        
        # 1. The "Ghost" Check
        target = "Patriot Viper Elite"
        if target in html:
            print(f"\n✅ SUCCESS: Found '{target}' in HTML!")
            
            # 2. Extract price to verify it's readable
            # Simple regex search around the name
            # Look for the name, then grab the next price pattern
            snippet_match = re.search(r'Patriot Viper Elite.*?\$(\d+\.\d{2})', html, re.DOTALL)
            if snippet_match:
                print(f"   Detected Price: ${snippet_match.group(1)}")
            else:
                print(f"   (Name found, but strict regex missed price. Check manually.)")
                
        else:
            print(f"\n❌ FAILURE: '{target}' NOT found in HTML.")
            print("   Possible causes: Merchant Block, Region Mismatch, or Page Load Timeout.")

        # 3. Standard parsing for the log (just to see what we DID get)
        soup = BeautifulSoup(html, "html.parser")
        products = soup.select("tr.tr__product")
        print(f"\n[INFO] Total Rows Parsed: {len(products)}")
        
        if len(products) > 0:
            print("--- First 5 Items Seen ---")
            for item in products[:5]:
                name = item.find("a").get_text(strip=True)
                price = item.select_one("td.td__price").get_text(strip=True)
                print(f"- {name} [{price}]")
                
    except Exception as e:
        print(f"[CRITICAL] Script Error: {e}")

if __name__ == "__main__":
    run_fast_diagnostic()
