"""Snapshot generated report metrics into a source-of-truth JSON file."""

from __future__ import annotations

import json
import os
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from analytics import (
    compute_broker_activity,
    compute_listing_metrics,
    compute_sales_metrics,
    compute_submarket_scorecard,
    deal_to_watch,
    intelligence_highlights,
)
from models import PropertyRecord


def record_to_dict(r: PropertyRecord) -> dict:
    return {
        "address": r.address,
        "city": r.city,
        "units": r.units,
        "price": r.price,
        "price_per_unit": r.price_per_unit,
        "price_per_sf": r.price_per_sf,
        "property_class": r.property_class,
        "broker_firm": r.broker_firm,
        "source": r.source,
    }


def snapshot(week_ending: date, listings: list[PropertyRecord], sales: list[PropertyRecord], output_path: str) -> str:
    lm = compute_listing_metrics(listings)
    sm = compute_sales_metrics(sales, listings)
    scorecard = compute_submarket_scorecard(listings, sales)
    brokers = compute_broker_activity(listings, sales)
    highlights = intelligence_highlights(sales, listings)
    deal = deal_to_watch(listings, sales)

    truth = {
        "report_id": f"KataLYST_Market_Intelligence_{week_ending.strftime('%b-%d-%Y')}",
        "week_ending": week_ending.isoformat(),
        "listing_metrics": {
            "count": lm.count,
            "total_units": lm.total_units,
            "total_volume": lm.total_volume,
            "avg_units": lm.avg_units,
            "median_units": lm.median_units,
            "avg_vintage": lm.avg_vintage,
            "avg_price_per_unit": lm.avg_price_per_unit,
            "avg_price_per_sf": lm.avg_price_per_sf,
            "by_market": lm.by_market,
            "avg_list_per_unit_by_market": {k: int(v) for k, v in lm.avg_list_per_unit_by_market.items() if v},
            "unit_size_distribution": lm.unit_size_distribution,
            "vintage_distribution": lm.vintage_distribution,
        },
        "sales_metrics": {
            "count": sm.count,
            "total_units": sm.total_units,
            "total_volume": sm.total_volume,
            "avg_units": sm.avg_units,
            "median_units": sm.median_units,
            "avg_vintage": sm.avg_vintage,
            "avg_price_per_unit": sm.avg_price_per_unit,
            "sale_list_ratio": sm.sale_list_ratio,
            "by_market": sm.by_market,
            "avg_sold_per_unit_by_market": {k: int(v) for k, v in sm.avg_sold_per_unit_by_market.items() if v},
        },
        "submarket_scorecard": [
            {
                "market": r.market,
                "listings": r.listings,
                "sales": r.sales,
                "list_units": r.list_units,
                "sold_units": r.sold_units,
                "avg_list_per_unit": r.avg_list_per_unit,
                "avg_sold_per_unit": r.avg_sold_per_unit,
            }
            for r in scorecard
        ],
        "brokers_active": [
            {"firm": b.firm, "listings": b.listings, "sales": b.sales, "role": b.role}
            for b in brokers
        ],
        "listings": [record_to_dict(l) for l in listings],
        "sales": [record_to_dict(s) for s in sales],
        "intelligence_highlights": {
            "deal_to_watch": deal["title"],
            "largest_sale_address": highlights.get("largest_sale").address if highlights.get("largest_sale") else None,
            "largest_listing_address": highlights.get("largest_listing").address if highlights.get("largest_listing") else None,
        },
    }

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(truth, f, indent=2)
    return output_path
