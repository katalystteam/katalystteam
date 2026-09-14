"""Marcus & Millichap scraper: Multifamily listings, Iowa.

NOTE: Two prior versions guessed at this site's structure and were both
proven wrong by live diagnostic runs:
  1. A guessed direct search URL (?propertyType=Multifamily&state=Iowa)
     bounced to an error page.
  2. Driving the filter UI by visible label text ("Property Type" /
     "Location" toggles) hung for 30s clicking an element that was never
     actually visible, then still found 0 cards.

A DOM sniff on that second run found the REAL result markup instead:
    <ul class="mm-gs-search-results mm-gs-properties">
      <li propertyid="1627184" dealid="303116" propertytype="Apartments"
          listingprice="Request For Offer" ...>
        <div class="mm-tile" data-dealid="303116"> ... </div>
      </li>
      ...
    </ul>
with real property links like /properties/303116/cedar-gardens. This
version scrapes that real markup directly -- reading propertytype and
listingprice straight off the <li> attributes rather than guessing
child-element selectors for them -- and treats the on-page filter UI as
a best-effort narrowing step with a short click timeout: if it hangs or
fails, cards are still scraped unfiltered and narrowed locally via
looks_like_iowa()/is_multifamily() same as every other site here.

A confirmed-real detail from the same diagnostic: the page URL after
load is .../properties#pageNumber=1&stb=orderdate,DESC -- a hash-based
client-side router, sorted newest-first. With the filter click not
landing, one page of the nationwide "newest" feed (12 cards) won't
reliably contain Iowa listings. This version paginates through that
confirmed URL hash pattern (pageNumber=1..max_pages_per_site) instead
of stopping after page 1, to actually improve the odds of a real
Iowa hit without needing the filter UI fixed.
"""
from __future__ import annotations

import logging
from typing import List, Optional

from playwright.sync_api import ElementHandle, Page, TimeoutError as PlaywrightTimeoutError

from scrapers.base import BaseScraper, diagnose_page, new_record, safe_goto, sniff_dom
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

SEARCH_URL = "https://www.marcusmillichap.com/properties"

# Best-effort narrowing only -- confirmed unreliable (element present but
# not clickable), so every click below uses a short explicit timeout and
# failure here never stops the scrape; local filtering below still applies.
FILTER_CLICK_TIMEOUT_MS = 3000
PROPERTY_TYPE_TOGGLE_SELECTORS = ["text=Property Type", "button:has-text('Property Type')"]
MULTIFAMILY_OPTION_SELECTORS = ["text=Multifamily", "label:has-text('Multifamily')"]

# Confirmed real via live DOM sniff (see module docstring).
CARD_SELECTORS = ["li[propertyid]", "ul.mm-gs-search-results li", ".mm-tile"]
LINK_SELECTOR = "a[href*='/properties/']"
MULTIFAMILY_PROPERTY_TYPES = {"apartments", "multifamily", "apartment", "multi-family"}


def _humanize_slug(href: str) -> str:
    slug = href.rstrip("/").rsplit("/", 1)[-1]
    return slug.replace("-", " ").title() if slug else ""


class MarcusScraper(BaseScraper):
    SITE_NAME = "marcus"

    def _apply_filters(self, page: Page) -> None:
        try:
            for sel in PROPERTY_TYPE_TOGGLE_SELECTORS:
                toggle = page.query_selector(sel)
                if not toggle:
                    continue
                try:
                    toggle.scroll_into_view_if_needed(timeout=FILTER_CLICK_TIMEOUT_MS)
                    toggle.click(timeout=FILTER_CLICK_TIMEOUT_MS)
                except PlaywrightTimeoutError:
                    # Last resort: bypass Playwright's actionability check
                    # (visible/stable/not-covered) and dispatch the click
                    # directly -- covers a sticky header overlapping the
                    # toggle without actually blocking a real click.
                    toggle.click(timeout=FILTER_CLICK_TIMEOUT_MS, force=True)
                page.wait_for_timeout(500)
                for opt_sel in MULTIFAMILY_OPTION_SELECTORS:
                    opt = page.query_selector(opt_sel)
                    if opt:
                        opt.click(timeout=FILTER_CLICK_TIMEOUT_MS)
                        page.wait_for_timeout(500)
                        break
                break
        except PlaywrightTimeoutError:
            logger.info(
                "[%s] filter UI click was not actionable within %dms even with force -- "
                "proceeding with unfiltered, paginated cards instead", self.SITE_NAME, FILTER_CLICK_TIMEOUT_MS
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("[%s] could not apply search filters: %s", self.SITE_NAME, exc)

    def _extract_card(self, card: ElementHandle) -> Optional[dict]:
        property_type_attr = (card.get_attribute("propertytype") or "").strip()
        listing_price_attr = (card.get_attribute("listingprice") or "").strip()
        link = card.query_selector(LINK_SELECTOR)
        href = (link.get_attribute("href") or "").strip() if link else ""
        if href and href.startswith("/"):
            href = f"https://www.marcusmillichap.com{href}"

        try:
            card_text = card.inner_text().strip()
        except Exception:  # noqa: BLE001
            card_text = ""

        name = _humanize_slug(href) or (card_text.splitlines()[0] if card_text else "")
        raw_text = " | ".join(filter(None, [card_text, property_type_attr]))

        if not looks_like_iowa(raw_text):
            return None
        if property_type_attr.lower() not in MULTIFAMILY_PROPERTY_TYPES and not is_multifamily(raw_text):
            return None

        units = normalize_units(card_text)
        cap_rate = normalize_cap_rate(card_text)
        if not units or not cap_rate:
            fallback = self.ollama.extract_fields(raw_text)
            units = units or normalize_units(fallback.get("units"))
            cap_rate = cap_rate or normalize_cap_rate(fallback.get("cap_rate"))

        return new_record(
            source="Marcus & Millichap",
            property_name=name,
            address="",
            city=extract_city(card_text),
            state=normalize_state("IA"),
            asking_price=normalize_price(listing_price_attr) or normalize_price(card_text),
            units=units,
            cap_rate=cap_rate,
            property_type=property_type_attr or "Multifamily",
            broker_name="",
            broker_email="",
            date_listed="",
            listing_url=href,
        )

    def scrape(self, page: Page) -> List[dict]:
        if not safe_goto(page, SEARCH_URL, self.timeout, self.SITE_NAME):
            return []

        page.wait_for_timeout(3000)
        diagnose_page(page, self.SITE_NAME)
        self._apply_filters(page)
        page.wait_for_timeout(1000)

        all_records: List[dict] = []
        total_candidates = 0
        for page_num in range(1, self.max_pages + 1):
            if page_num > 1:
                paged_url = f"{SEARCH_URL}#pageNumber={page_num}&stb=orderdate,DESC"
                if not safe_goto(page, paged_url, self.timeout, self.SITE_NAME):
                    break
                page.wait_for_timeout(2000)

            cards = []
            for sel in CARD_SELECTORS:
                cards = page.query_selector_all(sel)
                if cards:
                    break

            if not cards:
                if page_num == 1:
                    logger.warning("[%s] no property cards found with the confirmed selectors -- site markup may have changed again", self.SITE_NAME)
                    sniff_dom(page, self.SITE_NAME)
                else:
                    logger.info("[%s] page %d returned no cards -- stopping pagination", self.SITE_NAME, page_num)
                break

            total_candidates += len(cards)
            page_records = [r for card in cards if (r := self._extract_card(card)) is not None]
            all_records.extend(page_records)
            logger.info(
                "[%s] page %d: %d candidate cards, %d matched Iowa/multifamily",
                self.SITE_NAME, page_num, len(cards), len(page_records),
            )

            if all_records:
                # Filter landed (or got lucky) -- no need to keep paginating.
                break

        logger.info("[%s] %d total candidate cards across all pages, %d matched Iowa/multifamily", self.SITE_NAME, total_candidates, len(all_records))
        return [r for r in all_records if within_last_n_days(r["date_listed"], self.config["date_range_days"])]
