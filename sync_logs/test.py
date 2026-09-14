from playwright.sync_api import sync_playwright
import pandas as pd
from datetime import datetime

URLS = [
    "https://www.cbre.com/properties",
    "https://property.jll.com/",
    "https://www.marcusmillichap.com/properties"
]

rows = []

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False)

    for url in URLS:
        page = browser.new_page()
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(8000)

        rows.append({
            "date_scraped": datetime.now().strftime("%Y-%m-%d"),
            "source_url": url,
            "page_title": page.title(),
            "page_text_sample": page.locator("body").inner_text()[:3000]
        })

        page.close()

    browser.close()

df = pd.DataFrame(rows)
df.to_excel("katalyst_playwright_trial.xlsx", index=False)

print("Saved: katalyst_playwright_trial.xlsx")