"""Scrape Iowa multifamily listings from KataLYST Current LYSTings tracker."""

from __future__ import annotations

import re
from datetime import date

from playwright.sync_api import Page

from models import PropertyRecord
from scrapers.base import BaseScraper, parse_price


class KatalystTrackerScraper(BaseScraper):
    source_name = "KataLYST"
    base_url = "https://katalystteam.com/current-lystings/"

    def parse_listings(self, page: Page) -> list[PropertyRecord]:
        html = page.content()
        blocks = re.split(r"Multifamily for Sale", html)[1:]
        records: list[PropertyRecord] = []

        for block in blocks:
            addr_m = re.search(r">([^<]+,\s*IA)</p>", block)
            if not addr_m:
                continue
            full_addr = addr_m.group(1).strip().replace(", IA", "").strip()
            city_m = re.match(
                r"^(.+?)\s+(Des Moines|West Des Moines|Waterloo|Anamosa|Ames|Cedar Rapids|Dubuque|Sioux City|Iowa City|Ft\. Dodge|Fort Dodge)$",
                full_addr,
                re.I,
            )
            if city_m:
                address = city_m.group(1).strip()
                city = city_m.group(2).strip()
            else:
                tokens = full_addr.split()
                city = tokens[-1]
                address = " ".join(tokens[:-1])

            price_m = re.search(r"Sale Price:\s*</strong>\s*([^<]+)", block)
            cap_m = re.search(r"Cap Rate:\s*</strong>\s*([^<]+)", block)
            url_m = re.search(r'href="(https://katalystteam\.com/[^"?]+)', block)

            price = parse_price(price_m.group(1)) if price_m else None
            cap = None
            if cap_m:
                cap_val = re.search(r"([\d.]+)", cap_m.group(1))
                cap = float(cap_val.group(1)) if cap_val else None

            record = PropertyRecord(
                address=address,
                city=city,
                status="LISTED",
                price=price,
                cap_rate=cap,
                broker="Jared Husmann",
                broker_firm="KataLYST Team by KW Commercial",
                listed_date=self.week_ending,
                notes="KataLYST Current LYSTings tracker",
            )
            if url_m:
                record.source_url = url_m.group(1)
            records.append(record)

        for record in records:
            if record.source_url:
                self._enrich_from_detail(page, record)

        return [r for r in records if r.city and "TX" not in r.address]

    def _enrich_from_detail(self, page: Page, record: PropertyRecord) -> PropertyRecord:
        """Fetch property detail page for units and year built."""
        try:
            page.goto(record.source_url, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(2500)
            text = page.locator("body").inner_text()

            units_m = re.search(r"(\d+)-unit", text, re.I)
            if not units_m:
                units_m = re.search(r"(\d+)\s+units?\b", text, re.I)
            yb_m = re.search(r"Year Built:\s*(\d{4})", text, re.I)
            price_m = re.search(r"Current Price:\s*\$([\d,]+)", text, re.I)
            if price_m and not record.price:
                record.price = float(price_m.group(1).replace(",", ""))
            if units_m:
                record.units = int(units_m.group(1))
            if yb_m:
                record.year_built = int(yb_m.group(1))
            if record.price and record.units:
                record.price_per_unit = round(record.price / record.units, 2)
        except Exception as exc:
            record.notes += f" | detail: {exc}"
        return record
