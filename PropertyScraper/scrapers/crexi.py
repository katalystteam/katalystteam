"""Crexi scraper: Iowa multifamily, Sales listings.

NOTE: Crexi serves its search results through an Angular SPA behind
Cloudflare bot management. Selectors below match the card structure
observed on crexi.com/search as of the time this was written; if Crexi
ships a redesign or the request gets bot-challenged, `scrape()` will
log a warning and return an empty list rather than crash the run.
"""
from __future__ import annotations

import logging
from typing import List

from playwright.sync_api import Page

from scrapers.base import BaseScraper, diagnose_page, new_record, safe_attr, safe_goto, safe_text, sniff_dom
from scrapers.normalize import (
    is_multifamily,
    looks_like_iowa,
    normalize_cap_rate,
    normalize_date,
    normalize_price,
    normalize_state,
    normalize_units,
    within_last_n_days,
)

logger = logging.getLogger("scraper")

CARD_SELECTORS = ["app-property-card", ".list-card", "[data-testid='property-card']"]
NAME_SELECTORS = [".list-card-title", ".property-card-title", "h3", "h4"]
PRICE_SELECTORS = [".list-card-price", ".property-card-price", "[data-testid='price']"]
ADDRESS_SELECTORS = [".list-card-address", ".property-card-address", "[data-testid='address']"]
DETAIL_SELECTORS = [".list-card-info", ".property-card-info", ".list-card-attributes"]
BROKER_SELECTORS = [".list-card-broker", ".broker-name"]
LINK_SELECTORS = ["a.list-card-link", "a"]
NEXT_BUTTON_SELECTORS = ["button[aria-label='Next page']", ".pagination-next:not([disabled])"]


def _first_match(card, selectors: List[str]) -> str:
    for sel in selectors:
        text = safe_text(card, sel)
        if text:
            return text
    return ""


class CrexiScraper(BaseScraper):
    SITE_NAME = "crexi"

    def scrape(self, page: Page) -> List[dict]:
        url = self.config["sites"]["crexi"]["url"]
        if not safe_goto(page, url, self.timeout, self.SITE_NAME):
            return []

        page.wait_for_timeout(3000)  # allow Angular app to hydrate
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
                    "[%s] no listing cards found on page %d (selectors may be stale or "
                    "request was bot-challenged)", self.SITE_NAME, page_num
                )
                sniff_dom(page, self.SITE_NAME)
                break

            for card in cards:
                name = _first_match(card, NAME_SELECTORS)
                price_raw = _first_match(card, PRICE_SELECTORS)
                address = _first_match(card, ADDRESS_SELECTORS)
                detail_text = _first_match(card, DETAIL_SELECTORS)
                broker = _first_match(card, BROKER_SELECTORS)
                href = ""
                for sel in LINK_SELECTORS:
                    href = safe_attr(card, sel, "href")
                    if href:
                        break
                if href and href.startswith("/"):
                    href = f"https://www.crexi.com{href}"

                raw_text = " | ".join(filter(None, [name, price_raw, address, detail_text]))
                if not looks_like_iowa(raw_text) or not is_multifamily(raw_text + " multifamily"):
                    # Search is already filtered to IA + Multifamily server-side;
                    # this is a local safety net per FILTER REQUIREMENTS.
                    if not looks_like_iowa(raw_text):
                        continue

                units = normalize_units(detail_text)
                cap_rate = normalize_cap_rate(detail_text)
                if not units or not cap_rate:
                    fallback = self.ollama.extract_fields(raw_text)
                    units = units or normalize_units(fallback.get("units"))
                    cap_rate = cap_rate or normalize_cap_rate(fallback.get("cap_rate"))

                date_listed = ""  # Crexi does not expose listing date on card view

                records.append(new_record(
                    source="Crexi",
                    property_name=name,
                    address=address,
                    city="",
                    state=normalize_state("IA"),
                    asking_price=normalize_price(price_raw),
                    units=units,
                    cap_rate=cap_rate,
                    property_type="Multifamily",
                    broker_name=broker,
                    broker_email="",
                    date_listed=date_listed,
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
