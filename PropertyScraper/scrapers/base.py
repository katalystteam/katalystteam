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


_BLOCK_INDICATORS = [
    "captcha", "cloudflare", "access denied", "are you a human",
    "px-captcha", "attention required", "verify you are a human",
    "request blocked", "unusual traffic", "please enable javascript",
]


def diagnose_page(page: Page, site_name: str) -> None:
    """Log what the page actually rendered -- title, final URL, whether a
    bot-block/CAPTCHA page is showing, and a short body-text snippet. This
    is the primary debugging signal when a site returns 0 cards: it tells
    us whether we hit a real (but differently-structured) results page or
    a block/interstitial, without needing a screenshot."""
    try:
        title = page.title()
        url = page.url
        body_text = page.inner_text("body")[:400].replace("\n", " ").strip()
        lower_combined = (title + " " + body_text).lower()
        hits = [kw for kw in _BLOCK_INDICATORS if kw in lower_combined]
        logger.info(
            "[%s] diagnostic - url=%s title=%r block_indicators=%s body_snippet=%r",
            site_name, url, title, hits or "none", body_text,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("[%s] diagnostic capture failed: %s", site_name, exc)


_SNIFF_CANDIDATES = [
    "article",
    "li[class*='result' i]",
    "[class*='card' i]",
    "[class*='listing' i]",
    "[class*='property' i]",
    "[class*='property-card' i]",
    "[class*='search-result' i]",
    "a[href*='/listing']",
    "a[href*='/listings/']",
    "a[href*='/property/']",
    "a[href*='/properties/']",
    "a[href*='/Listing/']",
    "[data-testid*='card' i]",
    "[data-testid*='listing' i]",
    "[data-testid*='property' i]",
]


def sniff_dom(page: Page, site_name: str) -> None:
    """When the known card selectors find nothing, probe a broad set of
    common listing-card patterns instead of giving up blind. Logs which
    patterns actually match, how many, and a truncated HTML snippet of
    the first match for each hit -- real evidence for writing correct
    selectors on the next pass, instead of guessing again."""
    try:
        for selector in _SNIFF_CANDIDATES:
            try:
                elements = page.query_selector_all(selector)
            except Exception:  # noqa: BLE001 - a malformed selector on this DOM shouldn't stop the sweep
                continue
            if not elements:
                continue
            try:
                sample = elements[0].evaluate("el => el.outerHTML")[:500]
            except Exception:  # noqa: BLE001
                sample = "<could not read outerHTML>"
            logger.info(
                "[%s] sniff hit - selector=%r count=%d sample=%r",
                site_name, selector, len(elements), sample,
            )
    except Exception as exc:  # noqa: BLE001
        logger.warning("[%s] DOM sniff failed: %s", site_name, exc)


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
        # Fingerprint hardening: a plain headless Chromium context leaves
        # tells (navigator.webdriver=true, no plugins, no proper
        # Accept-Language/timezone) that basic bot-detection checks for
        # directly. None of this touches source IP -- it cannot help
        # against IP-reputation blocking (see README "Known limitations"),
        # but it's legitimate and worth ruling out before assuming a
        # result is an IP block rather than a fingerprint check.
        context = self.browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1440, "height": 900},
            locale="en-US",
            timezone_id="America/Chicago",  # Iowa
            extra_http_headers={
                "Accept-Language": "en-US,en;q=0.9",
                "Upgrade-Insecure-Requests": "1",
                "Sec-Fetch-Dest": "document",
                "Sec-Fetch-Mode": "navigate",
                "Sec-Fetch-Site": "none",
                "Sec-Fetch-User": "?1",
            },
        )
        context.add_init_script(
            """
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
            Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
            window.chrome = window.chrome || { runtime: {} };
            const originalQuery = window.navigator.permissions.query;
            window.navigator.permissions.query = (parameters) => (
                parameters.name === 'notifications'
                    ? Promise.resolve({ state: Notification.permission })
                    : originalQuery(parameters)
            );
            """
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
