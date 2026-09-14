#!/usr/bin/env python3
"""
Backtest the weekly kickoff pipeline against a frozen source-of-truth file.

1. Regenerates Excel + PDF from seed data
2. Computes analytics from the pipeline
3. Compares every metric, property, and broker row to source_of_truth_may_28_2026.json
4. Writes a pass/fail report to output/backtest_report.json
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import asdict
from datetime import date
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from analytics import (
    compute_broker_activity,
    compute_listing_metrics,
    compute_sales_metrics,
    compute_submarket_scorecard,
    deal_to_watch,
    intelligence_highlights,
)
from data.seed_may_28_2026 import NEW_LISTINGS, RECENT_SALES, WEEK_ENDING
from excel_export import export_workbook
from main import load_seed_data
from report.pdf_generator import generate_report

TRUTH_PATH = os.path.join(os.path.dirname(__file__), "data", "source_of_truth_may_28_2026.json")
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "output")
BACKTEST_REPORT_PATH = os.path.join(OUTPUT_DIR, "backtest_report.json")


def _load_truth() -> dict:
    with open(TRUTH_PATH) as f:
        return json.load(f)


def _check(name: str, actual: Any, expected: Any, tolerance: float = 0) -> dict:
    if expected is None:
        passed = actual is None
    elif isinstance(expected, (int, float)) and tolerance:
        passed = actual is not None and abs(actual - expected) <= tolerance
    else:
        passed = actual == expected
    return {
        "check": name,
        "expected": expected,
        "actual": actual,
        "passed": passed,
    }


def _normalize_address(addr: str) -> str:
    return addr.lower().replace(".", "").strip()


def _compare_properties(
    actual_records: list,
    expected_records: list,
    label: str,
) -> list[dict]:
    results = []
    expected_by_addr = {_normalize_address(r["address"]): r for r in expected_records}

    results.append(_check(f"{label}_count", len(actual_records), len(expected_records)))

    for record in actual_records:
        key = _normalize_address(record.address)
        exp = expected_by_addr.get(key)
        if not exp:
            results.append({
                "check": f"{label}_unexpected_{record.address}",
                "expected": "not present",
                "actual": record.address,
                "passed": False,
            })
            continue

        results.append(_check(f"{label}_{key}_units", record.units, exp["units"]))
        results.append(_check(f"{label}_{key}_price", record.price, exp.get("price")))
        results.append(_check(f"{label}_{key}_ppu", record.price_per_unit, exp.get("price_per_unit")))
        results.append(_check(f"{label}_{key}_class", record.property_class, exp["property_class"]))
        results.append(_check(f"{label}_{key}_broker", record.broker_firm, exp["broker_firm"]))

    return results


def _compare_dict(actual: dict, expected: dict, prefix: str) -> list[dict]:
    results = []
    for key, exp_val in expected.items():
        results.append(_check(f"{prefix}_{key}", actual.get(key), exp_val))
    return results


def run_backtest(regenerate: bool = True) -> dict:
    truth = _load_truth()
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    week_ending = WEEK_ENDING
    listings, sales, by_source, _ = load_seed_data(week_ending)

    excel_path = os.path.join(OUTPUT_DIR, f"weekly_kickoff_data_{week_ending.isoformat()}.xlsx")
    pdf_path = os.path.join(OUTPUT_DIR, f"KataLYST_Market_Intelligence_{week_ending.strftime('%b-%d-%Y')}.pdf")

    if regenerate:
        export_workbook(by_source, listings, sales, excel_path, scraped_on=week_ending)
        generate_report(listings, sales, week_ending, pdf_path)

    listing_m = compute_listing_metrics(listings)
    sales_m = compute_sales_metrics(sales, listings)
    scorecard = compute_submarket_scorecard(listings, sales)
    brokers = compute_broker_activity(listings, sales)
    highlights = intelligence_highlights(sales, listings)
    deal = deal_to_watch(listings, sales)

    results: list[dict] = []

    # Listing KPIs
    lm = truth["listing_metrics"]
    results.append(_check("listings_count", listing_m.count, lm["count"]))
    results.append(_check("listings_total_units", listing_m.total_units, lm["total_units"]))
    results.append(_check("listings_total_volume", listing_m.total_volume, lm["total_volume"]))
    results.append(_check("listings_avg_units", listing_m.avg_units, lm["avg_units"]))
    results.append(_check("listings_median_units", listing_m.median_units, lm["median_units"]))
    results.append(_check("listings_avg_vintage", listing_m.avg_vintage, lm["avg_vintage"], tolerance=1))
    results.append(_check("listings_avg_ppu", listing_m.avg_price_per_unit, lm["avg_price_per_unit"], tolerance=1))
    results.append(_check("listings_avg_ppsf", listing_m.avg_price_per_sf, lm["avg_price_per_sf"], tolerance=0.1))
    results.extend(_compare_dict(listing_m.by_market, lm["by_market"], "listings_market"))
    for key, exp_val in lm["avg_list_per_unit_by_market"].items():
        actual_val = listing_m.avg_list_per_unit_by_market.get(key)
        if actual_val is not None:
            actual_val = int(actual_val)
        results.append(_check(f"listings_avg_ppu_market_{key}", actual_val, exp_val, tolerance=2))
    results.extend(_compare_dict(listing_m.unit_size_distribution, lm["unit_size_distribution"], "unit_size"))
    results.extend(_compare_dict(listing_m.vintage_distribution, lm["vintage_distribution"], "vintage"))

    # Sales KPIs
    sm = truth["sales_metrics"]
    results.append(_check("sales_count", sales_m.count, sm["count"]))
    results.append(_check("sales_total_units", sales_m.total_units, sm["total_units"]))
    results.append(_check("sales_total_volume", sales_m.total_volume, sm["total_volume"]))
    results.append(_check("sales_avg_units", sales_m.avg_units, sm["avg_units"]))
    results.append(_check("sales_median_units", sales_m.median_units, sm["median_units"]))
    results.append(_check("sales_avg_vintage", sales_m.avg_vintage, sm["avg_vintage"], tolerance=1))
    results.append(_check("sales_avg_ppu", sales_m.avg_price_per_unit, sm["avg_price_per_unit"], tolerance=1))
    results.append(_check("sale_list_ratio", sales_m.sale_list_ratio, sm["sale_list_ratio"], tolerance=0.1))

    # Scorecard
    for exp_row in truth["submarket_scorecard"]:
        actual_row = next((r for r in scorecard if r.market == exp_row["market"]), None)
        mkt = exp_row["market"]
        if not actual_row:
            results.append({"check": f"scorecard_{mkt}", "expected": exp_row, "actual": None, "passed": False})
            continue
        results.append(_check(f"scorecard_{mkt}_listings", actual_row.listings, exp_row["listings"]))
        results.append(_check(f"scorecard_{mkt}_sales", actual_row.sales, exp_row["sales"]))
        results.append(_check(f"scorecard_{mkt}_list_units", actual_row.list_units, exp_row["list_units"]))
        results.append(_check(f"scorecard_{mkt}_sold_units", actual_row.sold_units, exp_row["sold_units"]))
        if exp_row["avg_list_per_unit"] is not None:
            results.append(_check(
                f"scorecard_{mkt}_avg_list_ppu", actual_row.avg_list_per_unit,
                exp_row["avg_list_per_unit"], tolerance=1,
            ))
        if exp_row["avg_sold_per_unit"] is not None:
            results.append(_check(
                f"scorecard_{mkt}_avg_sold_ppu", actual_row.avg_sold_per_unit,
                exp_row["avg_sold_per_unit"], tolerance=1,
            ))

    # Brokers
    for exp_b in truth["brokers_active"]:
        actual_b = next((b for b in brokers if b.firm == exp_b["firm"]), None)
        firm = exp_b["firm"]
        if not actual_b:
            results.append({"check": f"broker_{firm}", "expected": exp_b, "actual": None, "passed": False})
            continue
        results.append(_check(f"broker_{firm}_listings", actual_b.listings, exp_b["listings"]))
        results.append(_check(f"broker_{firm}_sales", actual_b.sales, exp_b["sales"]))
        results.append(_check(f"broker_{firm}_role", actual_b.role, exp_b["role"]))

    # Property-level
    results.extend(_compare_properties(listings, truth["listings"], "listing"))
    results.extend(_compare_properties(sales, truth["sales"], "sale"))

    # Intelligence highlights
    ih = truth["intelligence_highlights"]
    ls = highlights.get("largest_sale")
    results.append(_check("highlight_largest_sale", ls.address if ls else None, ih["largest_sale_address"]))
    hp = highlights.get("highest_ppu")
    results.append(_check("highlight_highest_ppu", hp.address if hp else None, ih["highest_ppu_address"]))
    lp = highlights.get("lowest_ppu")
    results.append(_check("highlight_lowest_ppu", lp.address if lp else None, ih["lowest_ppu_address"]))
    ll = highlights.get("largest_listing")
    results.append(_check("highlight_largest_listing", ll.address if ll else None, ih["largest_listing_address"]))
    results.append(_check("deal_to_watch", deal["title"], ih["deal_to_watch"]))

    # Output files
    results.append(_check("excel_exists", os.path.isfile(excel_path), True))
    results.append(_check("pdf_exists", os.path.isfile(pdf_path), True))

    page_count = None
    if os.path.isfile(pdf_path):
        proc = subprocess.run(
            ["mdls", "-name", "kMDItemNumberOfPages", pdf_path],
            capture_output=True, text=True,
        )
        if proc.returncode == 0 and "=" in proc.stdout:
            page_count = int(proc.stdout.split("=")[1].strip())
    results.append(_check("pdf_page_count", page_count, truth["pdf_expectations"]["page_count"]))

    passed = sum(1 for r in results if r["passed"])
    failed = sum(1 for r in results if not r["passed"])
    total = len(results)

    report = {
        "report_id": truth["report_id"],
        "reference_pdf": truth["reference_pdf"],
        "week_ending": truth["week_ending"],
        "generated_excel": excel_path,
        "generated_pdf": pdf_path,
        "summary": {
            "total_checks": total,
            "passed": passed,
            "failed": failed,
            "pass_rate": round(passed / total * 100, 1) if total else 0,
            "status": "PASS" if failed == 0 else "FAIL",
        },
        "failures": [r for r in results if not r["passed"]],
        "all_checks": results,
    }

    with open(BACKTEST_REPORT_PATH, "w") as f:
        json.dump(report, f, indent=2)

    return report


def print_report(report: dict) -> None:
    s = report["summary"]
    print(f"\n{'='*60}")
    print(f"BACKTEST: {report['report_id']}")
    print(f"Source of truth: {report['reference_pdf']}")
    print(f"{'='*60}")
    print(f"Status: {s['status']}  ({s['passed']}/{s['total_checks']} checks passed, {s['pass_rate']}%)")
    print(f"Generated PDF:  {report['generated_pdf']}")
    print(f"Generated Excel: {report['generated_excel']}")
    print(f"Report JSON:     output/backtest_report.json")

    if report["failures"]:
        print(f"\n--- FAILURES ({len(report['failures'])}) ---")
        for f in report["failures"]:
            print(f"  ✗ {f['check']}: expected {f['expected']}, got {f['actual']}")
    else:
        print("\nAll checks passed. Generated document matches source of truth.")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Backtest weekly kickoff against source of truth")
    parser.add_argument("--no-regenerate", action="store_true", help="Skip regenerating files")
    args = parser.parse_args()
    report = run_backtest(regenerate=not args.no_regenerate)
    print_report(report)
    sys.exit(0 if report["summary"]["status"] == "PASS" else 1)
