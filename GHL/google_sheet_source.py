"""
Download the call-notes Google Sheets workbook for sync_call_notes.py.

Default spreadsheet (Jared's Weekly To-Do's):
  https://docs.google.com/spreadsheets/d/1mYQW-dViPp-E0j62aaFqmVPAM_Mgd7_W/

Auth options (pick one):
  1. Service account — share the sheet with the service account email as Viewer,
     set GOOGLE_SERVICE_ACCOUNT_FILE to the JSON key path.
  2. Public link — set sharing to "Anyone with the link" → Viewer (no extra deps).

Official references:
  - Drive files.export: https://developers.google.com/drive/api/reference/rest/v3/files/export
  - Sheets publish/export: https://support.google.com/docs/answer/183965
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

import requests

logger = logging.getLogger(__name__)

DEFAULT_SPREADSHEET_ID = "1mYQW-dViPp-E0j62aaFqmVPAM_Mgd7_W"
XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
DRIVE_EXPORT_SCOPE = "https://www.googleapis.com/auth/drive.readonly"


def spreadsheet_id_from_env() -> str:
    return (
        os.environ.get("CALL_NOTES_GOOGLE_SHEET_ID", "").strip()
        or os.environ.get("GOOGLE_SHEET_ID", "").strip()
        or DEFAULT_SPREADSHEET_ID
    )


def cache_path(root: Path | None = None) -> Path:
    base = root or Path(__file__).resolve().parent.parent
    return base / "sync_logs" / "call_notes_workbook_cache.xlsx"


def public_export_url(spreadsheet_id: str) -> str:
    return f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/export?format=xlsx"


def download_via_public_export(spreadsheet_id: str, dest: Path, timeout: int = 120) -> bool:
    """Works when the sheet is shared as Anyone with the link → Viewer."""
    url = public_export_url(spreadsheet_id)
    resp = requests.get(url, timeout=timeout, allow_redirects=True)
    if resp.status_code != 200:
        logger.warning("Public export failed: HTTP %s", resp.status_code)
        return False
    if b"accounts.google.com" in resp.content[:500] or resp.content[:2] != b"PK":
        logger.warning("Public export returned login page or non-xlsx content")
        return False
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(resp.content)
    logger.info("Downloaded workbook via public export → %s", dest)
    return True


def download_via_service_account(spreadsheet_id: str, dest: Path) -> bool:
    """Export xlsx using a Google service account (Drive API files.export)."""
    key_file = os.environ.get("GOOGLE_SERVICE_ACCOUNT_FILE", "").strip()
    if not key_file:
        return False

    key_path = Path(key_file).expanduser()
    if not key_path.is_file():
        raise FileNotFoundError(f"GOOGLE_SERVICE_ACCOUNT_FILE not found: {key_path}")

    try:
        from google.oauth2 import service_account
        from googleapiclient.discovery import build
        from googleapiclient.http import MediaIoBaseDownload
    except ImportError as exc:
        raise RuntimeError(
            "Install google-api-python-client and google-auth for service-account download:\n"
            "  pip install google-api-python-client google-auth"
        ) from exc

    creds = service_account.Credentials.from_service_account_file(
        str(key_path),
        scopes=[DRIVE_EXPORT_SCOPE],
    )
    service = build("drive", "v3", credentials=creds, cache_discovery=False)
    request = service.files().export_media(fileId=spreadsheet_id, mimeType=XLSX_MIME)

    dest.parent.mkdir(parents=True, exist_ok=True)
    with open(dest, "wb") as handle:
        downloader = MediaIoBaseDownload(handle, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()

    logger.info("Downloaded workbook via service account → %s", dest)
    return True


def fetch_call_notes_workbook(
    dest: Path | None = None,
    spreadsheet_id: str | None = None,
    allow_stale_cache: bool = True,
) -> Path:
    """
    Download the latest Google Sheets workbook and return the local .xlsx path.

    Tries service account first, then public export. Falls back to an existing cache
    only when allow_stale_cache=True.
    """
    sheet_id = spreadsheet_id or spreadsheet_id_from_env()
    out = dest or cache_path()

    if download_via_service_account(sheet_id, out):
        return out
    if download_via_public_export(sheet_id, out):
        return out

    if allow_stale_cache and out.is_file():
        logger.warning(
            "Could not refresh Google Sheet; using cached workbook from %s", out
        )
        return out

    raise RuntimeError(
        "Could not download call-notes Google Sheet. Either:\n"
        "  • Share the sheet with your service account email and set "
        "GOOGLE_SERVICE_ACCOUNT_FILE, or\n"
        "  • Set sheet sharing to Anyone with the link → Viewer, or\n"
        "  • Set CALL_NOTES_FILE to a local .xlsx export."
    )
