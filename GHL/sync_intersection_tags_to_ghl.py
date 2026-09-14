"""
Match audience / Realnex CSV exports to GoHighLevel contacts and sync tags.

For each email in scope (union or intersection of input CSV files):

1. **Remove** from the GHL contact only tags that appear in the **master tag list**
   (every distinct tag string parsed from exports), plus common prefixed variants
   (``iowa - …``, ``iowa-…``, ``texas - …``, ``non-iowa-…``, etc.) so prior runs can
   be cleaned up.

2. **Add** tags from row **State** and merged base tags (TAGS column):
   - State is **Texas** (TX / TEXAS) → ``texas - {tag}``
   - Any other state or empty → ``iowa - {tag}``

3. Optional **import** contacts not found in GHL (``POST /contacts/``) with the same
   tags and address fields supported by the API.

CSV formats (auto-detected):

- **Audience** (Mailchimp-style): ``Email Address``, ``First Name``, ``Last Name``,
  ``State``, ``TAGS``.
- **Realnex-style**: ``Email``, ``First name``, ``Last name``, optional ``Name``,
  ``State``, optional ``TAGS`` / ``Tags``.

Writes:

- ``all_ghl_contacts.csv`` — contacts **found** in GHL (snapshot before changes).
- ``non_ghl.csv`` — emails **not** in GHL before import (or remaining if import off).

Environment: ``GHL_API_TOKEN``, ``GHL_LOCATION_ID``
"""

from __future__ import annotations

import argparse
import csv
import logging
import os
import sys
import time
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from io import StringIO
from pathlib import Path

import requests

from update_contact_tags import (
    MAX_TAGS_PER_BULK,
    add_tags_contact,
    bulk_update_tags,
    remove_tags_contact,
)

logger = logging.getLogger(__name__)

GHL_BASE_URL = os.environ.get("GHL_BASE_URL", "https://services.leadconnectorhq.com")
GHL_API_VERSION = "2021-07-28"

LOOKUP_DELAY_SEC = 0.35


def _headers() -> dict[str, str]:
    token = os.environ.get("GHL_API_TOKEN", "")
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Version": GHL_API_VERSION,
    }


def _parse_tags_cell(tags_cell: str) -> list[str]:
    if not tags_cell or not str(tags_cell).strip():
        return []
    row = list(csv.reader(StringIO(str(tags_cell).strip())))[0]
    return [c.strip() for c in row if c.strip()]


def _norm_email(s: str) -> str:
    return str(s).strip().lower()


@dataclass
class AudienceProfile:
    email: str
    first_name: str
    last_name: str
    state: str
    tags: list[str]

    def display_name(self) -> str:
        parts = [self.first_name.strip(), self.last_name.strip()]
        n = " ".join(p for p in parts if p).strip()
        return n or self.email


_CSV_ENCODINGS = ("utf-8-sig", "utf-8", "cp1252", "latin-1")


def _csv_open(path: Path):
    """Open CSV; audience exports are UTF-8, some Realnex exports are Windows-1252/latin-1."""
    last_err = None
    for enc in _CSV_ENCODINGS:
        try:
            f = path.open(encoding=enc, newline="")
            f.read(4096)
            f.seek(0)
            return f
        except UnicodeDecodeError as e:
            last_err = e
    raise last_err or UnicodeDecodeError("decode", b"", 0, 1, "no encoding worked")


def _is_xlsx_file(path: Path) -> bool:
    with path.open("rb") as f:
        return f.read(2) == b"PK"


def _read_xlsx_rows(path: Path) -> list[dict[str, str]]:
    """Read Excel (.xlsx) including files saved as .csv but still xlsx bytes."""
    import pandas as pd

    df = pd.read_excel(path, engine="openpyxl", dtype=str)
    df = df.fillna("")
    rows: list[dict[str, str]] = []
    for rec in df.to_dict(orient="records"):
        row = {str(k): str(v).strip() for k, v in rec.items()}
        if any(row.values()):
            rows.append(row)
    return rows


def _load_export_rows(path: Path) -> list[dict[str, str]]:
    if _is_xlsx_file(path):
        return _read_xlsx_rows(path)
    rows: list[dict[str, str]] = []
    with _csv_open(path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append({k: (v or "") for k, v in row.items()})
    return rows


def _detect_csv_kind(fieldnames: list[str] | None) -> str:
    """Return 'audience' or 'realnex'."""
    if not fieldnames:
        raise ValueError("CSV has no header row")
    fn = set(fieldnames)
    if "Email Address" in fn:
        return "audience"
    if "Email" in fn and ("First name" in fn or "First Name" in fn or "Name" in fn):
        return "realnex"
    raise ValueError(
        "Unrecognized CSV columns: need Mailchimp-style ('Email Address', …) "
        "or Realnex-style ('Email', 'First name' / 'Name', …)."
    )


def _read_csv_rows(path: Path) -> list[dict[str, str]]:
    rows = _load_export_rows(path)
    if not rows:
        return []
    kind = _detect_csv_kind(list(rows[0].keys()))
    if kind != "audience":
        raise ValueError(f"{path}: expected audience CSV (column 'Email Address')")
    return rows


def _read_realnex_rows(path: Path) -> list[dict[str, str]]:
    rows = _load_export_rows(path)
    if not rows:
        return []
    keys = list(rows[0].keys())
    kind = _detect_csv_kind(keys)
    if kind != "realnex":
        raise ValueError(f"{path}: expected Realnex-style CSV ('Email', …)")
    if "Email" not in keys:
        raise ValueError(f"{path}: missing 'Email' column")
    return rows


def _iter_export_rows(path: Path) -> list[dict[str, str]]:
    rows = _load_export_rows(path)
    if not rows:
        return []
    kind = _detect_csv_kind(list(rows[0].keys()))
    if kind == "audience":
        return rows
    return rows


def _row_to_profile(row: dict[str, str]) -> AudienceProfile | None:
    em = _norm_email(row.get("Email Address", ""))
    if not em:
        return None
    fn = (row.get("First Name") or "").strip()
    ln = (row.get("Last Name") or "").strip()
    if not fn and not ln and row.get("Name"):
        full = str(row.get("Name") or "").strip()
        parts = full.split(None, 1)
        fn = parts[0] if parts else ""
        ln = parts[1] if len(parts) > 1 else ""
    st = (row.get("State") or "").strip()
    tags = _parse_tags_cell(row.get("TAGS", "") or "")
    return AudienceProfile(email=em, first_name=fn, last_name=ln, state=st, tags=tags)


def _realnex_row_to_profile(row: dict[str, str]) -> AudienceProfile | None:
    em = _norm_email(row.get("Email", ""))
    if not em:
        return None
    fn = (row.get("First name") or row.get("First Name") or "").strip()
    ln = (row.get("Last name") or row.get("Last Name") or "").strip()
    if not fn and not ln and row.get("Name"):
        full = str(row.get("Name") or "").strip()
        parts = full.split(None, 1)
        fn = parts[0] if parts else ""
        ln = parts[1] if len(parts) > 1 else ""
    st = (row.get("State") or "").strip()
    tags_cell = row.get("TAGS") or row.get("Tags") or ""
    tags = _parse_tags_cell(tags_cell)
    return AudienceProfile(email=em, first_name=fn, last_name=ln, state=st, tags=tags)


def load_file_profiles(path: Path) -> dict[str, AudienceProfile]:
    out: dict[str, AudienceProfile] = {}
    for row in _read_csv_rows(path):
        p = _row_to_profile(row)
        if p:
            out[p.email] = p
    return out


def load_realnex_profiles(path: Path) -> dict[str, AudienceProfile]:
    out: dict[str, AudienceProfile] = {}
    for row in _read_realnex_rows(path):
        p = _realnex_row_to_profile(row)
        if p:
            out[p.email] = p
    return out


def _legacy_prefixes_to_strip() -> tuple[str, ...]:
    return (
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


def normalize_base_tags(tags: list[str]) -> list[str]:
    """Strip state/list prefixes so we can re-apply texas - / iowa - rules once."""
    out: list[str] = []
    seen: set[str] = set()
    for raw in tags:
        t = (raw or "").strip()
        if not t:
            continue
        lowered = t.lower()
        for prefix in _legacy_prefixes_to_strip():
            if lowered.startswith(prefix.lower()):
                t = t[len(prefix) :].strip()
                lowered = t.lower()
        if t and t not in seen:
            seen.add(t)
            out.append(t)
    return out


def load_file_profiles_auto(path: Path) -> dict[str, AudienceProfile]:
    preview = _load_export_rows(path)
    if not preview:
        return {}
    kind = _detect_csv_kind(list(preview[0].keys()))
    if kind == "audience":
        profiles = load_file_profiles(path)
    else:
        profiles = load_realnex_profiles(path)

    # import_ghl.csv is a Texas-only cohort — always apply texas - {tag}
    if path.name == "import_ghl.csv":
        forced: dict[str, AudienceProfile] = {}
        for em, p in profiles.items():
            forced[em] = AudienceProfile(
                email=p.email,
                first_name=p.first_name,
                last_name=p.last_name,
                state="TX",
                tags=normalize_base_tags(p.tags),
            )
        return forced

    return profiles


def union_merged_profiles(paths: list[Path]) -> dict[str, AudienceProfile]:
    maps = [load_file_profiles(p) for p in paths]
    all_em: set[str] = set()
    for m in maps:
        all_em |= set(m.keys())
    merged: dict[str, AudienceProfile] = {}
    for em in all_em:
        tags_merged: list[str] = []
        seen_t: set[str] = set()
        state = ""
        fn, ln = "", ""
        for m in maps:
            if em not in m:
                continue
            p = m[em]
            if not state and p.state.strip():
                state = p.state.strip()
            if not fn and p.first_name.strip():
                fn = p.first_name.strip()
            if not ln and p.last_name.strip():
                ln = p.last_name.strip()
            for t in p.tags:
                if t not in seen_t:
                    seen_t.add(t)
                    tags_merged.append(t)
        merged[em] = AudienceProfile(
            email=em,
            first_name=fn,
            last_name=ln,
            state=state,
            tags=tags_merged,
        )
    return merged


def union_merged_profiles_auto(paths: list[Path]) -> dict[str, AudienceProfile]:
    maps = [load_file_profiles_auto(p) for p in paths]
    all_em: set[str] = set()
    for m in maps:
        all_em |= set(m.keys())
    merged: dict[str, AudienceProfile] = {}
    for em in all_em:
        tags_merged: list[str] = []
        seen_t: set[str] = set()
        state = ""
        fn, ln = "", ""
        for m in maps:
            if em not in m:
                continue
            p = m[em]
            if not state and p.state.strip():
                state = p.state.strip()
            if not fn and p.first_name.strip():
                fn = p.first_name.strip()
            if not ln and p.last_name.strip():
                ln = p.last_name.strip()
            for t in p.tags:
                if t not in seen_t:
                    seen_t.add(t)
                    tags_merged.append(t)
        merged[em] = AudienceProfile(
            email=em,
            first_name=fn,
            last_name=ln,
            state=state,
            tags=tags_merged,
        )
    return merged


def intersection_merged_profiles(paths: list[Path]) -> dict[str, AudienceProfile]:
    maps = [load_file_profiles(p) for p in paths]
    common = set(maps[0].keys())
    for m in maps[1:]:
        common &= set(m.keys())
    out: dict[str, AudienceProfile] = {}
    for em in common:
        tags_merged: list[str] = []
        seen_t: set[str] = set()
        state = ""
        fn, ln = "", ""
        for m in maps:
            p = m[em]
            if not state and p.state.strip():
                state = p.state.strip()
            if not fn and p.first_name.strip():
                fn = p.first_name.strip()
            if not ln and p.last_name.strip():
                ln = p.last_name.strip()
            for t in p.tags:
                if t not in seen_t:
                    seen_t.add(t)
                    tags_merged.append(t)
        out[em] = AudienceProfile(
            email=em,
            first_name=fn,
            last_name=ln,
            state=state,
            tags=tags_merged,
        )
    return out


def intersection_merged_profiles_auto(paths: list[Path]) -> dict[str, AudienceProfile]:
    maps = [load_file_profiles_auto(p) for p in paths]
    common = set(maps[0].keys())
    for m in maps[1:]:
        common &= set(m.keys())
    out: dict[str, AudienceProfile] = {}
    for em in common:
        tags_merged: list[str] = []
        seen_t: set[str] = set()
        state = ""
        fn, ln = "", ""
        for m in maps:
            p = m[em]
            if not state and p.state.strip():
                state = p.state.strip()
            if not fn and p.first_name.strip():
                fn = p.first_name.strip()
            if not ln and p.last_name.strip():
                ln = p.last_name.strip()
            for t in p.tags:
                if t not in seen_t:
                    seen_t.add(t)
                    tags_merged.append(t)
        out[em] = AudienceProfile(
            email=em,
            first_name=fn,
            last_name=ln,
            state=state,
            tags=tags_merged,
        )
    return out


def collect_literal_tags_from_exports(paths: list[Path]) -> set[str]:
    """Every distinct tag string appearing in any CSV TAGS / Tags column."""
    literals: set[str] = set()
    for path in paths:
        for row in _iter_export_rows(path):
            cell = row.get("TAGS") or row.get("Tags") or ""
            for t in _parse_tags_cell(cell):
                literals.add(t)
                for base in normalize_base_tags([t]):
                    literals.add(base)
    return literals


def build_removal_superset(literal_tags: set[str]) -> set[str]:
    """
    Tags on a GHL contact that should be removed if present: any literal from exports,
    plus prefixed variants built from each literal as a 'base' tag name.
    """
    sup: set[str] = set(literal_tags)
    for b in literal_tags:
        sup.add(f"iowa-{b}")
        sup.add(f"iowa - {b}")
        sup.add(f"Iowa - {b}")
        sup.add(f"texas - {b}")
        sup.add(f"texas-{b}")
        sup.add(f"non-iowa-{b}")
        sup.add(f"Texas - {b}")
    return sup


def _state_to_abbr(state_raw: str) -> str:
    s = (state_raw or "").strip().upper()
    if not s:
        return ""
    if len(s) == 2:
        return s
    # Full names sometimes appear in exports
    full = {
        "IOWA": "IA",
        "TEXAS": "TX",
    }
    return full.get(s, "")


def is_texas_state(state_raw: str) -> bool:
    """True if state is Texas (TX or TEXAS). Everything else (including empty) is non-Texas."""
    abbr = _state_to_abbr(state_raw)
    if abbr == "TX":
        return True
    s = (state_raw or "").strip().upper()
    return s == "TEXAS"


def format_tags_for_state(state_raw: str, base_tags: list[str]) -> list[str]:
    """Texas → texas - {tag}; any other (including Iowa, empty) → iowa - {tag}."""
    out: list[str] = []
    for b in normalize_base_tags(base_tags):
        if not b.strip():
            continue
        if is_texas_state(state_raw):
            out.append(f"texas - {b}")
        else:
            out.append(f"iowa - {b}")
    return out


def create_ghl_contact(
    prof: AudienceProfile,
    tags: list[str],
    location_id: str,
    *,
    dry_run: bool,
) -> str | None:
    """POST /contacts/ — returns new contact id or None."""
    url = f"{GHL_BASE_URL}/contacts/"
    st_raw = (prof.state or "").strip()
    abbr = _state_to_abbr(st_raw)
    state_val = abbr if abbr else (st_raw[:50] if st_raw else "")
    body: dict = {
        "locationId": location_id,
        "email": prof.email,
        "firstName": prof.first_name or "",
        "lastName": prof.last_name or "",
        "tags": tags or [],
        "source": "sync_intersection_tags_to_ghl",
    }
    if state_val:
        body["state"] = state_val

    if dry_run:
        logger.info(
            "DRY RUN create contact %s tags=%s state=%s",
            prof.email,
            tags[:10],
            state_val or "(none)",
        )
        return "dry_run_contact_id"

    try:
        resp = requests.post(url, headers=_headers(), json=body, timeout=60)
        resp.raise_for_status()
        data = resp.json()
        contact = data.get("contact") or data
        cid = contact.get("id") if isinstance(contact, dict) else None
        if cid:
            logger.info("Imported contact %s → id=%s", prof.email, cid)
        else:
            logger.warning("Create contact missing id in response for %s", prof.email)
        return cid
    except requests.RequestException as e:
        logger.error("Create contact failed for %s: %s", prof.email, e)
        if getattr(e, "response", None) is not None:
            logger.error("Response: %s", e.response.text)
        return None


def find_contact_id_by_email(email: str, location_id: str) -> str | None:
    url = f"{GHL_BASE_URL}/contacts/"
    params: dict = {
        "locationId": location_id,
        "query": email,
        "limit": 25,
    }
    try:
        resp = requests.get(url, headers=_headers(), params=params, timeout=45)
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException as e:
        logger.error("Contact search failed for %s: %s", email, e)
        return None

    contacts = data.get("contacts") or []
    el = email.strip().lower()
    for c in contacts:
        ce = (c.get("email") or "").strip().lower()
        if ce == el:
            return c.get("id")
    return None


def get_contact(contact_id: str) -> dict | None:
    """GET /contacts/{contactId} → contact dict or None."""
    url = f"{GHL_BASE_URL}/contacts/{contact_id}"
    try:
        resp = requests.get(url, headers=_headers(), timeout=45)
        resp.raise_for_status()
        data = resp.json()
        return data.get("contact") or data.get("contacts")
    except requests.RequestException as e:
        logger.error("GET contact failed %s: %s", contact_id, e)
        return None


def ghl_display_name(c: dict) -> str:
    fn = (c.get("firstName") or "").strip()
    ln = (c.get("lastName") or "").strip()
    n = f"{fn} {ln}".strip()
    return n or (c.get("name") or "").strip() or (c.get("email") or "")


def remove_tags_in_chunks(contact_id: str, tags: list[str]) -> bool:
    """DELETE tags in chunks of MAX_TAGS_PER_BULK."""
    if not tags:
        return True
    for i in range(0, len(tags), MAX_TAGS_PER_BULK):
        chunk = tags[i : i + MAX_TAGS_PER_BULK]
        if not remove_tags_contact(contact_id, chunk, dry_run=False):
            return False
        time.sleep(LOOKUP_DELAY_SEC)
    return True


def group_by_tag_set(
    email_to_id: dict[str, str],
    email_to_new_tags: dict[str, list[str]],
) -> dict[tuple[str, ...], list[str]]:
    buckets: dict[tuple[str, ...], list[str]] = defaultdict(list)
    for em, cid in email_to_id.items():
        key = tuple(email_to_new_tags.get(em, []))
        buckets[key].append(cid)
    return dict(buckets)


def _join(tags: list[str]) -> str:
    return " | ".join(tags)


def write_split_outputs(
    *,
    out_dir: Path,
    in_ghl_rows: list[dict[str, str]],
    non_ghl_rows: list[dict[str, str]],
) -> tuple[Path, Path]:
    fields = ["name", "email", "state", "tags"]
    p1 = out_dir / "all_ghl_contacts.csv"
    p2 = out_dir / "non_ghl.csv"
    with p1.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(in_ghl_rows)
    with p2.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(non_ghl_rows)
    logger.info("Wrote %s (%d rows)", p1, len(in_ghl_rows))
    logger.info("Wrote %s (%d rows)", p2, len(non_ghl_rows))
    return p1, p2


def write_contact_report(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "email",
        "ghl_contact_id",
        "tags_to_add",
        "lookup_status",
        "tags_applied_status",
        "sync_mode",
    ]
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    logger.info("Wrote sync report: %s (%d rows)", path, len(rows))


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    root = Path(__file__).resolve().parent.parent
    ghl_dir = Path(__file__).resolve().parent
    realnex_candidates = [
        Path.home() / "Desktop/cursor/REALNEX_CONTACTS.csv",
        root / "Realnex-All-Contacts_April-20-2026.csv",
        root / "REALNEX_CONTACTS.csv",
    ]
    realnex_default = next((p for p in realnex_candidates if p.is_file()), None)
    defaults_raw = [
        *( [realnex_default] if realnex_default else [] ),
        root / "cleaned_email_audience_export_b69dfb88dd.csv",
        root / "unsubscribed_email_audience_export_b69dfb88dd.csv",
        root / "subscribed_email_audience_export_b69dfb88dd.csv",
        ghl_dir / "import_ghl.csv",
    ]
    defaults_prefixed = [
        root / "cleaned_email_audience_export_b69dfb88dd_state_prefixed.csv",
        root / "unsubscribed_email_audience_export_b69dfb88dd_state_prefixed.csv",
        root / "subscribed_email_audience_export_b69dfb88dd_state_prefixed.csv",
    ]

    p = argparse.ArgumentParser(
        description="Remove list-matching GHL tags, then add state-based tags from audience CSVs"
    )
    p.add_argument(
        "--csv",
        dest="csvs",
        nargs="+",
        metavar="PATH",
        default=None,
        help="One or more CSV paths (audience and/or Realnex-style); union/intersection applies",
    )
    p.add_argument(
        "--scope",
        choices=("union", "intersection"),
        default="union",
        help="union = any input file (default); intersection = email present in every file",
    )
    p.add_argument(
        "--legacy-state-prefixed-input",
        action="store_true",
        help="Use *_state_prefixed.csv defaults instead of raw exports",
    )
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--limit", type=int, default=None, metavar="N")
    p.add_argument("--report", type=Path, default=None, metavar="PATH")
    p.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Where to write all_ghl_contacts.csv and non_ghl.csv (default: repo root)",
    )
    p.add_argument("--list-all", action="store_true")
    p.add_argument(
        "--no-import-missing",
        action="store_true",
        help="Do not POST /contacts/ for emails missing from GHL",
    )
    args = p.parse_args(argv)

    if args.csvs:
        paths = [Path(x).expanduser().resolve() for x in args.csvs]
    elif args.legacy_state_prefixed_input:
        paths = defaults_prefixed
    else:
        seen_paths: set[Path] = set()
        paths = []
        for p in defaults_raw:
            resolved = p.expanduser().resolve()
            if resolved.is_file() and resolved not in seen_paths:
                seen_paths.add(resolved)
                paths.append(resolved)
        if len(paths) < len(defaults_raw):
            missing_defaults = [str(p) for p in defaults_raw if not p.is_file()]
            logger.warning(
                "Skipping missing default input files (%s); pass --csv explicitly for full set",
                ", ".join(missing_defaults),
            )
        if not paths:
            logger.error(
                "No default CSVs found under %s — pass --csv path1 path2 ...",
                root,
            )
            return 1

    out_dir = args.output_dir or root
    for path in paths:
        if not path.is_file():
            logger.error("Missing file: %s", path)
            return 1

    literal_master = collect_literal_tags_from_exports(paths)
    removal_superset = build_removal_superset(literal_master)
    logger.info(
        "Master tag list: %d literals; removal superset size %d (with prefixed variants)",
        len(literal_master),
        len(removal_superset),
    )

    if args.scope == "intersection":
        merged = intersection_merged_profiles_auto(paths)
        logger.info("Scope=intersection — emails in all files: %d", len(merged))
    else:
        merged = union_merged_profiles_auto(paths)
        logger.info("Scope=union — distinct emails: %d", len(merged))

    if not merged:
        logger.warning("No emails in scope.")
        return 0

    if args.limit is not None:
        keys = sorted(merged.keys())[: max(0, args.limit)]
        merged = {k: merged[k] for k in keys}
        logger.info("--limit %s → %d emails", args.limit, len(merged))

    token = os.environ.get("GHL_API_TOKEN", "")
    location_id = os.environ.get("GHL_LOCATION_ID", "")
    if not args.dry_run and (not token or not location_id):
        logger.error("Set GHL_API_TOKEN and GHL_LOCATION_ID (or use --dry-run).")
        return 1

    ghl_dir = Path(__file__).resolve().parent
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = args.report or (ghl_dir / f"tag_sync_report_{ts}.csv")

    if args.dry_run:
        logger.info(
            "DRY RUN — no API calls. Writing planned sync report only; "
            "run without --dry-run to build all_ghl_contacts.csv and non_ghl.csv from GHL."
        )
        dry_rep = [
            {
                "email": em,
                "ghl_contact_id": "",
                "tags_to_add": _join(
                    format_tags_for_state(merged[em].state, merged[em].tags)
                ),
                "lookup_status": "dry_run",
                "tags_applied_status": "not_run",
                "sync_mode": "list_remove_then_state_tags",
            }
            for em in sorted(merged.keys())
        ]
        write_contact_report(report_path, dry_rep)
        return 0

    all_ghl_out: list[dict[str, str]] = []
    non_ghl_out: list[dict[str, str]] = []
    report_by_email: dict[str, dict[str, str]] = {}
    import_missing = not args.no_import_missing

    pending_add: list[
        tuple[str, str, list[str], bool]
    ] = []  # email, cid, new_tags, remove_ok

    for i, em in enumerate(sorted(merged.keys()), 1):
        prof = merged[em]
        new_tags = format_tags_for_state(prof.state, prof.tags)

        cid = find_contact_id_by_email(em, location_id)
        if not cid:
            logger.warning("[%d/%d] Not in GHL: %s", i, len(merged), em)
            non_ghl_out.append(
                {
                    "name": prof.display_name(),
                    "email": em,
                    "state": prof.state,
                    "tags": _join(prof.tags),
                }
            )
            report_by_email[em] = {
                "email": em,
                "ghl_contact_id": "",
                "tags_to_add": _join(new_tags),
                "lookup_status": "not_in_ghl",
                "tags_applied_status": (
                    "pending_import" if import_missing else "not_attempted"
                ),
                "sync_mode": "list_remove_then_state_tags",
            }
            time.sleep(LOOKUP_DELAY_SEC)
            continue

        cobj = get_contact(cid)
        if not cobj:
            logger.error("[%d/%d] GET contact failed for %s", i, len(merged), em)
            report_by_email[em] = {
                "email": em,
                "ghl_contact_id": cid,
                "tags_to_add": _join(new_tags),
                "lookup_status": "matched_get_failed",
                "tags_applied_status": "failed",
                "sync_mode": "list_remove_then_state_tags",
            }
            time.sleep(LOOKUP_DELAY_SEC)
            continue

        ghl_tags = list(cobj.get("tags") or [])
        display = ghl_display_name(cobj)
        if not display.strip():
            display = prof.display_name()

        all_ghl_out.append(
            {
                "name": display,
                "email": em,
                "state": prof.state,
                "tags": _join(ghl_tags),
            }
        )

        to_remove = [t for t in ghl_tags if t in removal_superset]
        remove_ok = True
        if to_remove:
            logger.info(
                "[%d/%d] Removing %d list-matching tag(s) from %s",
                i,
                len(merged),
                len(to_remove),
                em,
            )
            remove_ok = remove_tags_in_chunks(cid, to_remove)

        pending_add.append((em, cid, new_tags, remove_ok))

        if not remove_ok:
            report_by_email[em] = {
                "email": em,
                "ghl_contact_id": cid,
                "tags_to_add": _join(new_tags),
                "lookup_status": "matched",
                "tags_applied_status": "remove_failed",
                "sync_mode": "list_remove_then_state_tags",
            }
        elif not new_tags:
            report_by_email[em] = {
                "email": em,
                "ghl_contact_id": cid,
                "tags_to_add": "",
                "lookup_status": "matched",
                "tags_applied_status": "removed_list_only",
                "sync_mode": "list_remove_then_state_tags",
            }
        else:
            report_by_email[em] = {
                "email": em,
                "ghl_contact_id": cid,
                "tags_to_add": _join(new_tags),
                "lookup_status": "matched",
                "tags_applied_status": "pending_add",
                "sync_mode": "list_remove_then_state_tags",
            }

        time.sleep(LOOKUP_DELAY_SEC)

    # Phase 2: bulk-add identical tag sets (contacts that passed remove)
    buckets: dict[tuple[str, ...], list[str]] = defaultdict(list)
    cid_to_email_add: dict[str, str] = {}
    for em, cid, new_tags, remove_ok in pending_add:
        if not remove_ok or not new_tags:
            continue
        key = tuple(new_tags)
        buckets[key].append(cid)
        cid_to_email_add[cid] = em

    failures = 0
    for tag_tuple, contact_ids in buckets.items():
        tags = list(tag_tuple)
        if len(contact_ids) > 1:
            ok_b, fail_b = bulk_update_tags(
                action="add",
                contact_ids=contact_ids,
                tags=tags,
                location_id=location_id,
                remove_all_tags=False,
                dry_run=False,
            )
            failures += fail_b
            batch_ok = fail_b == 0
            logger.info(
                "Bulk add %s for %d contacts — batches ok=%s fail=%s",
                tags[:8],
                len(contact_ids),
                ok_b,
                fail_b,
            )
            for cid in contact_ids:
                eml = cid_to_email_add.get(cid)
                if eml and eml in report_by_email:
                    report_by_email[eml]["tags_applied_status"] = (
                        "applied" if batch_ok else "add_failed"
                    )
        else:
            cid = contact_ids[0]
            eml = cid_to_email_add[cid]
            if add_tags_contact(cid, tags, dry_run=False):
                report_by_email[eml]["tags_applied_status"] = "applied"
            else:
                report_by_email[eml]["tags_applied_status"] = "add_failed"
                failures += 1

    import_failures = 0
    if import_missing:
        for em in sorted(report_by_email.keys()):
            rec = report_by_email[em]
            if rec.get("tags_applied_status") != "pending_import":
                continue
            prof = merged[em]
            new_tags = format_tags_for_state(prof.state, prof.tags)
            cid = create_ghl_contact(
                prof,
                new_tags,
                location_id,
                dry_run=False,
            )
            if cid:
                rec["ghl_contact_id"] = cid
                rec["tags_applied_status"] = "imported"
            else:
                rec["tags_applied_status"] = "import_failed"
                import_failures += 1
            time.sleep(LOOKUP_DELAY_SEC)

    write_split_outputs(out_dir=out_dir, in_ghl_rows=all_ghl_out, non_ghl_rows=non_ghl_out)

    report_rows = [report_by_email[k] for k in sorted(report_by_email.keys())]
    write_contact_report(report_path, report_rows)

    success = sum(
        1
        for r in report_rows
        if r.get("tags_applied_status")
        in ("applied", "removed_list_only", "not_attempted", "imported")
    )
    logger.info(
        "Done. Split outputs in %s | sync report: %s | bulk-add batch failures: %s | "
        "import failures: %s",
        out_dir,
        report_path,
        failures,
        import_failures,
    )
    if args.list_all:
        for r in report_rows:
            if r.get("tags_applied_status") in (
                "applied",
                "removed_list_only",
                "imported",
            ):
                logger.info(
                    "  %s  %s  %s",
                    r["email"],
                    r.get("tags_applied_status"),
                    r.get("tags_to_add"),
                )
    return 0 if failures == 0 and import_failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
