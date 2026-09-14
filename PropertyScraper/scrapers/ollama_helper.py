"""Local-LLM fallback extractor, backed by Ollama running qwen3:8b.

Used ONLY when deterministic parsing (normalize.py) fails to pull a
field out of a raw text blob scraped from a listing card/page. The
scrapers never let the model decide navigation, selectors, or which
listings to keep -- it is strictly a text-to-JSON field extractor.

Requires:
    ollama serve
    ollama pull qwen3:8b
"""
from __future__ import annotations

import json
import logging
import re
from typing import Optional

import requests

logger = logging.getLogger("scraper")

_FIELDS = ["property_name", "address", "city", "asking_price", "units", "cap_rate", "date_listed"]

_PROMPT_TEMPLATE = """You extract structured real-estate listing data from raw scraped text.
Return ONLY a single JSON object (no markdown, no explanation) with these exact keys:
{fields}
If a value is not present in the text, use an empty string for that key.
Rules:
- asking_price: digits only formatting like "$3,500,000" or "" if unknown.
- units: integer as a string, e.g. "180", or "" if unknown.
- cap_rate: a number like "5.4", or "" if unknown.
- date_listed: format YYYY-MM-DD if a date is present, else "".

TEXT:
\"\"\"{text}\"\"\"

JSON:"""


class OllamaExtractor:
    def __init__(self, config: dict):
        ollama_cfg = config.get("ollama", {})
        self.enabled = bool(ollama_cfg.get("enabled", False))
        self.host = ollama_cfg.get("host", "http://localhost:11434")
        self.model = ollama_cfg.get("model", "qwen3:8b")
        self.timeout = ollama_cfg.get("request_timeout", 60)
        self._availability_checked = False
        self._available = False

    def _check_available(self) -> bool:
        if self._availability_checked:
            return self._available
        self._availability_checked = True
        if not self.enabled:
            self._available = False
            return False
        try:
            resp = requests.get(f"{self.host}/api/tags", timeout=5)
            self._available = resp.status_code == 200
        except requests.RequestException:
            logger.warning("Ollama not reachable at %s; disabling LLM fallback for this run.", self.host)
            self._available = False
        return self._available

    def extract_fields(self, raw_text: str) -> dict:
        """Best-effort structured extraction. Returns {} on any failure."""
        if not raw_text or not raw_text.strip():
            return {}
        if not self._check_available():
            return {}

        prompt = _PROMPT_TEMPLATE.format(fields=", ".join(_FIELDS), text=raw_text[:4000])
        try:
            resp = requests.post(
                f"{self.host}/api/generate",
                json={
                    "model": self.model,
                    "prompt": prompt,
                    "stream": False,
                    "options": {"temperature": 0.0},
                },
                timeout=self.timeout,
            )
            resp.raise_for_status()
            raw_response = resp.json().get("response", "")
        except (requests.RequestException, ValueError) as exc:
            logger.warning("Ollama extraction request failed: %s", exc)
            return {}

        return self._parse_json_response(raw_response)

    @staticmethod
    def _parse_json_response(raw_response: str) -> dict:
        # qwen3 sometimes wraps reasoning in <think>...</think>; strip it.
        cleaned = re.sub(r"<think>.*?</think>", "", raw_response, flags=re.DOTALL).strip()
        match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if not match:
            return {}
        try:
            data = json.loads(match.group(0))
        except json.JSONDecodeError:
            return {}
        return {k: str(v) if v is not None else "" for k, v in data.items() if k in _FIELDS}
