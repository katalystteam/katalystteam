"""
Export all contacts/emails and review lists for people not receiving email (bounces/errors).

Sources:
  - GoHighLevel: POST /contacts/search (validEmail, dndSettings.Email message/code, tags)
  - Mailchimp audience exports: subscribed, unsubscribed, cleaned (cleaned = bounces/invalid)

Outputs (default: --output-dir):
  all_email_contacts.csv              — everyone in GHL and/or audience files
  not_receiving_emails.csv            — cannot receive mail (bounce, error, unsub, DND, cleaned)
  email_bouncing.csv                  — bounces & delivery errors only (excludes voluntary unsub)

Environment:
  GHL_API_TOKEN, GHL_LOCATION_ID
"""

from __future__ import annotations

import argparse
import csv
import logging
import os
import sys
import time
from dataclasses import dataclass, field
from io import StringIO
from pathlib import Path

import requests

GHL_BASE_URL = os.environ.get("GHL_BASE_URL", "https://services.leadconnectorhq.com")
GHL_API_VERSION = "2021-07-28"
REQUEST_DELAY = 0.25

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def _headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {os.environ.get('GHL_API_TOKEN', '')}",
        "Content-Type": "application/json",
        "Version": GHL_API_VERSION,
    }


def _norm_email(s: str) -> str:
    return (s or "").strip().lower()


def _parse_tags_cell(tags_cell: str) -> list[str]:
    if not tags_cell or not str(tags_cell).strip():
        return []
    row = list(csv.reader(StringIO(str(tags_cell).strip())))[0]
    return [c.strip() for c in row if c.strip()]


def _join(items: list[str]) -> str:
    return " | ".join(items)


def _contact_date_added_ms(c: dict) -> int | None:
    da = c.get("dateAdded")
    if da is None:
        return None
    if isinstance(da, (int, float)):
        return int(da)
    if isinstance(da, str):
        if da.isdigit():
            return int(da)
        try:
            from datetime import datetime

            s = da.replace("Z", "+00:00")
            return int(datetime.fromisoformat(s).timestamp() * 1000)
        except ValueError:
            return None
    return None


def _email_dnd_detail(c: dict) -> tuple[str, str, str]:
    """Return (status, message, code) for Email channel DND."""
    dnd = c.get("dndSettings") or {}
    if not isinstance(dnd, dict):
        return "", "", ""
    email = dnd.get("Email") or {}
    if not isinstance(email, dict):
        return "", "", ""
    return (
        str(email.get("status") or "").strip(),
        str(email.get("message") or "").strip(),
        str(email.get("code") or "").strip(),
    )


def _valid_email_flag(c: dict) -> str:
    """yes | no | unknown"""
    v = c.get("validEmail")
    if v is True or v == "true" or v == "True":
        return "yes"
    if v is False or v == "false" or v == "False":
        return "no"
    return "unknown"


def _tag_indicates_bounce(tags: list) -> bool:
    keywords = (
        "bounce",
        "bounced",
        "invalid",
        "undeliver",
        "failed",
        "failure",
        "error",
        "spam",
        "complaint",
        "suppressed",
        "bad email",
        "hard bounce",
        "soft bounce",
    )
    for t in tags:
        tl = str(t).lower()
        if any(k in tl for k in keywords):
            return True
    return False


def _dnd_message_indicates_bounce_or_error(message: str, code: str) -> bool:
    blob = f"{message} {code}".lower()
    if not blob.strip():
        return False
    signals = (
        "bounce",
        "bounced",
        "undeliver",
        "invalid",
        "failed",
        "failure",
        "does not exist",
        "mailbox",
        "spam",
        "complaint",
        "permanent bounce",
        "hard bounce",
        "soft bounce",
        "not accepted",
        "rejected",
        "error",
    )
    if any(s in blob for s in signals):
        # Pure unsubscribe click without a delivery failure signal
        if "unsubscribe" in blob and not any(
            x in blob for x in ("bounce", "spam", "invalid", "undeliver", "failed", "rejected")
        ):
            return False
        return True
    return False


def fetch_all_ghl_contacts(location_id: str) -> list[dict]:
    """POST /contacts/search — includes validEmail and full dndSettings (list GET omits these)."""
    url = f"{GHL_BASE_URL}/contacts/search"
    out: list[dict] = []
    page = 1

    while True:
        body = {"locationId": location_id, "page": page, "pageLimit": 100}
        resp = requests.post(url, headers=_headers(), json=body, timeout=60)
        resp.raise_for_status()
        batch = resp.json().get("contacts") or []
        if not batch:
            break
        out.extend(batch)
        if page % 10 == 0:
            logger.info("Fetched %d GHL contacts so far…", len(out))
        if len(batch) < 100:
            break
        page += 1
        time.sleep(REQUEST_DELAY)

    logger.info("Total GHL contacts fetched: %d", len(out))
    return out


@dataclass
class AudienceRow:
    email: str
    first_name: str = ""
    last_name: str = ""
    state: str = ""
    tags: list[str] = field(default_factory=list)
    segments: set[str] = field(default_factory=set)
    unsub_reason: str = ""
    clean_time: str = ""


def _load_audience_file(path: Path, segment: str) -> dict[str, AudienceRow]:
    """segment: subscribed | unsubscribed | cleaned"""
    rows: dict[str, AudienceRow] = {}
    with path.open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for raw in reader:
            em = _norm_email(raw.get("Email Address", ""))
            if not em:
                continue
            fn = (raw.get("First Name") or "").strip()
            ln = (raw.get("Last Name") or "").strip()
            st = (raw.get("State") or "").strip()
            tags = _parse_tags_cell(raw.get("TAGS", "") or "")
            unsub_reason = (raw.get("UNSUB_REASON") or raw.get("UNSUB_REASON_OTHER") or "").strip()
            clean_time = (raw.get("CLEAN_TIME") or "").strip()

            if em not in rows:
                rows[em] = AudienceRow(email=em, first_name=fn, last_name=ln, state=st, tags=tags)
            else:
                r = rows[em]
                if not r.first_name and fn:
                    r.first_name = fn
                if not r.last_name and ln:
                    r.last_name = ln
                if not r.state and st:
                    r.state = st
                seen = set(r.tags)
                for t in tags:
                    if t not in seen:
                        r.tags.append(t)
                        seen.add(t)
                if unsub_reason and not r.unsub_reason:
                    r.unsub_reason = unsub_reason
                if clean_time and not r.clean_time:
                    r.clean_time = clean_time

            rows[em].segments.add(segment)
    return rows


def merge_audience_exports(paths: dict[str, Path]) -> dict[str, AudienceRow]:
    merged: dict[str, AudienceRow] = {}
    for segment, path in paths.items():
        part = _load_audience_file(path, segment)
        for em, row in part.items():
            if em not in merged:
                merged[em] = row
            else:
                m = merged[em]
                m.segments |= row.segments
                if not m.first_name and row.first_name:
                    m.first_name = row.first_name
                if not m.last_name and row.last_name:
                    m.last_name = row.last_name
                if not m.state and row.state:
                    m.state = row.state
                if not m.unsub_reason and row.unsub_reason:
                    m.unsub_reason = row.unsub_reason
                if not m.clean_time and row.clean_time:
                    m.clean_time = row.clean_time
                seen = set(m.tags)
                for t in row.tags:
                    if t not in seen:
                        m.tags.append(t)
                        seen.add(t)
    return merged


def _display_name(first: str, last: str, fallback: str = "") -> str:
    n = f"{first.strip()} {last.strip()}".strip()
    return n or fallback


def ghl_issue_reasons(c: dict) -> list[str]:
    reasons: list[str] = []

    if _valid_email_flag(c) == "no":
        reasons.append("ghl_invalid_email")

    if c.get("bounceEmail") is True:
        reasons.append("ghl_bounce_email")
    if c.get("unsubscribeEmail") is True:
        reasons.append("ghl_unsubscribe_email")

    dnd_status, dnd_msg, dnd_code = _email_dnd_detail(c)
    dnd_lower = dnd_status.lower()
    if dnd_lower in ("inactive", "permanent"):
        reasons.append(f"ghl_email_dnd_{dnd_lower}")
    if _dnd_message_indicates_bounce_or_error(dnd_msg, dnd_code):
        reasons.append("ghl_esp_bounce_or_error")

    tags = c.get("tags") or []
    if isinstance(tags, list) and _tag_indicates_bounce(tags):
        reasons.append("ghl_tag_bounce_or_error")

    if c.get("dnd") is True and dnd_lower not in ("", "active"):
        reasons.append("ghl_dnd_global")

    return reasons


def is_bounce_or_delivery_error(reasons: list[str], row: dict[str, str]) -> bool:
    """True for hard bounces, invalid email, ESP failures — not voluntary unsub only."""
    bounce_keys = (
        "mailchimp_cleaned",
        "mailchimp_bounced_or_invalid",
        "ghl_invalid_email",
        "ghl_bounce_email",
        "ghl_esp_bounce_or_error",
        "ghl_tag_bounce_or_error",
        "ghl_email_dnd_permanent",
    )
    joined = " ".join(reasons)
    if any(k in joined for k in bounce_keys):
        return True
    if row.get("ghl_valid_email") == "no":
        return True
    if row.get("ghl_bounce_email") == "yes":
        return True
    return False


def audience_issue_reasons(a: AudienceRow | None) -> list[str]:
    if not a:
        return []
    reasons: list[str] = []
    if "cleaned" in a.segments:
        reasons.append("mailchimp_cleaned")
        reasons.append("mailchimp_bounced_or_invalid")
    if "unsubscribed" in a.segments:
        r = f"mailchimp_unsubscribed"
        if a.unsub_reason:
            r += f"({a.unsub_reason})"
        reasons.append(r)
    return reasons


def build_rows(
    ghl_by_email: dict[str, dict],
    audience: dict[str, AudienceRow],
) -> list[dict[str, str]]:
    all_emails = set(ghl_by_email.keys()) | set(audience.keys())
    out: list[dict[str, str]] = []

    for em in sorted(all_emails):
        g = ghl_by_email.get(em)
        a = audience.get(em)

        if g:
            fn = str(g.get("firstName") or "")
            ln = str(g.get("lastName") or "")
            name = _display_name(fn, ln, str(g.get("name") or g.get("contactName") or ""))
            state = str(g.get("state") or "")
            phone = str(g.get("phone") or "")
            tags = g.get("tags") or []
            tag_str = _join([str(t) for t in tags]) if isinstance(tags, list) else ""
            in_ghl = "yes"
            dnd_status, dnd_msg, dnd_code = _email_dnd_detail(g)
            valid_email = _valid_email_flag(g)
        else:
            name = _display_name(a.first_name, a.last_name) if a else ""
            state = a.state if a else ""
            phone = ""
            tag_str = _join(a.tags) if a else ""
            in_ghl = "no"
            dnd_status, dnd_msg, dnd_code = "", "", ""
            valid_email = "unknown"

        if a and not state:
            state = a.state
        if a and (not name or name == em):
            name = _display_name(a.first_name, a.last_name, name)

        mc_segments = _join(sorted(a.segments)) if a else ""
        reasons = ghl_issue_reasons(g) if g else []
        reasons.extend(audience_issue_reasons(a))
        reasons = list(dict.fromkeys(reasons))
        blocked = "yes" if reasons else "no"

        out.append(
            {
                "name": name,
                "email": em,
                "phone": phone,
                "state": state,
                "tags": tag_str,
                "in_ghl": in_ghl,
                "mailchimp_segments": mc_segments,
                "ghl_valid_email": valid_email,
                "ghl_bounce_email": "yes" if g and g.get("bounceEmail") is True else "no",
                "ghl_unsubscribe_email": "yes" if g and g.get("unsubscribeEmail") is True else "no",
                "ghl_email_dnd_status": dnd_status,
                "ghl_email_dnd_message": dnd_msg,
                "ghl_email_dnd_code": dnd_code,
                "mailchimp_clean_time": a.clean_time if a else "",
                "not_receiving_email": blocked,
                "reasons": "; ".join(reasons),
            }
        )
    return out


def write_csv(path: Path, rows: list[dict[str, str]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    logger.info("Wrote %s (%d rows)", path, len(rows))


def main(argv: list[str] | None = None) -> int:
    root = Path(__file__).resolve().parent.parent
    default_audience = {
        "subscribed": root / "subscribed_email_audience_export_b69dfb88dd.csv",
        "unsubscribed": root / "unsubscribed_email_audience_export_b69dfb88dd.csv",
        "cleaned": root / "cleaned_email_audience_export_b69dfb88dd.csv",
    }

    p = argparse.ArgumentParser(description="Export contacts and email deliverability review lists")
    p.add_argument("--output-dir", type=Path, default=root, help="Output directory for CSVs")
    p.add_argument(
        "--audience-only",
        action="store_true",
        help="Skip GHL API; use Mailchimp audience files only",
    )
    p.add_argument(
        "--subscribed-csv",
        type=Path,
        default=default_audience["subscribed"],
    )
    p.add_argument(
        "--unsubscribed-csv",
        type=Path,
        default=default_audience["unsubscribed"],
    )
    p.add_argument(
        "--cleaned-csv",
        type=Path,
        default=default_audience["cleaned"],
    )
    args = p.parse_args(argv)

    audience_paths = {
        "subscribed": args.subscribed_csv,
        "unsubscribed": args.unsubscribed_csv,
        "cleaned": args.cleaned_csv,
    }
    for label, path in audience_paths.items():
        if not path.is_file():
            logger.error("Missing %s audience file: %s", label, path)
            return 1

    audience = merge_audience_exports(audience_paths)
    logger.info("Audience emails loaded: %d", len(audience))

    ghl_by_email: dict[str, dict] = {}
    if not args.audience_only:
        token = os.environ.get("GHL_API_TOKEN", "")
        location_id = os.environ.get("GHL_LOCATION_ID", "")
        if not token or not location_id:
            logger.error("Set GHL_API_TOKEN and GHL_LOCATION_ID, or pass --audience-only.")
            return 1
        contacts = fetch_all_ghl_contacts(location_id)
        for c in contacts:
            em = _norm_email(str(c.get("email") or c.get("emailLowerCase") or ""))
            if em:
                ghl_by_email[em] = c

    all_rows = build_rows(ghl_by_email, audience)
    blocked_rows = [r for r in all_rows if r["not_receiving_email"] == "yes"]
    bounce_rows = [
        r
        for r in all_rows
        if is_bounce_or_delivery_error(
            [x.strip() for x in r["reasons"].split(";") if x.strip()], r
        )
    ]

    out_dir = args.output_dir
    all_fields = [
        "name",
        "email",
        "phone",
        "state",
        "tags",
        "in_ghl",
        "mailchimp_segments",
        "ghl_valid_email",
        "ghl_bounce_email",
        "ghl_unsubscribe_email",
        "ghl_email_dnd_status",
        "ghl_email_dnd_message",
        "ghl_email_dnd_code",
        "mailchimp_clean_time",
        "not_receiving_email",
        "reasons",
    ]
    review_fields = [
        "name",
        "email",
        "phone",
        "state",
        "tags",
        "in_ghl",
        "mailchimp_segments",
        "ghl_valid_email",
        "ghl_email_dnd_message",
        "reasons",
    ]
    bounce_fields = [
        "name",
        "email",
        "phone",
        "state",
        "tags",
        "in_ghl",
        "ghl_valid_email",
        "ghl_email_dnd_message",
        "mailchimp_clean_time",
        "reasons",
    ]

    write_csv(out_dir / "all_email_contacts.csv", all_rows, all_fields)
    write_csv(out_dir / "not_receiving_emails.csv", blocked_rows, review_fields)
    write_csv(out_dir / "email_bouncing.csv", bounce_rows, bounce_fields)

    invalid_ghl = sum(1 for r in all_rows if r.get("ghl_valid_email") == "no")
    logger.info(
        "Summary: total=%d | not_receiving=%d | bounce_or_error=%d | ghl_invalid_email=%d | in_ghl=%d",
        len(all_rows),
        len(blocked_rows),
        len(bounce_rows),
        invalid_ghl,
        sum(1 for r in all_rows if r["in_ghl"] == "yes"),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
