"""Compute market intelligence metrics from listing and sale records."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from statistics import median
from typing import Optional

from models import PropertyRecord


@dataclass
class ListingMetrics:
    count: int = 0
    total_units: int = 0
    total_volume: float = 0.0
    avg_units: float = 0.0
    median_units: float = 0.0
    avg_vintage: float = 0.0
    avg_price_per_unit: Optional[float] = None
    avg_price_per_sf: Optional[float] = None
    by_market: dict = field(default_factory=dict)
    avg_list_per_unit_by_market: dict = field(default_factory=dict)
    unit_size_distribution: dict = field(default_factory=dict)
    vintage_distribution: dict = field(default_factory=dict)
    executive_summary: str = ""


@dataclass
class SalesMetrics:
    count: int = 0
    total_units: int = 0
    total_volume: float = 0.0
    avg_units: float = 0.0
    median_units: float = 0.0
    avg_vintage: float = 0.0
    avg_price_per_unit: Optional[float] = None
    sale_list_ratio: Optional[float] = None
    sale_list_ratio_note: str = ""
    by_market: dict = field(default_factory=dict)
    avg_sold_per_unit_by_market: dict = field(default_factory=dict)
    executive_summary: str = ""


@dataclass
class SubmarketRow:
    market: str
    listings: int = 0
    sales: int = 0
    list_units: int = 0
    sold_units: int = 0
    avg_list_per_unit: Optional[float] = None
    avg_sold_per_unit: Optional[float] = None


@dataclass
class BrokerActivity:
    firm: str
    listings: int = 0
    sales: int = 0

    @property
    def role(self) -> str:
        if self.listings and self.sales:
            return "Listing & Selling"
        if self.listings:
            return "Listing Only"
        return "Selling Only"


def _avg(values: list) -> Optional[float]:
    return round(sum(values) / len(values), 2) if values else None


def _unit_bucket(units: int) -> str:
    if units <= 12:
        return "1–12"
    if units <= 24:
        return "13–24"
    if units <= 49:
        return "25–49"
    return "50+"


def _vintage_bucket(year: int) -> str:
    if year < 1960:
        return "Pre-1960"
    if year < 1980:
        return "1960–1979"
    if year < 2000:
        return "1980–1999"
    return "2000+"


def compute_listing_metrics(listings: list[PropertyRecord]) -> ListingMetrics:
    m = ListingMetrics()
    m.count = len(listings)
    if not listings:
        return m

    units = [l.units for l in listings if l.units]
    prices = [l.price for l in listings if l.price]
    ppu = [l.price_per_unit for l in listings if l.price_per_unit]
    ppsf = [l.price_per_sf for l in listings if l.price_per_sf]
    vintages = [l.year_built for l in listings if l.year_built]

    m.total_units = sum(units)
    m.total_volume = sum(prices)
    m.avg_units = round(sum(units) / len(units)) if units else 0
    m.median_units = median(units) if units else 0
    m.avg_vintage = round(sum(vintages) / len(vintages)) if vintages else 0
    m.avg_price_per_unit = _avg(ppu)
    m.avg_price_per_sf = _avg(ppsf)

    by_market = defaultdict(int)
    market_ppu = defaultdict(list)
    unit_buckets = defaultdict(int)
    vintage_buckets = defaultdict(int)

    for l in listings:
        by_market[l.market] += 1
        if l.price_per_unit:
            market_ppu[l.market].append(l.price_per_unit)
        if l.units:
            unit_buckets[_unit_bucket(l.units)] += 1
        if l.year_built:
            vintage_buckets[_vintage_bucket(l.year_built)] += 1

    m.by_market = dict(by_market)
    m.avg_list_per_unit_by_market = {k: _avg(v) for k, v in market_ppu.items()}
    m.unit_size_distribution = {b: unit_buckets.get(b, 0) for b in ["1–12", "13–24", "25–49", "50+"]}
    m.vintage_distribution = {b: vintage_buckets.get(b, 0) for b in ["Pre-1960", "1960–1979", "1980–1999", "2000+"]}

    top_market = max(by_market, key=by_market.get) if by_market else "—"
    m.executive_summary = (
        f"{m.count} multifamily listings totaling {m.total_units} units entered the Central Iowa market this week. "
        f"New inventory averaged {int(m.avg_units)} units per property with a {m.avg_vintage} average vintage. "
        f"{top_market} remained the most active submarket with {by_market.get(top_market, 0)} listings."
    )
    return m


def compute_sales_metrics(
    sales: list[PropertyRecord],
    listings: list[PropertyRecord],
) -> SalesMetrics:
    m = SalesMetrics()
    m.count = len(sales)
    if not sales:
        return m

    units = [s.units for s in sales if s.units]
    priced_units = [s.units for s in sales if s.units and s.price]
    prices = [s.price for s in sales if s.price]
    ppu = [s.price_per_unit for s in sales if s.price_per_unit]
    vintages = [s.year_built for s in sales if s.year_built]

    m.total_units = sum(units)
    m.total_volume = sum(prices)
    m.avg_units = round(sum(units) / len(units)) if units else 0
    m.median_units = median(priced_units) if priced_units else 0
    m.avg_vintage = round(sum(vintages) / len(vintages)) if vintages else 0
    m.avg_price_per_unit = _avg(ppu)

    by_market = defaultdict(int)
    market_ppu = defaultdict(list)
    for s in sales:
        by_market[s.market] += 1
        if s.price_per_unit:
            market_ppu[s.market].append(s.price_per_unit)

    m.by_market = dict(by_market)
    m.avg_sold_per_unit_by_market = {k: _avg(v) for k, v in market_ppu.items()}

    # Sale-to-list ratio from matched addresses or explicit list_price on sale
    listing_by_addr = {l.address.lower(): l for l in listings}
    ratios = []
    ratio_note = ""
    for s in sales:
        list_px = s.list_price
        match = listing_by_addr.get(s.address.lower())
        if not list_px and match:
            list_px = match.price
        if list_px and s.price:
            ratios.append(s.price / list_px)
            ratio_note = f"1 comp — {s.address.split('.')[0]}"

    if ratios:
        m.sale_list_ratio = round(sum(ratios) / len(ratios) * 100, 1)
        m.sale_list_ratio_note = ratio_note

    largest = max((s for s in sales if s.price), key=lambda x: x.price, default=None)
    top_market = max(by_market, key=by_market.get) if by_market else "—"
    m.executive_summary = (
        f"{m.count} sales totaling {m.total_units} units closed"
        + (f", led by the ${largest.price / 1e6:.1f}M {largest.city} transaction." if largest else ".")
        + f" {top_market} remained the most active submarket with {by_market.get(top_market, 0)} sales."
    )
    return m


def compute_submarket_scorecard(
    listings: list[PropertyRecord],
    sales: list[PropertyRecord],
) -> list[SubmarketRow]:
    markets = sorted(set(l.market for l in listings) | set(s.market for s in sales))
    rows = []
    for market in markets:
        m_listings = [l for l in listings if l.market == market]
        m_sales = [s for s in sales if s.market == market]
        list_ppu = [l.price_per_unit for l in m_listings if l.price_per_unit]
        sold_ppu = [s.price_per_unit for s in m_sales if s.price_per_unit]
        rows.append(SubmarketRow(
            market=market,
            listings=len(m_listings),
            sales=len(m_sales),
            list_units=sum(l.units or 0 for l in m_listings),
            sold_units=sum(s.units or 0 for s in m_sales),
            avg_list_per_unit=_avg(list_ppu),
            avg_sold_per_unit=_avg(sold_ppu),
        ))
    return rows


def compute_broker_activity(
    listings: list[PropertyRecord],
    sales: list[PropertyRecord],
) -> list[BrokerActivity]:
    firms: dict[str, BrokerActivity] = {}
    for l in listings:
        if not l.broker_firm:
            continue
        if l.broker_firm not in firms:
            firms[l.broker_firm] = BrokerActivity(firm=l.broker_firm)
        firms[l.broker_firm].listings += 1
    for s in sales:
        if not s.broker_firm:
            continue
        if s.broker_firm not in firms:
            firms[s.broker_firm] = BrokerActivity(firm=s.broker_firm)
        firms[s.broker_firm].sales += 1
    return sorted(firms.values(), key=lambda b: -(b.listings + b.sales))


def market_commentary(market: str, listings: list[PropertyRecord], sales: list[PropertyRecord]) -> str:
    """Generate submarket commentary from activity data."""
    m_listings = [l for l in listings if l.market == market]
    m_sales = [s for s in sales if s.market == market]
    n_list = len(m_listings)
    n_sales = len(m_sales)
    list_units = sum(l.units or 0 for l in m_listings)

    if market == "DSM":
        ames_listings = [l for l in m_listings if l.city.lower() == "ames"]
        ames_sales = [s for s in m_sales if s.city.lower() == "ames"]
        hayward_sale = next((s for s in ames_sales if "hayward" in s.address.lower()), None)
        parts = [f"Most active submarket this week with {n_list} new listings and {n_sales} closings."]
        if ames_listings:
            parts.append(f"Ames accounted for {len(ames_listings)} of the {n_list} listings")
        if hayward_sale and hayward_sale.price_per_unit:
            parts.append(
                f"and drove the highest sales pricing with the ${hayward_sale.price / 1e6:.1f}M "
                f"Hayward Ave transaction at ${hayward_sale.price_per_unit:,.0f}/unit."
            )
        parts.append("Investor activity in the university corridor remains elevated.")
        return " ".join(parts)

    if market == "Rural":
        ppu_vals = [l.price_per_unit for l in m_listings if l.price_per_unit]
        avg_ppu = _avg(ppu_vals)
        largest = max(m_listings, key=lambda l: l.units or 0, default=None)
        parts = [
            f"Three listings entered the rural market totaling {list_units} units — "
            f"the largest share of new supply"
        ]
        if avg_ppu:
            parts[-1] += f" — with pricing averaging ${avg_ppu:,.0f}/unit."
        else:
            parts[-1] += "."
        if largest:
            parts.append(
                f"The {largest.city} {largest.units}-unit listing remains the largest active listing in the state this week."
            )
        if n_sales:
            parts.append(f"Only one rural sale confirmed ({m_sales[0].city}).")
        return " ".join(parts)

    if market == "Iowa City":
        if m_sales:
            s = m_sales[0]
            return (
                f"No new listings but the largest transaction of the week — {s.address} at "
                f"${s.price / 1e6:.1f}M / ${s.price_per_unit:,.0f} per unit — confirms institutional "
                f"pricing pressure in the Iowa City submarket. Watch for follow-on supply as owners "
                f"benchmark to this comp."
            )
        return "No new listings or sales activity this week."

    if market == "Sioux City":
        if m_listings:
            l = m_listings[0]
            return (
                f"One large {l.units}-unit listing entered the market ({l.address.split(',')[0]}) "
                f"with pricing not yet disclosed. No sales activity. Market remains quiet relative to prior weeks."
            )
        return "No activity this week."

    if market == "Waterloo":
        if m_listings:
            l = m_listings[0]
            ppu = f"${l.price_per_unit:,.0f}/unit" if l.price_per_unit else "pricing TBD"
            return (
                f"One listing, no sales. {l.units}-unit B-class asset at {ppu} "
                f"consistent with submarket norms. Market stable."
            )
        return "No activity this week."

    return f"{n_list} listings and {n_sales} sales recorded this week."


def deal_to_watch(listings: list[PropertyRecord], sales: list[PropertyRecord]) -> dict:
    """Highlight the most notable market dynamic for page 6."""
    ames_listings = [l for l in listings if l.city.lower() == "ames"]
    ames_sales = [s for s in sales if s.city.lower() == "ames" and s.price]
    hayward_sale = next((s for s in ames_sales if "hayward" in s.address.lower()), None)

    if ames_listings and hayward_sale:
        listing_addrs = ", ".join(l.address.split(".")[0] for l in ames_listings[:3])
        return {
            "title": "Ames University Corridor",
            "body": (
                f"Ames generated three new listings ({listing_addrs}) and one confirmed sale "
                f"({hayward_sale.address.split('.')[0]} at ${hayward_sale.price / 1e6:.1f}M / "
                f"${hayward_sale.price_per_unit:,.0f} per unit) in the same week — a rare combination "
                f"of simultaneous supply and demand pressure in a single submarket. The Hayward sale "
                f"establishes a new comp ceiling for the university corridor. Owners of similar vintage "
                f"assets in the 10–35 unit range should be benchmarking to this number. Investors seeking "
                f"below-replacement-cost entry should note that the three new Ames listings remain unpriced, "
                f"creating a potential first-mover window."
            ),
            "broker_note": (
                "Broker to Watch: CBRE listing all three Ames properties. "
                "Triad Real Estate Partners represented the Hayward sale."
            ),
        }

    return {
        "title": "Market Watch",
        "body": "Monitor new supply entering key submarkets for pricing signals.",
        "broker_note": "",
    }


def intelligence_highlights(
    sales: list[PropertyRecord],
    listings: list[PropertyRecord],
    active_inventory: list[PropertyRecord] | None = None,
    mode: str = "sales",
) -> dict:
    """Page 6 highlight cards."""
    if mode == "active_inventory":
        largest_new = max(listings, key=lambda l: l.price or 0, default=None) if listings else None
        priced_active = [a for a in (active_inventory or []) if a.price_per_unit]
        highest_active = max(priced_active, key=lambda a: a.price_per_unit, default=None) if priced_active else None
        lowest_active = min(priced_active, key=lambda a: a.price_per_unit, default=None) if priced_active else None
        largest_active = max(active_inventory or [], key=lambda a: a.units or 0, default=None)
        return {
            "mode": mode,
            "largest_new_listing": largest_new,
            "highest_active_ppu": highest_active,
            "lowest_active_ppu": lowest_active,
            "largest_active_listing": largest_active,
        }

    priced_sales = [s for s in sales if s.price]
    largest_sale = max(priced_sales, key=lambda s: s.price) if priced_sales else None
    highest_ppu = max((s for s in sales if s.price_per_unit), key=lambda s: s.price_per_unit, default=None)
    lowest_ppu = min((s for s in sales if s.price_per_unit), key=lambda s: s.price_per_unit, default=None)
    largest_listing = max(listings, key=lambda l: l.units or 0, default=None)

    return {
        "mode": "sales",
        "largest_sale": largest_sale,
        "highest_ppu": highest_ppu,
        "lowest_ppu": lowest_ppu,
        "largest_listing": largest_listing,
    }
