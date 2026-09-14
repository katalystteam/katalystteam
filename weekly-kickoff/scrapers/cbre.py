"""CBRE multifamily listing scraper."""
from __future__ import annotations

import re
from datetime import date

from playwright.sync_api import Page

from models import PropertyRecord
from scrapers.base import BaseScraper, parse_price, parse_units


class CBREScraper(BaseScraper):
    source_name = "CBRE"
    base_url = (
        "https://www.cbre.com/properties"
        "?aspects=isLetting,isSale&locations=Iowa%2C%20USA&propertyTypes=Multifamily"
    )

    def parse_listings(self, page: Page) -> list[PropertyRecord]:
        records = []
        cards = page.locator(
            "[class*='property-card'], [class*='PropertyCard'], article, .card"
        ).all()

        for card in cards[:30]:
            try:
                text = card.inner_text()
                if "Iowa" not in text and "IA" not in text:
                    continue
                lines = [l.strip() for l in text.split("\n") if l.strip()]
                city_match = re.search(r"([A-Za-z\s.]+),?\s*(?:Iowa|IA)", text)
                broker_match = re.search(r"([A-Z][a-z]+ [A-Z][a-z]+)", text)

                records.append(PropertyRecord(
                    address=lines[0] if lines else "Unknown",
                    city=city_match.group(1).strip() if city_match else "",
                    status="LISTED",
                    price=parse_price(text),
                    units=parse_units(text),
                    broker=broker_match.group(1) if broker_match else "",
                    broker_firm="CBRE",
                    listed_date=date.today(),
                    notes="Scraped from CBRE",
                ))
            except Exception:
                continue
        return records
