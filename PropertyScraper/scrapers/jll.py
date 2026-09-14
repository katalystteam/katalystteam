"""JLL Investor Center scraper: Multifamily, Iowa.

NOTE: invest.jll.com is a React SPA; investment listings are searched
through an in-app filter panel rather than query-string parameters, and
most detail pages require an account to view underwriting data. This
scraper drives the visible filter controls (location search + asset
type facet) and scrapes whatever public card data renders.
"""
from __future__ import annotations

import logging
from typing import List

from playwright.sync_api import Page

from scrapers.base import BaseScraper, diagnose_page, new_record, safe_attr, safe_goto, safe_text, sniff_dom
from scrapers.normalize import (
    extract_city,
    is_multifamily,
    looks_like_iowa,
    normalize_state,
    normalize_units,
    within_last_n_days,
)

logger = logging.getLogger("scraper")

LOCATION_INPUT_SELECTORS = ["input[placeholder*='location' i]", "input[type='search']"]
ASSET_TYPE_FILTER_SELECTORS = ["button:has-text('Property Type')", "[data-filter='asset-type']"]
MULTIFAMILY_OPTION_SELECTORS = ["text=Multifamily", "label:has-text('Multifamily')"]
CARD_SELECTORS = [".investment-card", ".property-card", "[data-testid='listing-card']", "article"]
NAME_SELECTORS = [".investment-card-title", "h3", "h4"]
ADDRESS_SELECTORS = [".investment-card-location", ".location"]
DETAIL_SELECTORS = [".investment-card-details", ".details"]
LINK_SELECTORS = ["a"]


def _first_match(card, selectors: List[str]) -> str:
    for sel in selectors:
        text = safe_text(card, sel)
        if text:
            return text
    return ""


class JllScraper(BaseScraper):
    SITE_NAME = "jll"

    def _apply_filters(self, page: Page) -> None:
        try:
            loc_input = None
            for sel in LOCATION_INPUT_SELECTORS:
                loc_input = page.query_selector(sel)
                if loc_input:
                    break
            if loc_input:
                loc_input.fill("Iowa")
                loc_input.press("Enter")
                page.wait_for_timeout(2000)
            else:
                logger.warning("[%s] no location search input found", self.SITE_NAME)

            for sel in ASSET_TYPE_FILTER_SELECTORS:
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
        url = self.config["sites"]["jll"]["url"]
        if not safe_goto(page, url, self.timeout, self.SITE_NAME):
            return []

        page.wait_for_timeout(3000)
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
                "[%s] no investment cards found; JLL's SPA filter flow may have "
                "changed or listings require login", self.SITE_NAME
            )
            sniff_dom(page, self.SITE_NAME)
            return []

        for card in cards:
            name = _first_match(card, NAME_SELECTORS)
            address = _first_match(card, ADDRESS_SELECTORS)
            detail_text = _first_match(card, DETAIL_SELECTORS)
            href = safe_attr(card, LINK_SELECTORS[0], "href")
            if href and href.startswith("/"):
                href = f"https://invest.jll.com{href}"

            raw_text = " | ".join(filter(None, [name, address, detail_text]))
            if not looks_like_iowa(raw_text):
                continue
            if not is_multifamily(raw_text + " multifamily"):
                continue

            units = normalize_units(detail_text)
            if not units:
                fallback = self.ollama.extract_fields(raw_text)
                units = normalize_units(fallback.get("units"))

            records.append(new_record(
                source="JLL Investor Center",
                property_name=name,
                address=address,
                city=extract_city(address),
                state=normalize_state("IA"),
                asking_price="",
                units=units,
                cap_rate="",
                property_type="Multifamily",
                broker_name="",
                broker_email="",
                date_listed="",
                listing_url=href,
            ))

        return [r for r in records if within_last_n_days(r["date_listed"], self.config["date_range_days"])]
