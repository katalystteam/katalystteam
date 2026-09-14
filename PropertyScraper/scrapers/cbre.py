"""CBRE Deal Flow scraper: Multifamily, Iowa.

NOTE: cbredealflow.com is primarily a lead-gen/marketing front end for
CBRE's investment sales platform; most live deal detail typically sits
behind a broker login. This scraper attempts to (a) apply a Multifamily
+ Iowa filter directly on the public search UI if present, and (b) fall
back to scanning any publicly listed deal cards on the landing page.
Both paths degrade gracefully to an empty list rather than raising.
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
    normalize_state,
    normalize_units,
    within_last_n_days,
)

logger = logging.getLogger("scraper")

SEARCH_INPUT_SELECTORS = ["input[type='search']", "input[placeholder*='location' i]", "input[name*='search' i]"]
PROPERTY_TYPE_FILTER_SELECTORS = [
    "button:has-text('Property Type')",
    "[data-filter='property-type']",
]
MULTIFAMILY_OPTION_SELECTORS = ["text=Multifamily", "label:has-text('Multifamily')"]
CARD_SELECTORS = [".deal-card", ".property-card", "[data-testid='deal-card']", "article"]
NAME_SELECTORS = [".deal-card-title", "h3", "h4"]
LOCATION_SELECTORS = [".deal-card-location", ".location"]
DETAIL_SELECTORS = [".deal-card-details", ".details"]
BROKER_SELECTORS = [".deal-card-broker", ".broker"]
LINK_SELECTORS = ["a"]


def _first_match(card, selectors: List[str]) -> str:
    for sel in selectors:
        text = safe_text(card, sel)
        if text:
            return text
    return ""


class CbreScraper(BaseScraper):
    SITE_NAME = "cbre"

    def _apply_filters(self, page: Page) -> None:
        try:
            search_input = None
            for sel in SEARCH_INPUT_SELECTORS:
                search_input = page.query_selector(sel)
                if search_input:
                    break
            if search_input:
                search_input.fill("Iowa")
                search_input.press("Enter")
                page.wait_for_timeout(2000)
            else:
                logger.warning("[%s] no location search input found on landing page", self.SITE_NAME)

            for sel in PROPERTY_TYPE_FILTER_SELECTORS:
                btn = page.query_selector(sel)
                if btn:
                    btn.click()
                    page.wait_for_timeout(500)
                    for opt_sel in MULTIFAMILY_OPTION_SELECTORS:
                        opt = page.query_selector(opt_sel)
                        if opt:
                            opt.click()
                            page.wait_for_timeout(500)
                            break
                    break
        except Exception as exc:  # noqa: BLE001
            logger.warning("[%s] could not apply search filters: %s", self.SITE_NAME, exc)

    def scrape(self, page: Page) -> List[dict]:
        url = self.config["sites"]["cbre"]["url"]
        if not safe_goto(page, url, self.timeout, self.SITE_NAME):
            return []

        page.wait_for_timeout(2000)
        diagnose_page(page, self.SITE_NAME)
        self._apply_filters(page)

        records: List[dict] = []
        cards = []
        for sel in CARD_SELECTORS:
            cards = page.query_selector_all(sel)
            if cards:
                break

        if not cards:
            logger.warning(
                "[%s] no deal cards found; public deal listings for this site are "
                "commonly gated behind a broker login", self.SITE_NAME
            )
            return []

        for card in cards:
            name = _first_match(card, NAME_SELECTORS)
            location = _first_match(card, LOCATION_SELECTORS)
            detail_text = _first_match(card, DETAIL_SELECTORS)
            broker = _first_match(card, BROKER_SELECTORS)
            href = safe_attr(card, LINK_SELECTORS[0], "href")
            if href and href.startswith("/"):
                href = f"https://www.cbredealflow.com{href}"

            raw_text = " | ".join(filter(None, [name, location, detail_text]))
            if not looks_like_iowa(raw_text):
                continue
            if not is_multifamily(raw_text):
                continue

            units = normalize_units(detail_text)
            if not units:
                fallback = self.ollama.extract_fields(raw_text)
                units = normalize_units(fallback.get("units"))

            records.append(new_record(
                source="CBRE Deal Flow",
                property_name=name,
                address=location,
                city=extract_city(location),
                state=normalize_state("IA"),
                asking_price="",
                units=units,
                cap_rate="",
                property_type="Multifamily",
                broker_name=broker,
                broker_email="",
                date_listed="",
                listing_url=href,
            ))

        return [r for r in records if within_last_n_days(r["date_listed"], self.config["date_range_days"])]
