"""Crexi multifamily listing scraper."""
from __future__ import annotations

import re
from datetime import date

from playwright.sync_api import Page

from models import PropertyRecord
from scrapers.base import BaseScraper, parse_price, parse_units


class CrexiScraper(BaseScraper):
    source_name = "Crexi"
    base_url = "https://www.crexi.com/properties?propertyTypes=Multifamily&states=IA"

    def parse_listings(self, page: Page) -> list[PropertyRecord]:
        records = []
        cards = page.locator("[class*='property'], [class*='listing'], article, .card").all()
        if not cards:
            body = page.locator("body").inner_text()
            records.extend(self._parse_from_text(body))
            return records

        for card in cards[:30]:
            try:
                text = card.inner_text()
                if "IA" not in text and "Iowa" not in text:
                    continue
                record = self._parse_card_text(text)
                if record:
                    records.append(record)
            except Exception:
                continue
        return records

    def _parse_card_text(self, text: str) -> PropertyRecord | None:
        lines = [l.strip() for l in text.split("\n") if l.strip()]
        if len(lines) < 2:
            return None

        address = lines[0]
        city_match = re.search(r"([A-Za-z\s.]+),\s*IA", text)
        city = city_match.group(1).strip() if city_match else ""
        price = parse_price(text)
        units = parse_units(text)

        return PropertyRecord(
            address=address,
            city=city,
            status="LISTED",
            price=price,
            units=units,
            listed_date=date.today(),
            notes="Scraped from Crexi",
        )

    def _parse_from_text(self, text: str) -> list[PropertyRecord]:
        records = []
        for block in re.split(r"\n{2,}", text):
            if "IA" not in block and "Iowa" not in block:
                continue
            if not re.search(r"(?:apt|apartment|multifamily|units)", block, re.I):
                continue
            rec = self._parse_card_text(block)
            if rec:
                records.append(rec)
        return records[:20]
