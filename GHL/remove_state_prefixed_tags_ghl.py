"""
Normalize KWC/KWRI GHL contact tags only — all other tags are left unchanged.

Removes state-prefixed or legacy KWC/KWRI tags (e.g. ``iowa - KWRI``,
``texas - KWRI``, ``iowa - KWC - Texas``, ``iowa-kwri``) and adds bare ``KWRI``.

Other tags on the same contact (``iowa - Kickoff``, ``Buyers``, etc.) are not touched.
If a pipe-concatenated tag mixes KWRI with other tags, only the KWRI portion is
normalized; the other parts are re-added unchanged when needed.

Environment: ``GHL_API_TOKEN``, ``GHL_LOCATION_ID``

  python3 remove_state_prefixed_tags_ghl.py --dry-run
  python3 remove_state_prefixed_tags_ghl.py --limit-contacts 25
"""

from __future__ import annotations

import argparse
import csv
import logging
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path

try:
    from dotenv import load_dotenv

    load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env.local"))
    load_dotenv(
        os.path.join(
            os.path.dirname(__file__), "..", "real-estate-crm-dashboard-react", ".env.local"
        )
    )
except ImportError:
    pass

from normalize_state_prefixed_tags_ghl import (
    STATE_PREFIXES,
    iter_contacts_pages,
)
from update_contact_tags import (
    MAX_TAGS_PER_BULK,
    add_tags_contact,
    remove_tags_contact,
)

logger = logging.getLogger(__name__)

REQUEST_DELAY_SEC = 0.35
PIPE_SPLIT_RE = re.compile(r"\s*\|\s*")

LEGACY_PREFIXES = (
    "texas - ",
    "texas-",
    "iowa - ",
    "iowa-",
    "non-iowa - ",
    "non-iowa-",
    "Texas - ",
    "Texas-",
    "Iowa - ",
    "Iowa-",
)


def split_tag_atoms(tag: str) -> list[str]:
    """Split pipe-concatenated tag blobs GHL sometimes stores as one tag."""
    return [p.strip() for p in PIPE_SPLIT_RE.split(tag.strip()) if p.strip()]


def strip_state_prefixes_once(tag: str) -> tuple[bool, str]:
    t = tag.strip()
    if not t:
        return False, t
    tl = t.lower()
    for prefix in LEGACY_PREFIXES:
        if tl.startswith(prefix.lower()):
            return True, t[len(prefix) :].strip()
    if " - " in t:
        prefix, suffix = t.split(" - ", 1)
        prefix_l = prefix.strip().lower()
        rest = suffix.strip()
        if not rest:
            return False, t
        if prefix_l in STATE_PREFIXES:
            return True, rest
    return False, t


def fully_strip_state_prefixes(tag: str) -> tuple[bool, str]:
    """Recursively strip state / list prefixes until bare."""
    changed_any = False
    current = tag.strip()
    for _ in range(8):
        changed, nxt = strip_state_prefixes_once(current)
        if not changed:
            break
        changed_any = True
        current = nxt
    return changed_any, current


def is_kwc_related(tag: str) -> bool:
    return "kwc" in tag.strip().lower()


def is_kwri_atom(atom: str) -> bool:
    """True when atom is KWRI (bare or state-prefixed)."""
    t = atom.strip()
    if not t:
        return False
    if t.lower() == "kwri":
        return True
    _, stripped = fully_strip_state_prefixes(t)
    return stripped.lower() == "kwri"


def is_kwc_kwri_atom(atom: str) -> bool:
    """True only for KWC or KWRI family tags."""
    return is_kwc_related(atom) or is_kwri_atom(atom)


def needs_kwri_normalization(atom: str) -> bool:
    """True when atom should be replaced with bare KWRI (already-bare KWRI is fine)."""
    t = atom.strip()
    if not t or t.lower() == "kwri":
        return False
    return is_kwc_kwri_atom(t)


def contact_has_kwri(tags: list[str]) -> bool:
    for raw in tags:
        for atom in split_tag_atoms(raw):
            if atom.strip().lower() == "kwri":
                return True
    return False


def compute_tag_changes(tags: list[str]) -> tuple[list[str], list[str]]:
    """
    Return (tags_to_remove, tags_to_add).

    Only KWC/KWRI-related tags are changed; everything else stays as-is.
    """
    if not tags:
        return [], []

    to_remove: list[str] = []
    to_add: list[str] = []
    need_kwri = False
    existing_exact = set(tags)

    for raw in tags:
        atoms = split_tag_atoms(raw)
        kwri_atoms = [a for a in atoms if needs_kwri_normalization(a)]
        if not kwri_atoms:
            continue

        to_remove.append(raw)
        need_kwri = True

        # Re-add non-KWC/KWRI parts from pipe-concatenated tags unchanged.
        for atom in atoms:
            if needs_kwri_normalization(atom) or is_kwri_atom(atom):
                continue
            preserved = atom.strip()
            if preserved and preserved not in existing_exact and preserved not in to_add:
                to_add.append(preserved)

    if need_kwri and not contact_has_kwri(tags):
        to_add.append("KWRI")

    return to_remove, to_add


def _chunked(seq: list[str], size: int) -> list[list[str]]:
    return [seq[i : i + size] for i in range(0, len(seq), size)]


def remove_tags_in_chunks(contact_id: str, tags: list[str], *, dry_run: bool) -> bool:
    for chunk in _chunked(tags, MAX_TAGS_PER_BULK):
        if not remove_tags_contact(contact_id, chunk, dry_run):
            return False
        time.sleep(REQUEST_DELAY_SEC)
    return True


def apply_changes(
    contact_id: str,
    to_remove: list[str],
    to_add: list[str],
    *,
    dry_run: bool,
) -> bool:
    if to_remove and not remove_tags_in_chunks(contact_id, to_remove, dry_run=dry_run):
        return False
    if to_add and not add_tags_contact(contact_id, to_add, dry_run):
        return False
    return True


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )
    p = argparse.ArgumentParser(
        description="Normalize KWC/KWRI GHL tags to bare KWRI; leave other tags unchanged"
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
        help="CSV report path (default: GHL/remove_state_tags_report_<ts>.csv)",
    )
    args = p.parse_args(argv)

    token = os.environ.get("GHL_API_TOKEN", "")
    location_id = os.environ.get("GHL_LOCATION_ID", "")
    if not token or not location_id:
        logger.error("Set GHL_API_TOKEN and GHL_LOCATION_ID")
        return 1

    ghl_dir = Path(__file__).resolve().parent
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    report_path = args.report or (ghl_dir / f"normalize_kwc_kwri_report_{ts}.csv")

    report_rows: list[dict[str, str]] = []
    contacts_seen = 0
    contacts_changed = 0
    tags_removed = 0
    tags_added = 0
    failures = 0
    stop = False

    for page in iter_contacts_pages(location_id):
        if stop:
            break
        for c in page:
            if args.limit_contacts is not None and contacts_seen >= args.limit_contacts:
                stop = True
                break
            contacts_seen += 1
            cid = c.get("id") or ""
            email = (c.get("email") or "").strip()
            tags = list(c.get("tags") or [])

            to_remove, to_add = compute_tag_changes(tags)
            if not to_remove and not to_add:
                time.sleep(REQUEST_DELAY_SEC)
                continue

            contacts_changed += 1
            tags_removed += len(to_remove)
            tags_added += len(to_add)

            for t in to_remove:
                report_rows.append(
                    {
                        "contact_id": cid,
                        "email": email,
                        "action": "remove",
                        "tag": t,
                    }
                )
            for t in to_add:
                report_rows.append(
                    {
                        "contact_id": cid,
                        "email": email,
                        "action": "add",
                        "tag": t,
                    }
                )

            ok = apply_changes(cid, to_remove, to_add, dry_run=args.dry_run)
            if not ok:
                failures += 1
                logger.error("Failed for contact_id=%s email=%s", cid, email)
            else:
                logger.info(
                    "contact_id=%s (%s): remove %d, add %d",
                    cid,
                    email or "no-email",
                    len(to_remove),
                    len(to_add),
                )
            time.sleep(REQUEST_DELAY_SEC)

    report_path.parent.mkdir(parents=True, exist_ok=True)
    with report_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["contact_id", "email", "action", "tag"])
        w.writeheader()
        w.writerows(report_rows)

    logger.info(
        "Contacts scanned: %d | changed: %d | tags removed: %d | tags added: %d | "
        "failures: %d | report: %s",
        contacts_seen,
        contacts_changed,
        tags_removed,
        tags_added,
        failures,
        report_path,
    )
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
