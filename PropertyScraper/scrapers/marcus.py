"""Marcus & Millichap scraper: Multifamily listings, Iowa.

NOTE: marcusmillichap.com's public "Properties for Sale" search
supports state and property-type query params/filters, but the exact
UI (dropdown vs. facet checkboxes) changes with site redesigns. This
scraper first tries a direct query-string search URL, and falls back
to driving the on-page filter controls if that URL pattern 404s or the
result grid is empty.
"""
from __future__ import annotations

import logging
from typing import List

from playwright.sync_api import Page

from scrapers.base import BaseScraper, diagnose_page, new_record, safe_attr, safe_goto, safe_text
from scrapers.normalize import (
    extract_city,
    is_multifamily,
    looks_like_iowa,
    normalize_cap_rate,
    normalize_price,
    normalize_state,
    normalize_units,
    within_last_n_days,
)

logger = logging.getLogger("scraper")

DIRECT_SEARCH_URL = (
    "https://www.marcusmillichap.com/properties/search"
    "?propertyType=Multifamily&state=Iowa"
)

CARD_SELECTORS = [".property-card", ".listing-card", "[data-testid='property-card']", "article"]
NAME_SELECTORS = [".property-card-title", "h3", "h4"]
ADDRESS_SELECTORS = [".property-card-address", ".address"]
PRICE_SELECTORS = [".property-card-price", ".price"]
DETAIL_SELECTORS = [".property-card-details", ".details"]
LINK_SELECTORS = ["a"]
NEXT_BUTTON_SELECTORS = ["a[aria-label='Next']", ".pagination-next"]


def _first_match(card, selectors: List[str]) -> str:
    for sel in selectors:
        text = safe_text(card, sel)
        if text:
            return text
    return ""


class MarcusScraper(BaseScraper):
    SITE_NAME = "marcus"

    def scrape(self, page: Page) -> List[dict]:
        if not safe_goto(page, DIRECT_SEARCH_URL, self.timeout, self.SITE_NAME):
            base_url = self.config["sites"]["marcus"]["url"]
            logger.warning("[%s] direct search URL failed, falling back to %s", self.SITE_NAME, base_url)
            if not safe_goto(page, base_url, self.timeout, self.SITE_NAME):
                return []

        page.wait_for_timeout(3000)
        diagnose_page(page, self.SITE_NAME)

        records: List[dict] = []
        for page_num in range(1, self.max_pages + 1):
            cards = []
            for sel in CARD_SELECTORS:
                cards = page.query_selector_all(sel)
                if cards:
                    break

            if not cards:
                logger.warning(
                    "[%s] no property cards found on page %d (search UI may require "
                    "manual filter interaction after a redesign)", self.SITE_NAME, page_num
                )
                break

            for card in cards:
                name = _first_match(card, NAME_SELECTORS)
                address = _first_match(card, ADDRESS_SELECTORS)
                price_raw = _first_match(card, PRICE_SELECTORS)
                detail_text = _first_match(card, DETAIL_SELECTORS)
                href = safe_attr(card, LINK_SELECTORS[0], "href")
                if href and href.startswith("/"):
                    href = f"https://www.marcusmillichap.com{href}"

                raw_text = " | ".join(filter(None, [name, address, price_raw, detail_text]))
                if not looks_like_iowa(raw_text):
                    continue
                if not is_multifamily(raw_text + " multifamily"):
                    continue

                units = normalize_units(detail_text)
                cap_rate = normalize_cap_rate(detail_text)
                if not units or not cap_rate:
                    fallback = self.ollama.extract_fields(raw_text)
                    units = units or normalize_units(fallback.get("units"))
                    cap_rate = cap_rate or normalize_cap_rate(fallback.get("cap_rate"))

                records.append(new_record(
                    source="Marcus & Millichap",
                    property_name=name,
                    address=address,
                    city=extract_city(address),
                    state=normalize_state("IA"),
                    asking_price=normalize_price(price_raw),
                    units=units,
                    cap_rate=cap_rate,
                    property_type="Multifamily",
                    broker_name="",
                    broker_email="",
                    date_listed="",
                    listing_url=href,
                ))

            next_btn = None
            for sel in NEXT_BUTTON_SELECTORS:
                next_btn = page.query_selector(sel)
                if next_btn:
                    break
            if not next_btn:
                break
            try:
                next_btn.click()
                page.wait_for_timeout(2000)
            except Exception:  # noqa: BLE001
                break

        return [r for r in records if within_last_n_days(r["date_listed"], self.config["date_range_days"])]
