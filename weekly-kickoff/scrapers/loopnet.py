"""LoopNet multifamily listing scraper."""
from __future__ import annotations

import re
from datetime import date

from playwright.sync_api import Page

from models import PropertyRecord
from scrapers.base import BaseScraper, parse_price, parse_units


class LoopNetScraper(BaseScraper):
    source_name = "LoopNet"
    base_url = "https://www.loopnet.com/search/apartment-buildings/iowa/for-sale/"

    def parse_listings(self, page: Page) -> list[PropertyRecord]:
        records = []
        selectors = [
            "[data-testid='property-card']",
            ".placard",
            "[class*='property-card']",
            "article",
        ]
        cards = []
        for sel in selectors:
            found = page.locator(sel).all()
            if found:
                cards = found
                break

        for card in cards[:30]:
            try:
                text = card.inner_text()
                if "IA" not in text:
                    continue
                rec = self._parse_text(text)
                if rec:
                    records.append(rec)
            except Exception:
                continue

        if not records:
            records = self._parse_from_body(page.locator("body").inner_text())
        return records

    def _parse_text(self, text: str) -> PropertyRecord | None:
        lines = [l.strip() for l in text.split("\n") if l.strip()]
        if not lines:
            return None
        city_match = re.search(r"([A-Za-z\s.]+),\s*IA", text)
        return PropertyRecord(
            address=lines[0],
            city=city_match.group(1).strip() if city_match else "",
            status="LISTED",
            price=parse_price(text),
            units=parse_units(text),
            listed_date=date.today(),
            notes="Scraped from LoopNet",
        )

    def _parse_from_body(self, text: str) -> list[PropertyRecord]:
        records = []
        for m in re.finditer(
            r"([\w\d\s.-]+),\s*([A-Za-z\s.]+),\s*IA.*?(?:\$[\d,]+|\d+\s*units)",
            text,
            re.I | re.S,
        ):
            records.append(PropertyRecord(
                address=m.group(1).strip(),
                city=m.group(2).strip(),
                status="LISTED",
                listed_date=date.today(),
                notes="Scraped from LoopNet (body parse)",
            ))
        return records[:20]
