"""
Apply GoHighLevel contact tag updates from a file (bulk API + optional per-contact fallback).

Official API (HighLevel contacts OpenAPI):
  - Bulk: POST /contacts/bulk/tags/update/{type}   type = add | remove
    Body (UpdateTagsDTO): contacts[], tags[], locationId, optional removeAllTags (remove only)
  - Single contact add: POST /contacts/{contactId}/tags   Body: { "tags": [...] }
  - Single contact remove: DELETE /contacts/{contactId}/tags   Body: { "tags": [...] }
  - Base URL: https://services.leadconnectorhq.com
  - Header: Version: 2021-07-28
  - Auth: Bearer <Private Integration Token or OAuth token>
  - Scope: contacts.write

Limits (per HighLevel changelog / docs): up to 500 contacts and up to 50 tags per bulk request.

Environment:
  GHL_API_TOKEN    Private Integration token or OAuth access token
  GHL_LOCATION_ID  Sub-account (location) id

Examples:
  export GHL_API_TOKEN=...
  export GHL_LOCATION_ID=...

  # Same tags for every contact id (one id per line)
  python update_contact_tags.py --ids-file contacts.txt --tags "Buyer,Cold Lead" --action add

  # CSV: columns contact_id and tags (tags comma-separated in cell)
  python update_contact_tags.py --csv contacts.csv --action add

  # Dry run (no API calls)
  python update_contact_tags.py --ids-file contacts.txt --tags VIP --action add --dry-run

  # Remove all tags from listed contacts (bulk remove + removeAllTags)
  python update_contact_tags.py --ids-file contacts.txt --action remove --remove-all-tags
"""

from __future__ import annotations

import argparse
import csv
import logging
import os
import sys
import time
from collections import defaultdict

import requests

GHL_BASE_URL = os.environ.get("GHL_BASE_URL", "https://services.leadconnectorhq.com")
GHL_API_VERSION = "2021-07-28"

# Documented bulk limits
MAX_CONTACTS_PER_BULK = 500
MAX_TAGS_PER_BULK = 50
REQUEST_DELAY_SEC = 0.35

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)


def _headers() -> dict[str, str]:
    token = os.environ.get("GHL_API_TOKEN", "")
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Version": GHL_API_VERSION,
    }


def _chunked(seq: list[str], size: int) -> list[list[str]]:
    return [seq[i : i + size] for i in range(0, len(seq), size)]


def bulk_update_tags(
    *,
    action: str,
    contact_ids: list[str],
    tags: list[str],
    location_id: str,
    remove_all_tags: bool,
    dry_run: bool,
) -> tuple[int, int]:
    """
    POST /contacts/bulk/tags/update/{add|remove}
    Returns (success_batches, failed_batches).
    """
    if action not in ("add", "remove"):
        raise ValueError("action must be 'add' or 'remove'")

    path_type = "remove" if action == "remove" else "add"
    url = f"{GHL_BASE_URL}/contacts/bulk/tags/update/{path_type}"

    ok, fail = 0, 0
    id_batches = _chunked(contact_ids, MAX_CONTACTS_PER_BULK)
    tag_batches = _chunked(tags, MAX_TAGS_PER_BULK) if tags else [[]]

    for ids in id_batches:
        for tag_batch in tag_batches:
            body: dict = {
                "contacts": ids,
                "tags": tag_batch,
                "locationId": location_id,
            }
            if action == "remove" and remove_all_tags:
                body["removeAllTags"] = True

            if dry_run:
                logger.info(
                    "DRY RUN bulk %s: %d contacts, %d tags, removeAllTags=%s",
                    path_type,
                    len(ids),
                    len(tag_batch),
                    body.get("removeAllTags", False),
                )
                ok += 1
                continue

            try:
                resp = requests.post(url, headers=_headers(), json=body, timeout=60)
                resp.raise_for_status()
                data = resp.json()
                err_ct = int(data.get("errorCount", 0))
                if err_ct:
                    logger.warning("Bulk reported errorCount=%s; body snippet: %s", err_ct, data)
                ok += 1
            except requests.RequestException as e:
                fail += 1
                logger.error("Bulk tag update failed: %s", e)
                if getattr(e, "response", None) is not None:
                    logger.error("Response: %s", e.response.text)

            time.sleep(REQUEST_DELAY_SEC)

    return ok, fail


def add_tags_contact(contact_id: str, tags: list[str], dry_run: bool) -> bool:
    """POST /contacts/{contactId}/tags"""
    url = f"{GHL_BASE_URL}/contacts/{contact_id}/tags"
    if dry_run:
        logger.info("DRY RUN add tags to %s: %s", contact_id, tags)
        return True
    try:
        resp = requests.post(url, headers=_headers(), json={"tags": tags}, timeout=60)
        resp.raise_for_status()
        return True
    except requests.RequestException as e:
        logger.error("add tags failed for %s: %s", contact_id, e)
        if getattr(e, "response", None) is not None:
            logger.error("Response: %s", e.response.text)
        return False


def remove_tags_contact(contact_id: str, tags: list[str], dry_run: bool) -> bool:
    """DELETE /contacts/{contactId}/tags"""
    url = f"{GHL_BASE_URL}/contacts/{contact_id}/tags"
    if dry_run:
        logger.info("DRY RUN remove tags from %s: %s", contact_id, tags)
        return True
    try:
        resp = requests.delete(url, headers=_headers(), json={"tags": tags}, timeout=60)
        resp.raise_for_status()
        return True
    except requests.RequestException as e:
        logger.error("remove tags failed for %s: %s", contact_id, e)
        if getattr(e, "response", None) is not None:
            logger.error("Response: %s", e.response.text)
        return False


def parse_tag_list(arg: str | None, extras: list[str]) -> list[str]:
    parts: list[str] = []
    if arg:
        parts.extend(t.strip() for t in arg.split(",") if t.strip())
    parts.extend(t.strip() for t in extras if t.strip())
    # dedupe, preserve order
    seen: set[str] = set()
    out: list[str] = []
    for t in parts:
        if t not in seen:
            seen.add(t)
            out.append(t)
    return out


def load_ids_file(path: str) -> list[str]:
    with open(path, encoding="utf-8") as f:
        return [line.strip() for line in f if line.strip() and not line.strip().startswith("#")]


def load_csv_contact_ids_only(path: str) -> list[str]:
    """Read contact ids from CSV (column contact_id, contactId, or id); ignores other columns."""
    ids: list[str] = []
    with open(path, encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames:
            raise ValueError("CSV has no header row")
        fields = [h.strip() for h in reader.fieldnames]
        id_key = _pick_id_column(fields)
        if not id_key:
            raise ValueError(
                "CSV must include a contact id column named one of: contact_id, contactId, id"
            )
        for raw in reader:
            cid = (raw.get(id_key) or "").strip()
            if cid:
                ids.append(cid)
    return ids


def load_csv_rows(path: str, *, uniform_tags: list[str] | None = None) -> list[tuple[str, list[str]]]:
    """Returns list of (contact_id, tags_for_that_contact). If uniform_tags is set, each row gets those tags."""
    rows: list[tuple[str, list[str]]] = []
    with open(path, encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames:
            raise ValueError("CSV has no header row")

        fields = [h.strip() for h in reader.fieldnames]
        id_key = _pick_id_column(fields)
        tag_key = _pick_tags_column(fields)
        if not id_key:
            raise ValueError(
                "CSV must include a contact id column named one of: contact_id, contactId, id"
            )
        if uniform_tags is not None:
            for raw in reader:
                cid = (raw.get(id_key) or "").strip()
                if not cid:
                    continue
                rows.append((cid, list(uniform_tags)))
            return rows

        if not tag_key:
            raise ValueError(
                "CSV must include a tags column named one of: tags, tag, Tags — "
                "or pass --tags for the same tags on every row, or use --ids-file"
            )

        for raw in reader:
            cid = (raw.get(id_key) or "").strip()
            if not cid:
                continue
            raw_tags = (raw.get(tag_key) or "").strip()
            tags = [t.strip() for t in raw_tags.split(",") if t.strip()]
            rows.append((cid, tags))
    return rows


def _pick_id_column(fieldnames: list[str]) -> str | None:
    for candidate in ("contact_id", "contactId", "id"):
        if candidate in fieldnames:
            return candidate
    return None


def _pick_tags_column(fieldnames: list[str]) -> str | None:
    for candidate in ("tags", "tag", "Tags"):
        if candidate in fieldnames:
            return candidate
    return None


def group_by_tags(rows: list[tuple[str, list[str]]]) -> dict[tuple[str, ...], list[str]]:
    """Group contact ids that share the same tag set (order-normalized)."""
    buckets: dict[tuple[str, ...], list[str]] = defaultdict(list)
    for cid, tags in rows:
        key = tuple(sorted(set(tags)))
        buckets[key].append(cid)
    return buckets


def run_uniform_tags(
    contact_ids: list[str],
    tags: list[str],
    *,
    action: str,
    remove_all_tags: bool,
    dry_run: bool,
    location_id: str,
) -> int:
    """Same tags for all contacts — uses bulk API."""
    if action == "remove" and remove_all_tags:
        ok, fail = bulk_update_tags(
            action="remove",
            contact_ids=contact_ids,
            tags=[],
            location_id=location_id,
            remove_all_tags=True,
            dry_run=dry_run,
        )
    elif action == "remove" and not tags:
        logger.error("For remove without --remove-all-tags, supply at least one tag.")
        return 1
    elif action == "add" and not tags:
        logger.error("For add, supply at least one tag (--tags or CSV).")
        return 1
    else:
        ok, fail = bulk_update_tags(
            action=action,
            contact_ids=contact_ids,
            tags=tags,
            location_id=location_id,
            remove_all_tags=False,
            dry_run=dry_run,
        )

    logger.info("Bulk batches completed ok=%s failed=%s", ok, fail)
    return 0 if fail == 0 else 1


def run_per_row_tags(
    rows: list[tuple[str, list[str]]],
    *,
    action: str,
    dry_run: bool,
    location_id: str,
) -> int:
    """Tags differ by contact: group when possible (bulk), else single-contact calls."""
    failures = 0
    buckets = group_by_tags(rows)

    for tag_tuple, ids in buckets.items():
        tags = list(tag_tuple)
        if not tags:
            logger.warning("Skipping %d contacts with empty tags in CSV", len(ids))
            continue

        if len(ids) > 1:
            ok, fail = bulk_update_tags(
                action=action,
                contact_ids=ids,
                tags=tags,
                location_id=location_id,
                remove_all_tags=False,
                dry_run=dry_run,
            )
            failures += fail
            logger.info(
                "Grouped bulk: tags=%s contacts=%d batches_ok=%d batches_fail=%d",
                tags,
                len(ids),
                ok,
                fail,
            )
        else:
            cid = ids[0]
            if action == "add":
                if not add_tags_contact(cid, tags, dry_run):
                    failures += 1
            else:
                if not remove_tags_contact(cid, tags, dry_run):
                    failures += 1
            time.sleep(REQUEST_DELAY_SEC)

    return 1 if failures else 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Update GHL contact tags from a file")
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--ids-file", help="Text file: one contact id per line (# comments allowed)")
    src.add_argument("--csv", dest="csv_file", help="CSV with contact_id and tags columns")

    p.add_argument(
        "--tags",
        help="Comma-separated tags (same for all contacts when using --ids-file)",
    )
    p.add_argument(
        "--tag",
        action="append",
        default=[],
        metavar="NAME",
        help="Repeat to add one tag (alternative to --tags)",
    )
    p.add_argument(
        "--action",
        choices=("add", "remove"),
        required=True,
        help="Add or remove the given tags",
    )
    p.add_argument(
        "--remove-all-tags",
        action="store_true",
        help="Remove every tag from each contact (only with --action remove; uses bulk removeAllTags)",
    )
    p.add_argument("--dry-run", action="store_true", help="Log actions only; no API calls")

    args = p.parse_args(argv)

    if not os.environ.get("GHL_API_TOKEN") or not os.environ.get("GHL_LOCATION_ID"):
        logger.error("Set GHL_API_TOKEN and GHL_LOCATION_ID in the environment.")
        return 1

    location_id = os.environ.get("GHL_LOCATION_ID", "")

    if args.remove_all_tags and args.action != "remove":
        logger.error("--remove-all-tags only applies to --action remove")
        return 1

    tags = parse_tag_list(args.tags, args.tag)

    if args.ids_file:
        if args.action == "remove" and args.remove_all_tags:
            contact_ids = load_ids_file(args.ids_file)
            return run_uniform_tags(
                contact_ids,
                [],
                action="remove",
                remove_all_tags=True,
                dry_run=args.dry_run,
                location_id=location_id,
            )

        if not tags:
            logger.error("With --ids-file, provide --tags (or --tag) unless using --remove-all-tags.")
            return 1

        contact_ids = load_ids_file(args.ids_file)
        return run_uniform_tags(
            contact_ids,
            tags,
            action=args.action,
            remove_all_tags=False,
            dry_run=args.dry_run,
            location_id=location_id,
        )

    # CSV path
    if tags and args.action == "remove" and args.remove_all_tags:
        logger.error("Do not combine --remove-all-tags with --tags.")
        return 1

    if args.action == "remove" and args.remove_all_tags:
        ids = load_csv_contact_ids_only(args.csv_file)
        return run_uniform_tags(
            ids,
            [],
            action="remove",
            remove_all_tags=True,
            dry_run=args.dry_run,
            location_id=location_id,
        )

    uniform = tags if tags else None
    rows = load_csv_rows(args.csv_file, uniform_tags=uniform)
    if uniform:
        logger.info("Applying the same --tags list to every CSV row")

    return run_per_row_tags(rows, action=args.action, dry_run=args.dry_run, location_id=location_id)


if __name__ == "__main__":
    sys.exit(main())
