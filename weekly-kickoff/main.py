#!/usr/bin/env python3
"""
Weekly Kickoff — automated Central Iowa multifamily market intelligence pipeline.

Flow:
  1. Scrape Crexi, LoopNet, CBRE, DealFlow, JLL, Marcus & Millichap (or use seed data)
  2. Filter properties listed/sold in the past 7 days
  3. Export multi-sheet Excel workbook (one sheet per source)
  4. Generate 6-page PDF market intelligence report

Usage:
  python main.py --week-ending 2026-06-06           # June 6 report from reference docx
  python main.py --validate                          # May 28 report from seed data
  python main.py --backtest          # Regenerate + compare against source of truth
  python main.py --scrape --week-ending 2026-06-06 --visible  # Watch browsers scrape each site
  python main.py --scrape --week-ending 2026-06-06 --headless # Background scrape
  python main.py --demo --week-ending 2026-06-06              # Scrape visibly + open all output files + backtest
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from collections import defaultdict
from datetime import date, datetime

# Ensure package imports resolve when run from weekly-kickoff/
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import OUTPUT_DIR
from data.seed_may_28_2026 import NEW_LISTINGS, RECENT_SALES, WEEK_ENDING as MAY_28_ENDING
from excel_export import export_workbook
from models import PropertyRecord
from report.pdf_generator import generate_report


def open_file(path: str) -> None:
    """Open a file in the system default app (Preview, Excel, etc.)."""
    if not os.path.isfile(path):
        print(f"  (skip open — file not found: {path})")
        return
    print(f"  Opening {path}")
    if sys.platform == "darwin":
        subprocess.run(["open", path], check=False)
    elif sys.platform == "win32":
        os.startfile(path)  # type: ignore[attr-defined]
    else:
        subprocess.run(["xdg-open", path], check=False)


def load_seed_data(week_ending: date) -> tuple[
    list[PropertyRecord],
    list[PropertyRecord],
    dict[str, list[PropertyRecord]],
    dict,
]:
    """Return listings, sales, per-source records, and report kwargs from seed data."""
    if week_ending == MAY_28_ENDING:
        from data.seed_may_28_2026 import NEW_LISTINGS, RECENT_SALES
        listings, sales = list(NEW_LISTINGS), list(RECENT_SALES)
        report_kwargs = {}
    elif week_ending == date(2026, 6, 6):
        from data.seed_june_6_2026 import (
            ACTIVE_INVENTORY,
            MARKET_COMMENTARY,
            NEW_LISTINGS,
            NO_SALES_MESSAGE,
            RECENT_SALES,
            REPORT_OPTIONS,
            SUBMARKET_ORDER,
        )
        listings, sales = list(NEW_LISTINGS), list(RECENT_SALES)
        report_kwargs = {
            "active_inventory": list(ACTIVE_INVENTORY),
            "market_commentary_override": MARKET_COMMENTARY,
            "submarket_order": SUBMARKET_ORDER,
            "report_options": REPORT_OPTIONS,
            "no_sales_message": NO_SALES_MESSAGE,
        }
    else:
        raise ValueError(f"No seed data for week ending {week_ending}")

    by_source: dict[str, list[PropertyRecord]] = defaultdict(list)
    for record in listings:
        by_source[record.source].append(record)
    for record in sales:
        by_source[record.source].append(record)
    return listings, sales, dict(by_source), report_kwargs


def run_scrapers(headless: bool = True, week_ending: date | None = None) -> dict[str, list[PropertyRecord]]:
    """Scrape all configured real estate sites."""
    from scrapers import ALL_SCRAPERS

    results: dict[str, list[PropertyRecord]] = {}
    total = len(ALL_SCRAPERS)
    for i, scraper_cls in enumerate(ALL_SCRAPERS, start=1):
        print(f"\n[{i}/{total}] Scraping {scraper_cls.source_name}...")
        if not headless:
            print(f"  → Browser tab opening for {scraper_cls.source_name}")
        scraper = scraper_cls(headless=headless, week_ending=week_ending)
        records = scraper.scrape()
        results[scraper.source_name] = records
        print(f"  → {len(records)} records")
        if records:
            for r in records[:3]:
                print(f"     · {r.address}, {r.city} — {r.status} ({r.units or '?'} units)")
            if len(records) > 3:
                print(f"     · ... and {len(records) - 3} more")
        if not headless and i < total:
            print("  → Pausing 3s before next site...")
            time.sleep(3)
    return results


def parse_week_ending(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()


def dedupe_listings(records: list[PropertyRecord]) -> list[PropertyRecord]:
    seen = set()
    out = []
    for r in records:
        key = (r.address.lower(), r.city.lower())
        if key in seen:
            continue
        seen.add(key)
        out.append(r)
    return out


def main():
    parser = argparse.ArgumentParser(description="Weekly Kickoff market intelligence pipeline")
    parser.add_argument("--validate", action="store_true", help="Use May 28, 2026 seed data for validation")
    parser.add_argument("--backtest", action="store_true", help="Regenerate report and run backtest vs source of truth")
    parser.add_argument("--scrape", action="store_true", help="Live scrape real estate sites")
    parser.add_argument("--visible", action="store_true", help="Open browser windows while scraping (watch sites load)")
    parser.add_argument("--headless", action="store_true", help="Run browser in background (no windows)")
    parser.add_argument("--open", action="store_true", help="Open generated files (Excel, PDF, JSON) in default apps")
    parser.add_argument(
        "--demo",
        action="store_true",
        help="Full visual run: visible scrape + generate reports + open all files + backtest",
    )
    parser.add_argument("--week-ending", type=str, help="Report week ending date (YYYY-MM-DD)")
    parser.add_argument("--output-dir", default=OUTPUT_DIR, help="Output directory")
    args = parser.parse_args()

    if args.demo:
        args.scrape = True
        args.visible = True
        args.open = True

    run_backtest_after = args.backtest or args.demo

    if args.backtest and not args.demo and not args.scrape:
        from backtest import BACKTEST_REPORT_PATH, print_report, run_backtest
        report = run_backtest(regenerate=True)
        print_report(report)
        if args.open:
            open_file(BACKTEST_REPORT_PATH)
        sys.exit(0 if report["summary"]["status"] == "PASS" else 1)

    if not args.validate and not args.scrape:
        args.validate = True  # default to validation mode

    os.makedirs(args.output_dir, exist_ok=True)
    report_kwargs: dict = {}
    if args.week_ending:
        week_ending = parse_week_ending(args.week_ending)
    elif args.validate:
        week_ending = MAY_28_ENDING
    else:
        week_ending = date.today()

    seed_weeks = {MAY_28_ENDING, date(2026, 6, 6)}
    use_seed = args.validate or (week_ending in seed_weeks and not args.scrape)

    if use_seed:
        print(f"=== SEED MODE: Week ending {week_ending} (reference document) ===")
        listings, sales, by_source, report_kwargs = load_seed_data(week_ending)
    else:
        print(f"=== LIVE SCRAPE MODE · Week ending {week_ending} ===")
        headless = args.headless or not args.visible
        by_source = run_scrapers(headless=headless, week_ending=week_ending)
        all_records = [r for recs in by_source.values() for r in recs]
        listings = dedupe_listings([r for r in all_records if r.status == "LISTED"])
        sales = dedupe_listings([r for r in all_records if r.status == "SOLD"])

    # Excel export
    excel_name = f"weekly_kickoff_data_{week_ending.isoformat()}.xlsx"
    excel_path = os.path.join(args.output_dir, excel_name)
    export_workbook(by_source, listings, sales, excel_path, scraped_on=week_ending)
    print(f"Excel saved: {excel_path}")
    if args.open:
        open_file(excel_path)

    # PDF report
    pdf_name = f"KataLYST_Market_Intelligence_{week_ending.strftime('%b-%d-%Y')}.pdf"
    pdf_path = os.path.join(args.output_dir, pdf_name)
    generate_report(listings, sales, week_ending, pdf_path, **report_kwargs)
    print(f"PDF saved: {pdf_path}")
    if args.open:
        open_file(pdf_path)

    # Summary
    print("\n=== REPORT SUMMARY ===")
    print(f"Week ending: {week_ending}")
    print(f"New listings: {len(listings)} ({sum(l.units or 0 for l in listings)} units)")
    print(f"Recent sales: {len(sales)} ({sum(s.units or 0 for s in sales)} units)")
    print(f"Sources: {', '.join(by_source.keys())}")

    if args.scrape:
        from snapshot_truth import snapshot
        truth_path = os.path.join(
            args.output_dir,
            f"source_of_truth_{week_ending.isoformat()}.json",
        )
        snapshot(week_ending, listings, sales, truth_path)
        print(f"Source of truth saved: {truth_path}")
        if args.open:
            open_file(truth_path)

    if run_backtest_after:
        from backtest import BACKTEST_REPORT_PATH, print_report, run_backtest
        print("\n=== BACKTEST (May 28 reference) ===")
        report = run_backtest(regenerate=True)
        print_report(report)
        if args.open:
            open_file(BACKTEST_REPORT_PATH)

    print("\nDone." + (" All output files opened." if args.open else " Open the PDF to review this week's kickoff report."))


if __name__ == "__main__":
    main()
