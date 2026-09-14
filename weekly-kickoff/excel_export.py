"""Export scraped property data to a multi-sheet Excel workbook."""

from __future__ import annotations

import os
from datetime import date

import pandas as pd

from models import PropertyRecord


COLUMNS = [
    "Date Scraped",
    "Source",
    "Source URL",
    "Status",
    "Address",
    "City",
    "State",
    "Property Name",
    "Market",
    "Price",
    "Units",
    "Year Built",
    "Price Per Unit",
    "Price Per SF",
    "Cap Rate",
    "Class",
    "Broker",
    "Broker Firm",
    "Listed Date",
    "Sold Date",
    "Notes",
]


def _record_to_row(record: PropertyRecord, scraped_on: date) -> dict:
    return {
        "Date Scraped": scraped_on.isoformat(),
        "Source": record.source,
        "Source URL": record.source_url,
        "Status": record.status,
        "Address": record.address,
        "City": record.city,
        "State": record.state,
        "Property Name": record.property_name,
        "Market": record.market,
        "Price": record.price,
        "Units": record.units,
        "Year Built": record.year_built,
        "Price Per Unit": record.price_per_unit,
        "Price Per SF": record.price_per_sf,
        "Cap Rate": record.cap_rate,
        "Class": record.property_class,
        "Broker": record.broker,
        "Broker Firm": record.broker_firm,
        "Listed Date": record.listed_date.isoformat() if record.listed_date else None,
        "Sold Date": record.sold_date.isoformat() if record.sold_date else None,
        "Notes": record.notes,
    }


def export_workbook(
    records_by_source: dict[str, list[PropertyRecord]],
    all_listings: list[PropertyRecord],
    all_sales: list[PropertyRecord],
    output_path: str,
    scraped_on: date | None = None,
) -> str:
    """Write one sheet per source plus consolidated Listings, Sales, and Summary sheets."""
    scraped_on = scraped_on or date.today()
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        for source, records in records_by_source.items():
            sheet_name = source[:31]  # Excel sheet name limit
            rows = [_record_to_row(r, scraped_on) for r in records]
            df = pd.DataFrame(rows, columns=COLUMNS)
            df.to_excel(writer, sheet_name=sheet_name, index=False)

        if all_listings:
            df_list = pd.DataFrame(
                [_record_to_row(r, scraped_on) for r in all_listings], columns=COLUMNS
            )
            df_list.to_excel(writer, sheet_name="All Listings", index=False)

        if all_sales:
            df_sales = pd.DataFrame(
                [_record_to_row(r, scraped_on) for r in all_sales], columns=COLUMNS
            )
            df_sales.to_excel(writer, sheet_name="All Sales", index=False)

        summary = pd.DataFrame([
            {"Metric": "Total New Listings", "Value": len(all_listings)},
            {"Metric": "Total Listing Units", "Value": sum(l.units or 0 for l in all_listings)},
            {"Metric": "Total Recent Sales", "Value": len(all_sales)},
            {"Metric": "Total Sold Units", "Value": sum(s.units or 0 for s in all_sales)},
            {"Metric": "Sources Scraped", "Value": len(records_by_source)},
            {"Metric": "Scrape Date", "Value": scraped_on.isoformat()},
        ])
        summary.to_excel(writer, sheet_name="Summary", index=False)

    return output_path
