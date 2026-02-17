# ram-bot



Checks for the cheapest ddr5 ram kit on pcpartpicker and newegg (canada) every day. posts to discord. 2x16GB 6000 MHz and CL30 or faster.



### How it works

- runs on github actions (free vm)

- uses scraperapi to bypass cloudflare

- scrapes price/name/URL

- saves history to json file to track trends

- posts in discord



### Setup

1. fork 

2. get a scraperapi key (free tier is fine, literally 1 min setup)

3. make a discord webhook

4. put them in repo settings -> secrets -> actions:

   - `DISCORD_WEBHOOK`

   - `SCRAPER_API_KEY`

5. enable actions permission to read/write (so it can save history)



### Disclaimer

if it breaks, god bless.

do not use selenium unless you want to get IP banned


