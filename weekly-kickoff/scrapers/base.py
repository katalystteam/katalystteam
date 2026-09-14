"""Base scraper interface for real estate listing sites."""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from datetime import date, timedelta

from playwright.sync_api import Page, sync_playwright

from models import PropertyRecord


class BaseScraper(ABC):
    source_name: str = ""
    base_url: str = ""
    lookback_days: int = 7

    def __init__(
        self,
        headless: bool = True,
        timeout_ms: int = 60000,
        week_ending: date | None = None,
    ):
        self.headless = headless
        self.timeout_ms = timeout_ms
        self.week_ending = week_ending or date.today()

    @abstractmethod
    def parse_listings(self, page: Page) -> list[PropertyRecord]:
        """Extract property records from the loaded page."""

    def scrape(self) -> list[PropertyRecord]:
        records: list[PropertyRecord] = []
        cutoff = self.week_ending - timedelta(days=self.lookback_days)

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=self.headless)
            page = browser.new_page()
            try:
                page.goto(self.base_url, wait_until="domcontentloaded", timeout=self.timeout_ms)
                page.wait_for_timeout(8000 if not self.headless else 5000)
                records = self.parse_listings(page)
                for r in records:
                    r.source = self.source_name
                    r.source_url = self.base_url
            except Exception as exc:
                print(f"[{self.source_name}] Scrape error: {exc}")
            finally:
                browser.close()

        # Filter to Iowa multifamily listed in lookback window
        filtered = []
        for r in records:
            if r.state and r.state.upper() != "IA":
                continue
            if r.listed_date and r.listed_date < cutoff:
                continue
            filtered.append(r)
        return filtered


def parse_price(text: str) -> float | None:
    """Extract numeric price from strings like '$1,900,000' or '1.9M'."""
    if not text:
        return None
    text = text.strip().upper()
    m = re.search(r"\$?([\d,.]+)\s*M", text)
    if m:
        return float(m.group(1).replace(",", "")) * 1_000_000
    m = re.search(r"\$?([\d,]+)", text)
    if m:
        val = float(m.group(1).replace(",", ""))
        return val if val > 1000 else None
    return None


def parse_units(text: str) -> int | None:
    m = re.search(r"(\d+)\s*(?:units?|u\b)", text, re.I)
    if m:
        return int(m.group(1))
    m = re.search(r"\b(\d{1,3})\b", text)
    return int(m.group(1)) if m else None
