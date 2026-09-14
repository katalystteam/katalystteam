"""
Restore GoHighLevel contact tags from a snapshot CSV (e.g. all_ghl_contacts.csv).

The sync script writes all_ghl_contacts.csv with each contact's tags **immediately
before** that contact was modified in the same run. Use this to roll back automation.

Optional: pass --report GHL/tag_sync_report_<ts>.csv to reuse ghl_contact_id lookups
(email column) and skip search-by-email.

Environment: GHL_API_TOKEN, GHL_LOCATION_ID

Examples:
  python3 GHL/restore_tags_from_snapshot.py --dry-run
  python3 GHL/restore_tags_from_snapshot.py \\
    --snapshot ../all_ghl_contacts.csv \\
    --report GHL/tag_sync_report_20260522_203948.csv
"""

from __future__ import annotations

import argparse
import csv
import logging
import os
import sys
import time
from pathlib import Path

from sync_intersection_tags_to_ghl import find_contact_id_by_email
from update_contact_tags import (
    add_tags_contact,
    bulk_update_tags,
    remove_tags_contact,
)

logger = logging.getLogger(__name__)
LOOKUP_DELAY_SEC = 0.35


def _split_tags(cell: str) -> list[str]:
    if not cell or not str(cell).strip():
        return []
    return [t.strip() for t in str(cell).split("|") if t.strip()]


def load_snapshot(path: Path) -> dict[str, list[str]]:
    """email -> tags list"""
    out: dict[str, list[str]] = {}
    with path.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames:
            raise ValueError(f"{path}: empty CSV")
        for row in reader:
            em = (row.get("email") or row.get("Email") or "").strip().lower()
            if not em:
                continue
            tags = _split_tags(row.get("tags") or row.get("Tags") or "")
            out[em] = tags
    return out


def load_id_map(report_path: Path) -> dict[str, str]:
    """email -> ghl_contact_id"""
    m: dict[str, str] = {}
    with report_path.open(encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            em = (row.get("email") or "").strip().lower()
            cid = (row.get("ghl_contact_id") or "").strip()
            if em and cid:
                m[em] = cid
    return m


def restore_contact(
    cid: str,
    target_tags: list[str],
    *,
    dry_run: bool,
    location_id: str,
) -> bool:
    """Replace tags: remove all current, then add snapshot tags."""
    if dry_run:
        logger.info(
            "DRY RUN restore contact_id=%s → %d tag(s): %s",
            cid,
            len(target_tags),
            target_tags[:6],
        )
        return True

    _ok_b, fail_b = bulk_update_tags(
        action="remove",
        contact_ids=[cid],
        tags=[],
        location_id=location_id,
        remove_all_tags=True,
        dry_run=False,
    )
    if fail_b:
        return False
    if not target_tags:
        return True
    return add_tags_contact(cid, target_tags, dry_run=False)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )
    root = Path(__file__).resolve().parent.parent
    p = argparse.ArgumentParser(description="Restore GHL tags from snapshot CSV")
    p.add_argument(
        "--snapshot",
        type=Path,
        default=root / "all_ghl_contacts.csv",
        help="CSV with email + tags (pipe-separated), default: all_ghl_contacts.csv",
    )
    p.add_argument(
        "--report",
        type=Path,
        default=None,
        help="Optional tag_sync_report CSV for ghl_contact_id by email",
    )
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--limit", type=int, default=None, metavar="N")
    args = p.parse_args(argv)

    snapshot_path = args.snapshot.expanduser().resolve()
    if not snapshot_path.is_file():
        logger.error("Snapshot not found: %s", snapshot_path)
        return 1

    token = os.environ.get("GHL_API_TOKEN", "")
    location_id = os.environ.get("GHL_LOCATION_ID", "")
    if not args.dry_run and (not token or not location_id):
        logger.error("Set GHL_API_TOKEN and GHL_LOCATION_ID (or use --dry-run).")
        return 1

    snapshot = load_snapshot(snapshot_path)
    id_by_email = load_id_map(args.report) if args.report else {}

    emails = sorted(snapshot.keys())
    if args.limit is not None:
        emails = emails[: max(0, args.limit)]

    logger.info(
        "Restore from %s — %d contact(s); id map: %d from report",
        snapshot_path.name,
        len(emails),
        len(id_by_email),
    )

    ok_n = 0
    fail_n = 0
    for i, em in enumerate(emails, 1):
        tags = snapshot[em]
        cid = id_by_email.get(em)
        if not cid and not args.dry_run:
            cid = find_contact_id_by_email(em, location_id)
            time.sleep(LOOKUP_DELAY_SEC)
        elif not cid and args.dry_run:
            cid = "dry-run-id"

        if not cid:
            logger.warning("[%d/%d] No GHL contact for %s — skip", i, len(emails), em)
            fail_n += 1
            continue

        if restore_contact(cid, tags, dry_run=args.dry_run, location_id=location_id):
            ok_n += 1
            if i % 50 == 0:
                logger.info("[%d/%d] restored so far…", i, len(emails))
        else:
            logger.error("[%d/%d] Restore failed for %s", i, len(emails), em)
            fail_n += 1

        if not args.dry_run:
            time.sleep(LOOKUP_DELAY_SEC)

    logger.info("Done. restored=%d failed=%d", ok_n, fail_n)
    return 0 if fail_n == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
