"""LoopNet scraper: Apartment Buildings, Iowa, For Sale.

NOTE: LoopNet (CoStar Group) also runs bot-detection (PerimeterX) in
front of search results and frequently serves an interstitial/CAPTCHA
to headless browsers. Selectors target the placard/card layout used
on loopnet.com/search/... result pages.
"""
from __future__ import annotations

import logging
from typing import List

from playwright.sync_api import Page

from scrapers.base import BaseScraper, new_record, safe_attr, safe_goto, safe_text
from scrapers.normalize import (
    extract_city,
    normalize_price,
    normalize_state,
    normalize_units,
    within_last_n_days,
)

logger = logging.getLogger("scraper")

CARD_SELECTORS = [".placard", "[data-id='placardContainer']", "article.placard"]
NAME_SELECTORS = [".placard-title", "h4.title", ".placard-header a"]
PRICE_SELECTORS = [".placard-price", ".price"]
ADDRESS_SELECTORS = [".placard-address", ".address"]
DETAIL_SELECTORS = [".placard-info", ".data-points"]
LINK_SELECTORS = ["a.placard-title", "a[href*='/Listing/']", "a"]
NEXT_BUTTON_SELECTORS = ["a[aria-label='Next page']", ".searchPager-next"]


def _first_match(card, selectors: List[str]) -> str:
    for sel in selectors:
        text = safe_text(card, sel)
        if text:
            return text
    return ""


class LoopnetScraper(BaseScraper):
    SITE_NAME = "loopnet"

    def scrape(self, page: Page) -> List[dict]:
        url = self.config["sites"]["loopnet"]["url"]
        if not safe_goto(page, url, self.timeout, self.SITE_NAME):
            return []

        page.wait_for_timeout(3000)

        records: List[dict] = []
        for page_num in range(1, self.max_pages + 1):
            cards = []
            for sel in CARD_SELECTORS:
                cards = page.query_selector_all(sel)
                if cards:
                    break

            if not cards:
                logger.warning(
                    "[%s] no listing cards found on page %d (likely a bot-challenge "
                    "interstitial or a DOM change)", self.SITE_NAME, page_num
                )
                break

            for card in cards:
                name = _first_match(card, NAME_SELECTORS)
                price_raw = _first_match(card, PRICE_SELECTORS)
                address = _first_match(card, ADDRESS_SELECTORS)
                detail_text = _first_match(card, DETAIL_SELECTORS)
                href = ""
                for sel in LINK_SELECTORS:
                    href = safe_attr(card, sel, "href")
                    if href:
                        break
                if href and href.startswith("/"):
                    href = f"https://www.loopnet.com{href}"

                if not name and not address:
                    continue

                units = normalize_units(detail_text)
                if not units:
                    raw_text = " | ".join(filter(None, [name, price_raw, address, detail_text]))
                    fallback = self.ollama.extract_fields(raw_text)
                    units = normalize_units(fallback.get("units"))

                records.append(new_record(
                    source="LoopNet",
                    property_name=name,
                    address=address,
                    city=extract_city(address),
                    state=normalize_state("IA"),
                    asking_price=normalize_price(price_raw),
                    units=units,
                    cap_rate="",
                    property_type="Apartment Building",
                    broker_name="",
                    broker_email="",
                    date_listed="",  # LoopNet does not expose listing date on card view
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
