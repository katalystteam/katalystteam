"""Deterministic field-cleaning helpers shared by every site scraper.

These run first. The Ollama fallback (ollama_helper.py) is only invoked
when these regex/parsing paths fail to pull a value out of raw text.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Optional

from dateutil import parser as dateutil_parser

CSV_COLUMNS = [
    "source",
    "property_name",
    "address",
    "city",
    "state",
    "asking_price",
    "units",
    "cap_rate",
    "property_type",
    "broker_name",
    "broker_email",
    "date_listed",
    "listing_url",
    "scraped_at",
]

IOWA_CITIES = {
    "des moines", "cedar rapids", "davenport", "sioux city", "iowa city",
    "waterloo", "council bluffs", "ames", "west des moines", "dubuque",
    "ankeny", "urbandale", "cedar falls", "marion", "bettendorf",
    "mason city", "clinton", "burlington", "ottumwa", "fort dodge",
    "muscatine", "coralville", "johnston", "north liberty", "altoona",
    "newton", "indianola", "clive", "waukee", "pella", "oskaloosa",
    "storm lake", "spencer", "marshalltown", "boone", "fairfield",
}


def normalize_price(raw: Optional[str]) -> str:
    """'$3,500,000' / '3.5M' / 'Price: $3,500,000.00' -> '$3,500,000'"""
    if not raw:
        return ""
    text = raw.strip()
    m = re.search(r"\$?\s*([\d,]+(?:\.\d+)?)\s*([mMkK])?", text)
    if not m:
        return ""
    number_str, suffix = m.group(1), m.group(2)
    try:
        value = float(number_str.replace(",", ""))
    except ValueError:
        return ""
    if suffix and suffix.lower() == "m":
        value *= 1_000_000
    elif suffix and suffix.lower() == "k":
        value *= 1_000
    if value <= 0:
        return ""
    return f"${int(round(value)):,}"


def normalize_units(raw) -> str:
    """'180 Units' / '180' / 180 -> '180'"""
    if raw is None:
        return ""
    if isinstance(raw, (int, float)):
        return str(int(raw))
    m = re.search(r"([\d,]+)\s*(?:units?|beds?)?", str(raw), re.IGNORECASE)
    if not m:
        return ""
    digits = m.group(1).replace(",", "")
    return digits if digits.isdigit() else ""


def normalize_cap_rate(raw) -> str:
    """'5.4%' / 'Cap Rate: 5.4' / 5.4 -> '5.4'"""
    if raw is None:
        return ""
    m = re.search(r"(\d+(?:\.\d+)?)\s*%?", str(raw))
    if not m:
        return ""
    return m.group(1)


def normalize_date(raw: Optional[str]) -> str:
    """Best-effort parse of any human date string to YYYY-MM-DD. Empty on failure."""
    if not raw:
        return ""
    text = raw.strip()
    text = re.sub(r"(?i)^listed\s*(on)?:?\s*", "", text)
    try:
        dt = dateutil_parser.parse(text, fuzzy=True, default=datetime.now())
        return dt.strftime("%Y-%m-%d")
    except (ValueError, OverflowError):
        return ""


def normalize_state(raw: Optional[str]) -> str:
    if not raw:
        return "IA"
    text = raw.strip().upper()
    if text in {"IA", "IOWA"}:
        return "IA"
    return text[:2] if len(text) >= 2 else "IA"


def extract_city(address_or_text: Optional[str]) -> str:
    if not address_or_text:
        return ""
    lower = address_or_text.lower()
    for city in IOWA_CITIES:
        if city in lower:
            return city.title()
    m = re.search(r",\s*([A-Za-z\s]+),\s*IA\b", address_or_text)
    if m:
        return m.group(1).strip()
    return ""


def looks_like_iowa(text: Optional[str]) -> bool:
    if not text:
        return False
    lower = text.lower()
    if re.search(r"\biowa\b", lower) or re.search(r",\s*ia\b", lower):
        return True
    return any(city in lower for city in IOWA_CITIES)


def is_multifamily(text: Optional[str]) -> bool:
    if not text:
        return False
    lower = text.lower()
    keywords = ["multifamily", "multi-family", "multi family", "apartment"]
    return any(k in lower for k in keywords)


def within_last_n_days(date_str: str, n_days: int) -> bool:
    """True if date_str parses AND is within the last n days.
    A blank/unparseable date_str is treated as 'unknown' -> caller decides
    to keep the record per spec (date unavailable = keep, blank date)."""
    if not date_str:
        return True
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError:
        return True
    return (datetime.now() - dt).days <= n_days
