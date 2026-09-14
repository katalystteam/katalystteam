"""KataLYST Current LYSTings scraper: the team's own public listings page.

NOTE: This is adapted from a working scraper already validated on the
user's local machine -- weekly-kickoff/scrapers/katalyst_tracker.py in
this same repo. Its own captured source-of-truth run
(weekly-kickoff/output/source_of_truth_2026-06-06.json) shows it is the
ONLY one of seven configured sources (KataLYST + 6 external
marketplaces) that returned real, clean records in that run: 6 real
Iowa listings from here, 0 from Crexi/LoopNet/CBRE/DealFlow/JLL, and 2
garbage rows from Marcus & Millichap (nav-link text mis-parsed as an
address). That's real evidence, not a guess -- unlike the five external
marketplace scrapers, katalystteam.com is the team's own site, so there
is no bot-protection wall to defeat.

Ported into this project's architecture (BaseScraper retry/diagnostics/
screenshot infra, this project's CSV schema and normalize.py helpers)
rather than copied verbatim. One deliberate behavior change from the
original: the original set listed_date to "today" for every record,
which isn't a real listing date -- this version leaves date_listed
blank instead, per this project's own rule for sources that don't
expose a true listing date, rather than fabricating one that would
incorrectly pass the last-7-days filter forever.
"""
from __future__ import annotations

import logging
import re
from typing import List

from playwright.sync_api import Page

from scrapers.base import BaseScraper, diagnose_page, new_record, safe_goto
from scrapers.normalize import (
    normalize_cap_rate,
    normalize_price,
    normalize_state,
    normalize_units,
    within_last_n_days,
)

logger = logging.getLogger("scraper")

TRACKER_URL = "https://katalystteam.com/current-lystings/"
BROKER_NAME = "Jared Husmann"
BROKER_EMAIL = "jhusmann@katalystteam.com"

_CITY_PATTERN = (
    r"^(.+?)\s+(Des Moines|West Des Moines|Waterloo|Anamosa|Ames|Cedar Rapids|"
    r"Dubuque|Sioux City|Iowa City|Ft\. Dodge|Fort Dodge)$"
)


def _split_address_city(full_addr: str) -> tuple[str, str]:
    m = re.match(_CITY_PATTERN, full_addr, re.IGNORECASE)
    if m:
        return m.group(1).strip(), m.group(2).strip()
    tokens = full_addr.split()
    if len(tokens) < 2:
        return full_addr, ""
    return " ".join(tokens[:-1]), tokens[-1]


class KatalystTrackerScraper(BaseScraper):
    SITE_NAME = "katalyst_tracker"

    def _enrich_from_detail(self, page: Page, listing_url: str) -> dict:
        """Fetch the property detail page for units/year-built/price that
        aren't on the listings index page. Best-effort: any failure here
        just leaves those fields blank rather than failing the record."""
        enrichment = {"units": "", "year_built": "", "price": ""}
        if not listing_url:
            return enrichment
        try:
            page.goto(listing_url, timeout=self.timeout, wait_until="domcontentloaded")
            page.wait_for_timeout(2000)
            text = page.inner_text("body")

            units_m = re.search(r"(\d+)-unit", text, re.IGNORECASE) or re.search(r"(\d+)\s+units?\b", text, re.IGNORECASE)
            if units_m:
                enrichment["units"] = units_m.group(1)

            yb_m = re.search(r"Year Built:\s*(\d{4})", text, re.IGNORECASE)
            if yb_m:
                enrichment["year_built"] = yb_m.group(1)

            price_m = re.search(r"Current Price:\s*\$([\d,]+)", text, re.IGNORECASE)
            if price_m:
                enrichment["price"] = price_m.group(1)
        except Exception as exc:  # noqa: BLE001 - enrichment is best-effort, never fatal
            logger.info("[%s] detail enrichment failed for %s: %s", self.SITE_NAME, listing_url, exc)
        return enrichment

    def scrape(self, page: Page) -> List[dict]:
        if not safe_goto(page, TRACKER_URL, self.timeout, self.SITE_NAME):
            return []

        page.wait_for_timeout(2000)
        diagnose_page(page, self.SITE_NAME)

        html = page.content()
        blocks = re.split(r"Multifamily for Sale", html)[1:]

        if not blocks:
            logger.warning("[%s] no 'Multifamily for Sale' blocks found -- page structure may have changed", self.SITE_NAME)
            return []

        records: List[dict] = []
        for block in blocks:
            addr_m = re.search(r">([^<]+,\s*IA)</p>", block)
            if not addr_m:
                continue
            full_addr = addr_m.group(1).strip().replace(", IA", "").strip()
            address, city = _split_address_city(full_addr)
            if not city or "TX" in full_addr:
                continue

            price_m = re.search(r"Sale Price:\s*</strong>\s*([^<]+)", block)
            cap_m = re.search(r"Cap Rate:\s*</strong>\s*([^<]+)", block)
            url_m = re.search(r'href="(https://katalystteam\.com/[^"?]+)', block)

            listing_url = url_m.group(1) if url_m else ""
            price_raw = price_m.group(1) if price_m else ""
            cap_raw = cap_m.group(1) if cap_m else ""

            enrichment = self._enrich_from_detail(page, listing_url)
            asking_price = normalize_price(price_raw) or normalize_price(enrichment["price"])
            units = normalize_units(enrichment["units"])

            records.append(new_record(
                source="KataLYST",
                property_name=address,
                address=address,
                city=city,
                state=normalize_state("IA"),
                asking_price=asking_price,
                units=units,
                cap_rate=normalize_cap_rate(cap_raw),
                property_type="Multifamily",
                broker_name=BROKER_NAME,
                broker_email=BROKER_EMAIL,
                date_listed="",  # index page doesn't expose a true listing date -- left blank per spec
                listing_url=listing_url,
            ))

        return [r for r in records if within_last_n_days(r["date_listed"], self.config["date_range_days"])]
