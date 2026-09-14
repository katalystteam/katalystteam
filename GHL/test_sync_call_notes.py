"""
Unit tests for sync_call_notes.py

Run with: python -m pytest GHL/test_sync_call_notes.py -v
"""

import os
import json
from unittest.mock import patch, MagicMock

import requests
import pytest

from sync_call_notes import (
    CallNote,
    extract_call_notes,
    parse_name_and_phone,
    parse_sheet_date,
    format_note_body,
    search_contact_by_name,
    create_note,
    get_existing_notes,
    note_already_exists,
    sync_notes,
)


# ---------------------------------------------------------------------------
# Test data
# ---------------------------------------------------------------------------
EXCEL_PATH = os.path.join(os.path.dirname(__file__), "..", "call_notes.xlsx")
TEST_SHEET = "1.5.26 Economics"

MOCK_CONTACT = {
    "id": "abc123",
    "firstName": "Tyler",
    "lastName": "Hogue",
    "name": "Tyler Hogue",
    "locationId": "loc123",
}

MOCK_NOTE_RESPONSE = {
    "note": {
        "id": "note456",
        "body": "[Call Notes - 1.5.26] Test note",
        "userId": "user789",
        "dateAdded": "2026-01-05T12:00:00.000Z",
        "contactId": "abc123",
    }
}


# ---------------------------------------------------------------------------
# Excel parsing tests
# ---------------------------------------------------------------------------
class TestParseSheetDate:
    def test_standard_format(self):
        assert parse_sheet_date("1.5.26 Economics") == "1.5.26"

    def test_longer_date(self):
        assert parse_sheet_date("12.15.25 Economics") == "12.15.25"

    def test_with_leading_space(self):
        assert parse_sheet_date(" 3.20.23 Economics") == "3.20.23"


class TestExtractCallNotes:
    def test_extracts_from_real_file(self):
        """Integration test: reads actual Excel file."""
        if not os.path.exists(EXCEL_PATH):
            pytest.skip("call_notes.xlsx not found")

        notes = extract_call_notes(EXCEL_PATH, TEST_SHEET)

        assert len(notes) > 0
        for cn in notes:
            assert cn.name, "Name should not be empty"
            assert cn.notes, "Notes should not be empty"
            assert cn.called is True
            assert cn.sheet_date == "1.5.26"

    def test_known_contacts_present(self):
        """Verify specific known contacts from 1.5.26 sheet are extracted."""
        if not os.path.exists(EXCEL_PATH):
            pytest.skip("call_notes.xlsx not found")

        notes = extract_call_notes(EXCEL_PATH, TEST_SHEET)
        names = [cn.name for cn in notes]

        assert "Tyler Hogue" in names
        assert "Ben Latusek" in names

    def test_uncalled_contacts_excluded(self):
        """Contacts with Called=False should not be extracted."""
        if not os.path.exists(EXCEL_PATH):
            pytest.skip("call_notes.xlsx not found")

        notes = extract_call_notes(EXCEL_PATH, TEST_SHEET)
        names = [cn.name for cn in notes]

        # Tyler Rasmussen has Called=False in 1.5.26
        assert "Tyler Rasmussen" not in names

    def test_invalid_sheet_raises(self):
        if not os.path.exists(EXCEL_PATH):
            pytest.skip("call_notes.xlsx not found")

        with pytest.raises(ValueError, match="not found"):
            extract_call_notes(EXCEL_PATH, "NonExistent Sheet")


class TestParseNameAndPhone:
    def test_name_with_dashed_phone(self):
        name, phone = parse_name_and_phone("Keith Kleinhans 281-777-7177")
        assert name == "Keith Kleinhans"
        assert phone == "281-777-7177"

    def test_name_with_parenthesized_phone(self):
        name, phone = parse_name_and_phone("Brian Ridge (319) 777-2284")
        assert name == "Brian Ridge"
        assert phone == "(319) 777-2284"

    def test_name_with_dotted_phone(self):
        name, phone = parse_name_and_phone("John Doe 515.123.4567")
        assert name == "John Doe"
        assert phone == "515.123.4567"

    def test_name_without_phone(self):
        name, phone = parse_name_and_phone("Tyler Hogue")
        assert name == "Tyler Hogue"
        assert phone == ""

    def test_name_with_trailing_spaces(self):
        name, phone = parse_name_and_phone("Jen Parker ")
        assert name == "Jen Parker"
        assert phone == ""

    def test_name_with_hyphen_before_phone(self):
        name, phone = parse_name_and_phone("Ron Lappy -515-509-9961")
        assert name == "Ron Lappy"
        assert phone == "515-509-9961"


class TestFormatNoteBody:
    def test_format_without_phone(self):
        cn = CallNote(name="Test", notes="Talked about deals", called=True, sheet_date="1.5.26")
        result = format_note_body(cn)
        assert result == "[Call Notes - 1.5.26] Talked about deals"

    def test_format_with_phone(self):
        cn = CallNote(name="Keith Kleinhans", notes="Referred by Todd Scott", called=True, sheet_date="1.5.26", phone="281-777-7177")
        result = format_note_body(cn)
        assert result == "[Call Notes - 1.5.26] (Phone: 281-777-7177) Referred by Todd Scott"


# ---------------------------------------------------------------------------
# GHL API tests (mocked)
# ---------------------------------------------------------------------------
class TestSearchContactByName:
    @patch("sync_call_notes.requests.get")
    def test_exact_match_returned(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"contacts": [MOCK_CONTACT]}
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        with patch("sync_call_notes.GHL_API_TOKEN", "test-token"), \
             patch("sync_call_notes.GHL_LOCATION_ID", "loc123"):
            result = search_contact_by_name("Tyler Hogue")

        assert result is not None
        assert result["id"] == "abc123"

    @patch("sync_call_notes.requests.get")
    def test_no_contacts_returns_none(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"contacts": []}
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        with patch("sync_call_notes.GHL_API_TOKEN", "test-token"), \
             patch("sync_call_notes.GHL_LOCATION_ID", "loc123"):
            result = search_contact_by_name("Nobody Real")

        assert result is None

    @patch("sync_call_notes.requests.get")
    def test_api_error_returns_none(self, mock_get):
        mock_get.side_effect = requests.RequestException("Connection failed")

        with patch("sync_call_notes.GHL_API_TOKEN", "test-token"), \
             patch("sync_call_notes.GHL_LOCATION_ID", "loc123"):
            result = search_contact_by_name("Tyler Hogue")

        assert result is None

    @patch("sync_call_notes.requests.get")
    def test_case_insensitive_match(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "contacts": [
                {"id": "abc123", "firstName": "tyler", "lastName": "hogue", "name": "tyler hogue"}
            ]
        }
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        with patch("sync_call_notes.GHL_API_TOKEN", "test-token"), \
             patch("sync_call_notes.GHL_LOCATION_ID", "loc123"):
            result = search_contact_by_name("Tyler Hogue")

        assert result is not None
        assert result["id"] == "abc123"


class TestCreateNote:
    @patch("sync_call_notes.requests.post")
    def test_successful_creation(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.json.return_value = MOCK_NOTE_RESPONSE
        mock_resp.raise_for_status = MagicMock()
        mock_post.return_value = mock_resp

        with patch("sync_call_notes.GHL_API_TOKEN", "test-token"):
            result = create_note("abc123", "[Call Notes - 1.5.26] Test note")

        assert result is not None
        assert result["id"] == "note456"

        # Verify correct URL and payload
        call_args = mock_post.call_args
        assert "abc123/notes" in call_args[0][0]
        assert call_args[1]["json"]["body"] == "[Call Notes - 1.5.26] Test note"

    @patch("sync_call_notes.requests.post")
    def test_api_error_returns_none(self, mock_post):
        mock_post.side_effect = requests.RequestException("Server error")

        with patch("sync_call_notes.GHL_API_TOKEN", "test-token"):
            result = create_note("abc123", "Test note")

        assert result is None


class TestGetExistingNotes:
    @patch("sync_call_notes.requests.get")
    def test_returns_notes(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "notes": [
                {"id": "n1", "body": "Existing note", "contactId": "abc123"}
            ]
        }
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        with patch("sync_call_notes.GHL_API_TOKEN", "test-token"):
            result = get_existing_notes("abc123")

        assert len(result) == 1
        assert result[0]["body"] == "Existing note"

    @patch("sync_call_notes.requests.get")
    def test_api_error_returns_empty(self, mock_get):
        mock_get.side_effect = requests.RequestException("error")

        with patch("sync_call_notes.GHL_API_TOKEN", "test-token"):
            result = get_existing_notes("abc123")

        assert result == []


class TestNoteAlreadyExists:
    @patch("sync_call_notes.get_existing_notes")
    def test_duplicate_detected(self, mock_get_notes):
        mock_get_notes.return_value = [
            {"id": "n1", "body": "[Call Notes - 1.5.26] Test note"}
        ]
        assert note_already_exists("abc123", "[Call Notes - 1.5.26] Test note") is True

    @patch("sync_call_notes.get_existing_notes")
    def test_no_duplicate(self, mock_get_notes):
        mock_get_notes.return_value = [
            {"id": "n1", "body": "Some other note"}
        ]
        assert note_already_exists("abc123", "[Call Notes - 1.5.26] New note") is False

    @patch("sync_call_notes.get_existing_notes")
    def test_empty_notes(self, mock_get_notes):
        mock_get_notes.return_value = []
        assert note_already_exists("abc123", "Any note") is False


# ---------------------------------------------------------------------------
# Sync integration test (mocked API)
# ---------------------------------------------------------------------------
class TestSyncNotes:
    @patch("sync_call_notes.create_note")
    @patch("sync_call_notes.note_already_exists")
    @patch("sync_call_notes.search_contact_by_name")
    def test_dry_run_no_api_calls(self, mock_search, mock_dup, mock_create):
        """Dry run should not call any GHL API."""
        if not os.path.exists(EXCEL_PATH):
            pytest.skip("call_notes.xlsx not found")

        with patch("sync_call_notes.GHL_API_TOKEN", "test-token"), \
             patch("sync_call_notes.GHL_LOCATION_ID", "loc123"):
            summary = sync_notes(TEST_SHEET, dry_run=True)

        mock_search.assert_not_called()
        mock_dup.assert_not_called()
        mock_create.assert_not_called()
        assert summary["synced"] == summary["total"]

    @patch("sync_call_notes.time.sleep")
    @patch("sync_call_notes.create_note")
    @patch("sync_call_notes.note_already_exists")
    @patch("sync_call_notes.search_contact_by_name")
    def test_full_sync_with_mocked_api(self, mock_search, mock_dup, mock_create, mock_sleep):
        """Full sync with mocked GHL API."""
        if not os.path.exists(EXCEL_PATH):
            pytest.skip("call_notes.xlsx not found")

        mock_search.return_value = MOCK_CONTACT
        mock_dup.return_value = False
        mock_create.return_value = {"id": "note456", "body": "test"}

        with patch("sync_call_notes.GHL_API_TOKEN", "test-token"), \
             patch("sync_call_notes.GHL_LOCATION_ID", "loc123"):
            summary = sync_notes(TEST_SHEET, dry_run=False)

        assert summary["synced"] == summary["total"]
        assert summary["failed"] == 0
        assert mock_search.call_count == summary["total"]
        assert mock_create.call_count == summary["total"]

    @patch("sync_call_notes.time.sleep")
    @patch("sync_call_notes.create_note")
    @patch("sync_call_notes.note_already_exists")
    @patch("sync_call_notes.search_contact_by_name")
    def test_skips_not_found(self, mock_search, mock_dup, mock_create, mock_sleep):
        """Contacts not found in GHL should be counted as not_found."""
        if not os.path.exists(EXCEL_PATH):
            pytest.skip("call_notes.xlsx not found")

        mock_search.return_value = None  # no contact found

        with patch("sync_call_notes.GHL_API_TOKEN", "test-token"), \
             patch("sync_call_notes.GHL_LOCATION_ID", "loc123"):
            summary = sync_notes(TEST_SHEET, dry_run=False)

        assert summary["not_found"] == summary["total"]
        assert summary["synced"] == 0
        mock_create.assert_not_called()

    @patch("sync_call_notes.time.sleep")
    @patch("sync_call_notes.create_note")
    @patch("sync_call_notes.note_already_exists")
    @patch("sync_call_notes.search_contact_by_name")
    def test_skips_duplicates(self, mock_search, mock_dup, mock_create, mock_sleep):
        """Duplicate notes should be skipped."""
        if not os.path.exists(EXCEL_PATH):
            pytest.skip("call_notes.xlsx not found")

        mock_search.return_value = MOCK_CONTACT
        mock_dup.return_value = True  # already exists

        with patch("sync_call_notes.GHL_API_TOKEN", "test-token"), \
             patch("sync_call_notes.GHL_LOCATION_ID", "loc123"):
            summary = sync_notes(TEST_SHEET, dry_run=False)

        assert summary["skipped_duplicate"] == summary["total"]
        assert summary["synced"] == 0
        mock_create.assert_not_called()
