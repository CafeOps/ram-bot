import requests
from bs4 import BeautifulSoup
import json
import os
import sys

PCPP_URL = "https://ca.pcpartpicker.com/products/memory/#L=25,300&S=6000,9600&X=0,100522&Z=32768002&sort=price&page=1"

try:
    WEBHOOK_URL = os.environ["DISCORD_WEBHOOK"]
except KeyError:
    print("Error: DISCORD_WEBHOOK environment variable not set.")
    sys.exit(1)

def get_cheapest_ram():
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    
    try:
        response = requests.get(PCPP_URL, headers=headers)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.content, "html.parser")
        
        product_list = soup.select("tr.tr__product")
        
        if not product_list:
            print("Error: Could not find product list. PCPartPicker layout may have changed or no items match filters.")
            return None

        top_item = product_list[0]
        
        name_element = top_item.select_one("div.td__name a")
        name = name_element.get_text(strip=True)
        
        link = "https://ca.pcpartpicker.com" + name_element["href"]
        
        price_element = top_item.select_one("td.td__price")
        price = price_element.get_text(strip=True)
        
        if not price:
            price = "Check Link (Price not scraped)"
        return {"name": name, "price": price, "url": link}
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
                "description": f"The current cheapest kit on PCPartPicker (CA).",
                "color": 5814783, 
                "fields": [
                    {
                        "name": "Product",
                        "value": item['name'],
                        "inline": False
                    },
                    {
                        "name": "Price",
                        "value": f"**{item['price']}**",
                        "inline": True
                    }
                ],
                "url": item['url']
            }
        ]
    }
    
    try:
        result = requests.post(WEBHOOK_URL, json=payload)
        result.raise_for_status()
        print("Success: Posted to Discord.")
    except requests.exceptions.RequestException as e:
        print(f"Discord Error: {e}")

if __name__ == "__main__":
    print("Fetching data...")
    deal = get_cheapest_ram()
    
    if deal:
        print(f"Found: {deal['name']} @ {deal['price']}")
        post_to_discord(deal)
    else:
        print("No deal found.")