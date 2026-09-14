"""Marcus & Millichap multifamily listing scraper."""
from __future__ import annotations

import re
from datetime import date

from playwright.sync_api import Page

from models import PropertyRecord
from scrapers.base import BaseScraper, parse_price, parse_units


class MarcusMillichapScraper(BaseScraper):
    source_name = "MarcusMillichap"
    base_url = "https://www.marcusmillichap.com/properties?propertyType=Multifamily&state=IA"

    def parse_listings(self, page: Page) -> list[PropertyRecord]:
        records = []
        cards = page.locator(
            "[class*='property'], [class*='listing'], [class*='card'], article"
        ).all()

        for card in cards[:25]:
            try:
                text = card.inner_text()
                if "IA" not in text and "Iowa" not in text:
                    continue
                lines = [l.strip() for l in text.split("\n") if l.strip()]
                city_match = re.search(r"([A-Za-z\s.]+),\s*IA", text)
                broker_match = re.search(r"([A-Z][a-z]+ [A-Z][a-z]+)", text)

                records.append(PropertyRecord(
                    address=lines[0] if lines else "Unknown",
                    city=city_match.group(1).strip() if city_match else "",
                    status="LISTED",
                    price=parse_price(text),
                    units=parse_units(text),
                    broker=broker_match.group(1) if broker_match else "",
                    broker_firm="Marcus & Millichap",
                    listed_date=date.today(),
                    notes="Scraped from Marcus & Millichap",
                ))
            except Exception:
                continue
        return records
