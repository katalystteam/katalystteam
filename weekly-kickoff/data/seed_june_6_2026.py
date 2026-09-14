"""
Seed data from KataLYST_Market_Intelligence_June-6-2026.docx (reference output).
"""

from __future__ import annotations

from datetime import date

from models import PropertyRecord

WEEK_ENDING = date(2026, 6, 6)

NEW_LISTINGS = [
    PropertyRecord(
        address="920 Meadow Ln.",
        city="Des Moines",
        property_name="Valley Acres Apartments",
        market="DSM",
        status="LISTED",
        price=5_900_000,
        units=102,
        price_per_unit=57_843,
        price_per_sf=74.35,
        cap_rate=7.58,
        property_class="C",
        year_built=1971,
        broker="Cy Fox",
        broker_firm="CBRE",
        source="CBRE",
        listed_date=date(2026, 6, 4),
    ),
]

RECENT_SALES: list[PropertyRecord] = []

# Active statewide inventory for intelligence highlight cards
ACTIVE_INVENTORY = [
    PropertyRecord(
        address="1720 Morningside Ave.",
        city="Sioux City",
        market="Sioux City",
        status="LISTED",
        units=24,
        price_per_unit=177_083,
        property_class="A",
        broker_firm="CBRE",
        source="CBRE",
    ),
    PropertyRecord(
        address="1311 W. 1st St.",
        city="Cedar Falls",
        market="Waterloo",
        status="LISTED",
        units=23,
        price_per_unit=50_000,
        property_class="D",
        source="LoopNet",
    ),
    PropertyRecord(
        address="1015 5th Ave.",
        city="Ft. Dodge",
        property_name="Phillips Luxury Apartments",
        market="Rural",
        status="LISTED",
        units=72,
        property_class="C",
        broker_firm="Greysteel",
        source="Crexi",
    ),
]

MARKET_COMMENTARY = {
    "DSM": (
        "DSM remains the most active submarket with 11 active listings totaling 357 units. "
        "The lone new entry this week — Valley Acres Apartments at 920 Meadow Ln — is a 102-unit "
        "Class C asset priced at $5.9M ($57,843/unit, 7.58% cap rate). At that pricing, it targets "
        "the value-add buyer base and is one of the larger individual assets currently on the market "
        "statewide. CBRE continues to dominate DSM listing activity. The Ames university corridor "
        "listings from prior weeks remain unpriced and active."
    ),
    "Rural": (
        "Five rural listings remain active with 173 units and an average asking price of $82,840/unit — "
        "elevated relative to prior weeks, reflecting the Chariton Class A development at $115,385/unit "
        "anchoring the average. The Ft. Dodge 72-unit listing at 1015 5th Ave. (Greysteel) remains "
        "unpriced and continues to be the largest single rural listing by unit count. "
        "No rural sales were recorded this week."
    ),
    "Sioux City": (
        "Sioux City holds three active listings — one Class A at $177,083/unit (1720 Morningside Ave.) "
        "and two unpriced assets. No new activity this week. The Morningside listing remains the highest "
        "asking price per unit of any active listing statewide and targets institutional or exchange buyers. "
        "Market quiet otherwise."
    ),
    "Quad Cities": (
        "Three Class D listings across Davenport and Bettendorf remain active (100 units, avg $57,949/unit). "
        "All three listed by Marcus & Millichap on May 13. No closings. These assets represent the lowest "
        "quality tier in the statewide tracker — watch for price reductions as days on market extend."
    ),
    "Waterloo": (
        "Two listings remain active in Waterloo totaling 35 units. Average asking at $56,042/unit "
        "consistent with recent submarket norms. No new listings or sales. Market stable but thin — "
        "limited buyer pool relative to other submarkets."
    ),
}

SUBMARKET_ORDER = ["DSM", "Rural", "Sioux City", "Quad Cities", "Waterloo"]

NO_SALES_MESSAGE = (
    "No closings recorded this week. For most recent transaction comps, reference the "
    "May 28th, 2026 report (6 sales · 182 units · $20.9M)."
)

REPORT_OPTIONS = {
    "intelligence_mode": "active_inventory",
    "include_deal_to_watch": False,
    "include_brokers_table": False,
}
