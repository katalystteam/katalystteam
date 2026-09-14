#!/usr/bin/env python3
"""Iowa Multifamily Property Aggregator.

Launches Playwright, visits each configured commercial real-estate
site, scrapes Iowa multifamily listings, normalizes and de-duplicates
the results, and writes output/properties.csv. One site failing never
stops the others -- each scraper is isolated and logged independently.
"""
from __future__ import annotations

import json
import logging
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import List

import pandas as pd
from playwright.sync_api import sync_playwright

from scrapers.cbre import CbreScraper
from scrapers.crexi import CrexiScraper
from scrapers.jll import JllScraper
from scrapers.loopnet import LoopnetScraper
from scrapers.marcus import MarcusScraper
from scrapers.normalize import CSV_COLUMNS
from scrapers.ollama_helper import OllamaExtractor

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")
LOG_DIR = os.path.join(BASE_DIR, "logs")
OUTPUT_DIR = os.path.join(BASE_DIR, "output")

# Strictly the 5 sites named in the project spec -- no other sources.
SCRAPER_CLASSES = {
    "crexi": CrexiScraper,
    "loopnet": LoopnetScraper,
    "cbre": CbreScraper,
    "marcus": MarcusScraper,
    "jll": JllScraper,
}


def setup_logging() -> logging.Logger:
    os.makedirs(LOG_DIR, exist_ok=True)
    logger = logging.getLogger("scraper")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()

    file_handler = logging.FileHandler(os.path.join(LOG_DIR, "scraper.log"))
    file_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    logger.addHandler(file_handler)

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    logger.addHandler(console_handler)

    return logger


def load_config() -> dict:
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def run_site(site_key: str, cls, browser, config: dict, ollama: OllamaExtractor) -> List[dict]:
    if not config["sites"].get(site_key, {}).get("enabled", True):
        return []
    scraper = cls(browser, config, ollama)
    return scraper.run()


def dedupe(records: List[dict]) -> List[dict]:
    seen = set()
    unique = []
    for r in records:
        key = r.get("listing_url") or (r.get("property_name", ""), r.get("address", ""), r.get("source", ""))
        if key in seen:
            continue
        seen.add(key)
        unique.append(r)
    return unique


def export_csv(records: List[dict], logger: logging.Logger) -> str:
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    csv_path = os.path.join(OUTPUT_DIR, "properties.csv")
    tmp_path = csv_path + ".tmp"

    df = pd.DataFrame(records, columns=CSV_COLUMNS)
    try:
        df.to_csv(tmp_path, index=False)
        os.replace(tmp_path, csv_path)  # atomic swap protects a good file from a partial write
    except Exception as exc:  # noqa: BLE001
        logger.error("CSV export failed: %s", exc)
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise
    return csv_path


def maybe_send_email_report(config: dict, csv_path: str, total: int, logger: logging.Logger) -> None:
    email_cfg = config.get("email_report", {})
    if not email_cfg.get("enabled"):
        return
    import smtplib
    from email.message import EmailMessage

    msg = EmailMessage()
    msg["Subject"] = f"Iowa Multifamily Aggregator - {total} listings - {datetime.now():%Y-%m-%d}"
    msg["From"] = email_cfg["from_addr"]
    msg["To"] = ", ".join(email_cfg["to_addrs"])
    msg.set_content(f"Run completed at {datetime.now():%Y-%m-%d %H:%M:%S}.\n{total} listings exported to {csv_path}.")

    try:
        with smtplib.SMTP(email_cfg["smtp_host"], email_cfg["smtp_port"]) as server:
            server.starttls()
            server.login(email_cfg["username"], email_cfg["password"])
            server.send_message(msg)
        logger.info("Email report sent to %s", msg["To"])
    except Exception as exc:  # noqa: BLE001
        logger.error("Email report failed: %s", exc)


def main() -> None:
    logger = setup_logging()
    config = load_config()

    if os.environ.get("SCRAPER_DISABLE_OLLAMA") == "1":
        # Set by the GitHub Actions workflow: hosted runners have no local
        # Ollama daemon and no GPU, so the LLM fallback is skipped in CI --
        # the run falls back to deterministic parsing only.
        config.setdefault("ollama", {})["enabled"] = False
        logger.info("SCRAPER_DISABLE_OLLAMA=1 - running with deterministic parsing only, no LLM fallback")

    if os.environ.get("SCRAPER_HEADLESS") in ("true", "false"):
        config["headless"] = os.environ["SCRAPER_HEADLESS"] == "true"

    ollama = OllamaExtractor(config)

    if config.get("ollama", {}).get("enabled"):
        logger.info(
            "Ollama fallback extraction enabled (model=%s). Only used when a "
            "field can't be parsed deterministically.", config["ollama"]["model"]
        )

    all_records: List[dict] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=config.get("headless", True),
            args=["--disable-blink-features=AutomationControlled"],
        )
        try:
            if config.get("parallel"):
                with ThreadPoolExecutor(max_workers=len(SCRAPER_CLASSES)) as executor:
                    futures = {
                        executor.submit(run_site, key, cls, browser, config, ollama): key
                        for key, cls in SCRAPER_CLASSES.items()
                    }
                    for future in as_completed(futures):
                        site_key = futures[future]
                        try:
                            all_records.extend(future.result())
                        except Exception as exc:  # noqa: BLE001
                            logger.error("[%s] site crashed outside retry wrapper: %s", site_key, exc)
            else:
                for key, cls in SCRAPER_CLASSES.items():
                    try:
                        all_records.extend(run_site(key, cls, browser, config, ollama))
                    except Exception as exc:  # noqa: BLE001
                        logger.error("[%s] site crashed outside retry wrapper: %s", key, exc)
        finally:
            browser.close()

    before = len(all_records)
    deduped = dedupe(all_records)
    logger.info("Collected %d raw listings, %d after de-duplication", before, len(deduped))

    csv_path = export_csv(deduped, logger)
    logger.info("Listings exported: %d rows written to %s", len(deduped), csv_path)

    maybe_send_email_report(config, csv_path, len(deduped), logger)

    print(f"Done. {len(deduped)} listings written to {csv_path}. See logs/scraper.log for details.")


if __name__ == "__main__":
    main()
