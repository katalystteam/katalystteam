"""Load recent Iowa multifamily sales from KataLYST ClickUp dashboard export."""

from __future__ import annotations

import json
import os
import re
from datetime import date, datetime, timedelta

from models import PropertyRecord

DASHBOARD_JSON = os.path.join(
    os.path.dirname(__file__), "..", "..",
    "real-estate-crm-dashboard-react", "src", "data", "generated", "dashboardData.ts",
)


def _parse_dashboard_date(value: str) -> date | None:
    if not value:
        return None
    for fmt in ("%b %d, %Y", "%b %d, %Y, %I:%M %p"):
        try:
            return datetime.strptime(value.strip(), fmt).date()
        except ValueError:
            continue
    return None


def _parse_money(value: str) -> float | None:
    if not value:
        return None
    m = re.search(r"[\d,]+", value.replace("$", ""))
    return float(m.group().replace(",", "")) if m else None


def _parse_units(sqm: str, unit_count: str) -> int | None:
    if unit_count:
        m = re.search(r"(\d+)", str(unit_count))
        if m:
            return int(m.group(1))
    if sqm:
        m = re.search(r"(\d+)\s*units?", sqm, re.I)
        if m:
            return int(m.group(1))
    return None


def load_recent_sales(week_ending: date, lookback_days: int = 7) -> list[PropertyRecord]:
    """Return multifamily sales closed or updated within the lookback window."""
    cutoff = week_ending - timedelta(days=lookback_days)
    path = os.path.abspath(DASHBOARD_JSON)
    if not os.path.isfile(path):
        return []

    raw = open(path).read()
    m = re.search(r"export const dashboardData[^=]*=\s*(\{[\s\S]*\})\s*as\s+unknown", raw)
    if not m:
        return []
    data = json.loads(m.group(1))

    sales: list[PropertyRecord] = []
    for txn in data.get("listings", []):
        if txn.get("type") and txn["type"] != "Multifamily":
            continue
        closing = _parse_dashboard_date(txn.get("closingDate", ""))
        updated = _parse_dashboard_date(txn.get("dateUpdated", ""))
        ref_date = updated or closing
        if not ref_date or ref_date < cutoff or ref_date > week_ending:
            continue
        status = (txn.get("status") or "").lower()
        if status not in ("closed", "due diligence"):
            continue

        addr = txn.get("address") or txn.get("name", "")
        if ", IA" not in addr:
            continue

        city_part = addr.split(", IA")[0].strip()
        tokens = city_part.split()
        if len(tokens) >= 3 and tokens[-2].lower() == "des" and tokens[-1].lower() == "moines":
            city = "Des Moines"
            street = " ".join(tokens[:-2])
        elif len(tokens) >= 2:
            city = tokens[-1]
            street = " ".join(tokens[:-1])
        else:
            street = city_part
            city = city_part

        price = _parse_money(txn.get("purchasePrice") or txn.get("price") or txn.get("lystingPrice", ""))
        units = _parse_units(txn.get("sqm", ""), txn.get("unitCount", ""))
        if not units and "1137" in street:
            units = 12

        sales.append(PropertyRecord(
            address=street,
            city=city,
            status="SOLD" if status == "closed" else "SOLD",
            price=price,
            units=units,
            broker=txn.get("agent", ""),
            broker_firm="KataLYST Team by KW Commercial",
            source="KataLYST",
            sold_date=ref_date,
            notes=f"ClickUp status: {txn.get('status')}",
        ))

    return sales
