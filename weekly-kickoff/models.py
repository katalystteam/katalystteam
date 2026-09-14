"""Data models for weekly market intelligence."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Optional


@dataclass
class PropertyRecord:
    """A multifamily listing or sale record."""

    address: str
    city: str
    state: str = "IA"
    property_name: str = ""
    market: str = ""
    status: str = "LISTED"  # LISTED or SOLD
    price: Optional[float] = None
    units: Optional[int] = None
    price_per_unit: Optional[float] = None
    price_per_sf: Optional[float] = None
    cap_rate: Optional[float] = None
    property_class: str = ""
    year_built: Optional[int] = None
    broker: str = ""
    broker_firm: str = ""
    source: str = ""
    source_url: str = ""
    listed_date: Optional[date] = None
    sold_date: Optional[date] = None
    list_price: Optional[float] = None  # original ask, used for sale-to-list ratio
    notes: str = ""

    def __post_init__(self):
        if not self.market:
            self.market = classify_market(self.city)
        if self.price and self.units and not self.price_per_unit:
            self.price_per_unit = round(self.price / self.units, 2)


def classify_market(city: str) -> str:
    """Map an Iowa city to a submarket label used in the report."""
    c = city.strip().lower()
    if c in DSM_CITIES:
        return "DSM"
    if c in WATERLOO_CITIES:
        return "Waterloo"
    if c in SIOUX_CITY_CITIES:
        return "Sioux City"
    if c in IOWA_CITY_CITIES:
        return "Iowa City"
    if c in QUAD_CITIES_CITIES:
        return "Quad Cities"
    if c in RURAL_CITIES:
        return "Rural"
    # Default heuristic for unknown Iowa cities
    if "des moines" in c or "ames" in c:
        return "DSM"
    return "Rural"


# Import market city sets for classify_market
from config import (  # noqa: E402
    DSM_CITIES,
    IOWA_CITY_CITIES,
    QUAD_CITIES_CITIES,
    RURAL_CITIES,
    SIOUX_CITY_CITIES,
    WATERLOO_CITIES,
)
