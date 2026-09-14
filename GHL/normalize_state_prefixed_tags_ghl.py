"""
Rewrite GoHighLevel contact tags: non-Texas *state-prefixed* tags become ``iowa - …``.

Only tags shaped like ``<state token> - <rest>`` (space-hyphen-space) are changed.

Examples:

- ``Arizona - KWRI`` → ``iowa - KWRI``
- ``texas - KWRI`` / ``Texas - KWRI`` → unchanged
- ``Iowa - KWRI`` / ``IA - KWRI`` → unchanged (already Iowa)
- ``non-iowa - KWRI`` (legacy) → ``iowa - KWRI``

Unknown prefixes (e.g. ``Buyer - VIP``) are left as-is so arbitrary tags are not rewritten.

Uses deprecated but still supported ``GET /contacts/`` pagination (``locationId``, ``limit``,
``startAfter``, ``startAfterId``).

Environment: ``GHL_API_TOKEN``, ``GHL_LOCATION_ID``

  python3 normalize_state_prefixed_tags_ghl.py --dry-run
  python3 normalize_state_prefixed_tags_ghl.py --limit-contacts 50
"""

from __future__ import annotations

import argparse
import csv
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

from update_contact_tags import (
    MAX_TAGS_PER_BULK,
    add_tags_contact,
    remove_tags_contact,
)

logger = logging.getLogger(__name__)

GHL_BASE_URL = os.environ.get("GHL_BASE_URL", "https://services.leadconnectorhq.com")
GHL_API_VERSION = "2021-07-28"
PAGE_LIMIT = 100
REQUEST_DELAY_SEC = 0.35


# USPS abbreviation -> full name (same source as rewrite_audience_tags_by_state.py)
US_STATE_NAMES: dict[str, str] = {
    "AL": "Alabama",
    "AK": "Alaska",
    "AZ": "Arizona",
    "AR": "Arkansas",
    "CA": "California",
    "CO": "Colorado",
    "CT": "Connecticut",
    "DE": "Delaware",
    "DC": "District of Columbia",
    "FL": "Florida",
    "GA": "Georgia",
    "HI": "Hawaii",
    "ID": "Idaho",
    "IL": "Illinois",
    "IN": "Indiana",
    "IA": "Iowa",
    "KS": "Kansas",
    "KY": "Kentucky",
    "LA": "Louisiana",
    "ME": "Maine",
    "MD": "Maryland",
    "MA": "Massachusetts",
    "MI": "Michigan",
    "MN": "Minnesota",
    "MS": "Mississippi",
    "MO": "Missouri",
    "MT": "Montana",
    "NE": "Nebraska",
    "NV": "Nevada",
    "NH": "New Hampshire",
    "NJ": "New Jersey",
    "NM": "New Mexico",
    "NY": "New York",
    "NC": "North Carolina",
    "ND": "North Dakota",
    "OH": "Ohio",
    "OK": "Oklahoma",
    "OR": "Oregon",
    "PA": "Pennsylvania",
    "RI": "Rhode Island",
    "SC": "South Carolina",
    "SD": "South Dakota",
    "TN": "Tennessee",
    "TX": "Texas",
    "UT": "Utah",
    "VT": "Vermont",
    "VA": "Virginia",
    "WA": "Washington",
    "WV": "West Virginia",
    "WI": "Wisconsin",
    "WY": "Wyoming",
}


def _build_state_prefix_lookup() -> frozenset[str]:
    """Lowercase tokens that count as a U.S. state / DC place prefix (abbr + full name)."""
    tokens: set[str] = set()
    for abbr, full in US_STATE_NAMES.items():
        tokens.add(abbr.lower())
        tokens.add(full.lower())
    return frozenset(tokens)


STATE_PREFIXES = _build_state_prefix_lookup()
TEXAS_PREFIXES = frozenset({"texas", "tx"})
IOWA_PREFIXES = frozenset({"iowa", "ia"})
NON_IOWA_LEGACY = frozenset({"non-iowa", "non iowa"})


def _headers() -> dict[str, str]:
    token = os.environ.get("GHL_API_TOKEN", "")
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Version": GHL_API_VERSION,
    }


def normalize_state_prefixed_tag(tag: str) -> str | None:
    """
    If ``tag`` is ``<state-like prefix> - <suffix>``, return the Iowa-prefixed replacement
    when the prefix is a non-Texas state; otherwise return None (leave tag unchanged).
    """
    tl = tag.strip().lower()

    # Legacy tags from earlier runs often look like `non-iowa-kwri` (no spaces).
    # Always normalize these to `iowa - kwri`.
    if tl.startswith("non-iowa-"):
        rest = tag.strip()[len("non-iowa-") :].strip()
        return f"iowa - {rest}" if rest else None

    if " - " not in tag:
        return None
    prefix, suffix = tag.split(" - ", 1)
    prefix_l = prefix.strip().lower()
    if not prefix_l:
        return None
    rest = suffix.strip()
    if not rest:
        return None

    if prefix_l in TEXAS_PREFIXES:
        return None
    if prefix_l in IOWA_PREFIXES:
        return None
    if prefix_l in NON_IOWA_LEGACY:
        return f"iowa - {rest}"
    if prefix_l in STATE_PREFIXES and prefix_l not in TEXAS_PREFIXES:
        return f"iowa - {rest}"
    return None


def _start_after_value(contact: dict) -> int | float | None:
    """Numeric ``startAfter`` cursor from contact ``dateAdded``."""
    da = contact.get("dateAdded")
    if da is None:
        return None
    if isinstance(da, (int, float)):
        return da
    if isinstance(da, str):
        if da.isdigit():
            return int(da)
        try:
            s = da.replace("Z", "+00:00")
            dt = datetime.fromisoformat(s)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return int(dt.timestamp() * 1000)
        except ValueError:
            return None
    return None


def iter_contacts_pages(location_id: str):
    """Yield pages of contact dicts from GET /contacts/."""
    url = f"{GHL_BASE_URL}/contacts/"
    start_after: int | float | None = None
    start_after_id: str | None = None

    while True:
        params: dict = {
            "locationId": location_id,
            "limit": PAGE_LIMIT,
        }
        if start_after is not None and start_after_id:
            params["startAfter"] = start_after
            params["startAfterId"] = start_after_id

        resp = requests.get(url, headers=_headers(), params=params, timeout=60)
        resp.raise_for_status()
        data = resp.json()
        contacts = data.get("contacts") or []
        if not contacts:
            break
        yield contacts
        last = contacts[-1]
        start_after_id = last.get("id")
        start_after = _start_after_value(last)
        if start_after is None or not start_after_id:
            logger.warning(
                "Stopping pagination: missing cursor on last contact id=%s",
                start_after_id,
            )
            break
        time.sleep(REQUEST_DELAY_SEC)


def _chunked(seq: list[str], size: int) -> list[list[str]]:
    return [seq[i : i + size] for i in range(0, len(seq), size)]


def remove_tags_in_chunks(contact_id: str, tags: list[str], *, dry_run: bool) -> bool:
    for chunk in _chunked(tags, MAX_TAGS_PER_BULK):
        if not remove_tags_contact(contact_id, chunk, dry_run):
            return False
        time.sleep(REQUEST_DELAY_SEC)
    return True


def apply_tag_replacements(
    contact_id: str,
    replacements: list[tuple[str, str]],
    *,
    dry_run: bool,
    current_tags: list[str],
) -> bool:
    """Remove old tags then add new tags (per contact)."""
    to_remove = [o for o, n in replacements if o != n]
    to_add = [n for o, n in replacements if o != n]
    if not to_remove:
        return True
    remaining_after_remove = set(current_tags) - set(to_remove)
    seen_add: set[str] = set()
    deduped_add: list[str] = []
    for t in to_add:
        if t in remaining_after_remove or t in seen_add:
            continue
        seen_add.add(t)
        deduped_add.append(t)
    if not remove_tags_in_chunks(contact_id, to_remove, dry_run=dry_run):
        return False
    if not deduped_add:
        return True
    if not add_tags_contact(contact_id, deduped_add, dry_run):
        return False
    return True


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )
    p = argparse.ArgumentParser(
        description="Normalize non-Texas state-prefixed GHL tags to iowa - …"
    )
    p.add_argument("--dry-run", action="store_true")
    p.add_argument(
        "--limit-contacts",
        type=int,
        default=None,
        metavar="N",
        help="Process at most N contacts (for testing)",
    )
    p.add_argument(
        "--report",
        type=Path,
        default=None,
        help="CSV path for per-tag changes (default: GHL/state_tag_normalize_report_<ts>.csv)",
    )
    args = p.parse_args(argv)

    token = os.environ.get("GHL_API_TOKEN", "")
    location_id = os.environ.get("GHL_LOCATION_ID", "")
    if not token or not location_id:
        logger.error("Set GHL_API_TOKEN and GHL_LOCATION_ID")
        return 1

    ghl_dir = Path(__file__).resolve().parent
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    report_path = args.report or (ghl_dir / f"state_tag_normalize_report_{ts}.csv")

    report_rows: list[dict[str, str]] = []
    contacts_seen = 0
    contacts_changed = 0
    failures = 0
    stop_pagination = False

    for page in iter_contacts_pages(location_id):
        if stop_pagination:
            break
        for c in page:
            if args.limit_contacts is not None and contacts_seen >= args.limit_contacts:
                stop_pagination = True
                break
            contacts_seen += 1  # 1-based count; --limit-contacts N processes N contacts
            cid = c.get("id") or ""
            email = (c.get("email") or "").strip()
            tags = list(c.get("tags") or [])
            pairs: list[tuple[str, str]] = []
            for t in tags:
                new_t = normalize_state_prefixed_tag(t)
                if new_t is not None and new_t != t:
                    pairs.append((t, new_t))
            if not pairs:
                time.sleep(REQUEST_DELAY_SEC)
                continue

            contacts_changed += 1
            for old_t, new_t in pairs:
                report_rows.append(
                    {
                        "contact_id": cid,
                        "email": email,
                        "old_tag": old_t,
                        "new_tag": new_t,
                    }
                )
            ok = apply_tag_replacements(
                cid, pairs, dry_run=args.dry_run, current_tags=tags
            )
            if not ok:
                failures += 1
                logger.error("Failed tag normalize for contact_id=%s email=%s", cid, email)
            else:
                logger.info(
                    "Updated %d tag(s) on contact_id=%s (%s)",
                    len(pairs),
                    cid,
                    email or "no-email",
                )
            time.sleep(REQUEST_DELAY_SEC)

    report_path.parent.mkdir(parents=True, exist_ok=True)
    with report_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(
            f,
            fieldnames=["contact_id", "email", "old_tag", "new_tag"],
        )
        w.writeheader()
        w.writerows(report_rows)

    logger.info(
        "Contacts scanned: %d | contacts with tag changes: %d | tag rows in report: %d | "
        "failures: %d | report: %s",
        contacts_seen,
        contacts_changed,
        len(report_rows),
        failures,
        report_path,
    )
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
