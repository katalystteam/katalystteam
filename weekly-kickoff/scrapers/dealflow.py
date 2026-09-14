"""DealFlow multifamily listing scraper."""
from __future__ import annotations

import re
from datetime import date

from playwright.sync_api import Page

from models import PropertyRecord
from scrapers.base import BaseScraper, parse_price, parse_units


class DealFlowScraper(BaseScraper):
    source_name = "DealFlow"
    base_url = "https://www.dealflow.com/properties?state=IA&propertyType=Multifamily"

    def parse_listings(self, page: Page) -> list[PropertyRecord]:
        records = []
        body = page.locator("body").inner_text()
        cards = page.locator("[class*='property'], [class*='listing'], article").all()

        for card in cards[:25]:
            try:
                text = card.inner_text()
                if "IA" not in text and "Iowa" not in text:
                    continue
                lines = [l.strip() for l in text.split("\n") if l.strip()]
                city_match = re.search(r"([A-Za-z\s.]+),\s*IA", text)
                records.append(PropertyRecord(
                    address=lines[0] if lines else "Unknown",
                    city=city_match.group(1).strip() if city_match else "",
                    status="LISTED",
                    price=parse_price(text),
                    units=parse_units(text),
                    listed_date=date.today(),
                    notes="Scraped from DealFlow",
                ))
            except Exception:
                continue

        if not records:
            for m in re.finditer(r"([\w\d\s.-]+)\s+([A-Za-z\s.]+),?\s*IA", body):
                records.append(PropertyRecord(
                    address=m.group(1).strip(),
                    city=m.group(2).strip(),
                    status="LISTED",
                    listed_date=date.today(),
                    notes="Scraped from DealFlow (body parse)",
                ))
        return records[:20]
