"""Shared scraping infrastructure: retries, timeouts, screenshots,
and the record shape every site scraper must return."""
from __future__ import annotations

import logging
import os
import time
from datetime import datetime
from typing import Callable, List, Optional

from playwright.sync_api import Browser, Page, TimeoutError as PlaywrightTimeoutError

from scrapers.normalize import CSV_COLUMNS
from scrapers.ollama_helper import OllamaExtractor

logger = logging.getLogger("scraper")


def new_record(**kwargs) -> dict:
    record = {col: "" for col in CSV_COLUMNS}
    record["scraped_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    record.update(kwargs)
    return record


def retry(fn: Callable, retry_count: int, site_name: str, *, args=(), kwargs=None, default=None):
    """Run fn(*args, **kwargs), retrying retry_count times on any exception.
    Logs every retry attempt. Returns `default` if every attempt fails."""
    kwargs = kwargs or {}
    last_exc = None
    for attempt in range(1, retry_count + 1):
        try:
            return fn(*args, **kwargs)
        except (PlaywrightTimeoutError, Exception) as exc:  # noqa: BLE001 - scraper must survive any site failure
            last_exc = exc
            logger.warning("[%s] attempt %d/%d failed: %s", site_name, attempt, retry_count, exc)
            time.sleep(min(2 ** attempt, 10))
    logger.error("[%s] all %d attempts failed: %s", site_name, retry_count, last_exc)
    return default


def screenshot_on_failure(page: Optional[Page], site_name: str, screenshot_dir: str, enabled: bool) -> None:
    if not enabled or page is None:
        return
    try:
        os.makedirs(screenshot_dir, exist_ok=True)
        path = os.path.join(screenshot_dir, f"{site_name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png")
        page.screenshot(path=path, full_page=True)
        logger.info("[%s] failure screenshot saved to %s", site_name, path)
    except Exception as exc:  # noqa: BLE001
        logger.warning("[%s] could not save failure screenshot: %s", site_name, exc)


def safe_goto(page: Page, url: str, timeout: int, site_name: str) -> bool:
    try:
        page.goto(url, timeout=timeout, wait_until="domcontentloaded")
        return True
    except PlaywrightTimeoutError:
        logger.warning("[%s] navigation to %s timed out after %dms", site_name, url, timeout)
        return False


def safe_text(page_or_locator, selector: str) -> str:
    try:
        el = page_or_locator.query_selector(selector)
        return el.inner_text().strip() if el else ""
    except Exception:  # noqa: BLE001
        return ""


def safe_attr(page_or_locator, selector: str, attr: str) -> str:
    try:
        el = page_or_locator.query_selector(selector)
        return (el.get_attribute(attr) or "").strip() if el else ""
    except Exception:  # noqa: BLE001
        return ""


class BaseScraper:
    """Common scaffolding every site module subclasses."""

    SITE_NAME = "base"

    def __init__(self, browser: Browser, config: dict, ollama: OllamaExtractor):
        self.browser = browser
        self.config = config
        self.ollama = ollama
        self.timeout = config.get("timeout", 30000)
        self.retry_count = config.get("retry_count", 3)
        self.max_pages = config.get("max_pages_per_site", 5)
        self.screenshot_enabled = config.get("screenshot_on_failure", True)
        self.screenshot_dir = config.get("screenshot_dir", "logs/screenshots")

    def new_page(self) -> Page:
        context = self.browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1440, "height": 900},
        )
        page = context.new_page()
        page.set_default_timeout(self.timeout)
        return page

    def run(self) -> List[dict]:
        """Subclasses implement scrape(); run() wraps it with retry + logging."""
        logger.info("[%s] site started", self.SITE_NAME)
        page = None
        try:
            page = self.new_page()
            records = retry(
                self.scrape,
                self.retry_count,
                self.SITE_NAME,
                args=(page,),
                default=[],
            )
        except Exception as exc:  # noqa: BLE001 - one site's crash must not kill the run
            logger.error("[%s] unrecoverable error: %s", self.SITE_NAME, exc)
            screenshot_on_failure(page, self.SITE_NAME, self.screenshot_dir, self.screenshot_enabled)
            records = []
        else:
            if not records:
                screenshot_on_failure(page, self.SITE_NAME, self.screenshot_dir, self.screenshot_enabled)
        finally:
            if page is not None:
                try:
                    page.context.close()
                except Exception:  # noqa: BLE001
                    pass
        logger.info("[%s] site completed - %d listings found", self.SITE_NAME, len(records))
        return records

    def scrape(self, page: Page) -> List[dict]:
        raise NotImplementedError
