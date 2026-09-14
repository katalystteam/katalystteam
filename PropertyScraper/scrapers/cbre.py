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
search/filter is actually applied, rather than a login wall.

The modal's page-size control reads "Page Size 5 10 25 50 100 All" --
that enumerated-options pattern (plus the site otherwise looking like
a classic ASP.NET/webforms property, matching RCM LightBox's typical
stack) strongly suggests its Property Type/State/Country fields are
real HTML <select> elements, not JS-only custom widgets. This version
opens the modal, probes every <select> inside it and logs each one's
name/id and full option list (real evidence, not a guess), then
best-effort calls select_option() on whichever <select> has a
"Multifamily" option and whichever has an "Iowa"/"IA" option.
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

MODAL_SELECT_SCOPE = f"{ALL_FILTERS_MODAL_SELECTOR} select"
APPLY_BUTTON_SELECTORS = [
    f"{ALL_FILTERS_MODAL_SELECTOR} button:has-text('Apply')",
    f"{ALL_FILTERS_MODAL_SELECTOR} button:has-text('Search')",
    f"{ALL_FILTERS_MODAL_SELECTOR} button:has-text('Filter')",
    f"{ALL_FILTERS_MODAL_SELECTOR} button:has-text('View Results')",
]
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

    def _select_by_option_match(self, page: Page, keywords: List[str]) -> bool:
        """Find the first <select> inside the modal that has an option
        whose text matches one of `keywords` (case-insensitive), and
        select it. Returns True on success."""
        selects = page.query_selector_all(MODAL_SELECT_SCOPE)
        for sel_el in selects:
            try:
                option_texts = [
                    (opt.text_content() or "").strip()
                    for opt in sel_el.query_selector_all("option")
                ]
            except Exception:  # noqa: BLE001
                continue
            for keyword in keywords:
                match = next((t for t in option_texts if t.lower() == keyword.lower()), None)
                if match:
                    try:
                        sel_el.select_option(label=match, timeout=3000)
                        name_or_id = sel_el.get_attribute("name") or sel_el.get_attribute("id") or "?"
                        logger.info("[%s] selected %r on <select %s>", self.SITE_NAME, match, name_or_id)
                        return True
                    except Exception as exc:  # noqa: BLE001
                        logger.info("[%s] select_option(%r) failed: %s", self.SITE_NAME, match, exc)
        return False

    def _probe_modal_selects(self, page: Page) -> None:
        """Real evidence, not a guess: log every <select>'s name/id and
        full option list inside the opened modal."""
        selects = page.query_selector_all(MODAL_SELECT_SCOPE)
        logger.info("[%s] modal contains %d <select> element(s)", self.SITE_NAME, len(selects))
        for sel_el in selects:
            try:
                name_or_id = sel_el.get_attribute("name") or sel_el.get_attribute("id") or "?"
                option_texts = [(opt.text_content() or "").strip() for opt in sel_el.query_selector_all("option")]
                logger.info("[%s] <select %s> options=%s", self.SITE_NAME, name_or_id, option_texts[:20])
            except Exception as exc:  # noqa: BLE001
                logger.info("[%s] could not read a modal <select>: %s", self.SITE_NAME, exc)

    def _apply_filters(self, page: Page) -> bool:
        """Open the confirmed "All Filters" modal, probe its real <select>
        elements, and best-effort select Multifamily + Iowa. Returns True
        if the modal actually opened, so the caller knows whether to trust
        the subsequent card search or treat it as still-closed state."""
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

            logger.info("[%s] All Filters modal opened -- probing its <select> fields", self.SITE_NAME)
            self._probe_modal_selects(page)

            property_type_set = self._select_by_option_match(page, ["Multifamily", "Multi-Family", "Apartment", "Apartments"])
            state_set = self._select_by_option_match(page, ["Iowa", "IA"])
            logger.info("[%s] filter selection result: property_type_set=%s state_set=%s", self.SITE_NAME, property_type_set, state_set)

            if not (property_type_set or state_set):
                # <select>-based approach didn't match anything real --
                # fall back to the generic sniff for further evidence.
                sniff_dom(page, self.SITE_NAME)

            for sel in APPLY_BUTTON_SELECTORS:
                apply_btn = page.query_selector(sel)
                if apply_btn:
                    apply_btn.click(timeout=3000)
                    page.wait_for_timeout(2500)
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
