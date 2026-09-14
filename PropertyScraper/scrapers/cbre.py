"""CBRE Deal Flow scraper: Multifamily, Iowa.

NOTE: A prior version suspected the result grid lived in an <iframe>
(the page advertises "Listing Engine(tm) technology provided by RCM
LightBox"). A live diagnostic run RULED THAT OUT: the page has exactly
1 frame -- the top-level document itself. The real DOM sniff instead
found the filter UI is a modal, triggered by:
    <li id="rcmListFilter" data-toggle="modal" data-target="#allFiltersModal"
        class="btn-filter btn-all-filters" title="All Filters">
No listing-card markup was found on the closed landing page at all --
consistent with a "deal flow" platform that shows nothing until a
search/filter is actually applied, rather than a login wall. This
version clicks #rcmListFilter to open that modal and re-runs
diagnose_page()/sniff_dom() against whatever renders inside it, since
its internal markup (the actual Property Type / Country controls) is
still unknown -- next run's log gives real evidence instead of another
guessed selector for the modal's contents.
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

# Confirmed real via live DOM sniff (see module docstring).
ALL_FILTERS_TRIGGER_SELECTOR = "#rcmListFilter"
ALL_FILTERS_MODAL_SELECTOR = "#allFiltersModal"

# Contents of the opened modal are still unconfirmed -- best-effort guesses,
# with sniff_dom() as the fallback that gathers real evidence if these miss.
MULTIFAMILY_OPTION_SELECTORS = ["text=Multifamily", "label:has-text('Multifamily')"]
APPLY_BUTTON_SELECTORS = ["button:has-text('Apply')", "button:has-text('Search')", "button:has-text('View Results')"]
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

    def _apply_filters(self, page: Page) -> bool:
        """Open the confirmed "All Filters" modal and best-effort select
        Multifamily inside it. Returns True if the modal actually opened,
        so the caller knows whether to trust the subsequent card search or
        treat it as still-closed (landing-page) state."""
        try:
            trigger = page.query_selector(ALL_FILTERS_TRIGGER_SELECTOR)
            if not trigger:
                logger.warning("[%s] All Filters trigger (%s) not found -- site markup may have changed", self.SITE_NAME, ALL_FILTERS_TRIGGER_SELECTOR)
                return False

            trigger.click(timeout=5000)
            page.wait_for_timeout(1000)

            modal = page.query_selector(ALL_FILTERS_MODAL_SELECTOR)
            if not modal:
                logger.warning("[%s] clicked %s but modal %s did not appear", self.SITE_NAME, ALL_FILTERS_TRIGGER_SELECTOR, ALL_FILTERS_MODAL_SELECTOR)
                return False

            logger.info("[%s] All Filters modal opened -- sniffing its contents", self.SITE_NAME)
            diagnose_page(page, self.SITE_NAME)
            sniff_dom(page, self.SITE_NAME)

            for opt_sel in MULTIFAMILY_OPTION_SELECTORS:
                opt = page.query_selector(opt_sel)
                if opt:
                    opt.click(timeout=3000)
                    page.wait_for_timeout(500)
                    break

            for sel in APPLY_BUTTON_SELECTORS:
                apply_btn = page.query_selector(sel)
                if apply_btn:
                    apply_btn.click(timeout=3000)
                    page.wait_for_timeout(2000)
                    break

            return True
        except Exception as exc:  # noqa: BLE001
            logger.warning("[%s] could not apply search filters: %s", self.SITE_NAME, exc)
            return False

    def scrape(self, page: Page) -> List[dict]:
        url = self.config["sites"]["cbre"]["url"]
        if not safe_goto(page, url, self.timeout, self.SITE_NAME):
            return []

        page.wait_for_timeout(2000)
        diagnose_page(page, self.SITE_NAME)

        modal_opened = self._apply_filters(page)

        records: List[dict] = []
        cards = []
        for sel in CARD_SELECTORS:
            cards = page.query_selector_all(sel)
            if cards:
                break

        if not cards:
            logger.warning(
                "[%s] no deal cards found (modal_opened=%s); either the modal's "
                "Multifamily/Apply controls didn't match, or results require a "
                "broker login even after filtering", self.SITE_NAME, modal_opened
            )
            sniff_dom(page, self.SITE_NAME)
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
