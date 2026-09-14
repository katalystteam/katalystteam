# Iowa Multifamily Property Aggregator

Scrapes Iowa multifamily listings from Crexi, LoopNet, CBRE Deal Flow,
Marcus & Millichap, and JLL Investor Center, normalizes the data, and
exports one deduplicated CSV: `output/properties.csv`.

## Run it with one click (no install required)

This repo ships a GitHub Actions workflow that does the whole run on
GitHub's own servers — nobody needs Python, Playwright, or Ollama
installed locally to get a CSV.

1. Go to the repo's **Actions** tab.
2. Select **"Iowa Multifamily Property Aggregator"** in the left sidebar.
3. Click **"Run workflow"** (top right), leave the default options, click the green **"Run workflow"** button.
4. Wait for the run to finish (usually a few minutes; up to 25 before it's cut off).
5. Open the finished run, scroll to **Artifacts**, download `properties-csv-<run number>` for the CSV and `scraper-logs-<run number>` for `scraper.log` / failure screenshots.

**Trade-off of the one-click path**: GitHub's hosted runners have no
local Ollama daemon and no GPU, so `SCRAPER_DISABLE_OLLAMA=1` is set
automatically for every Actions run — you get deterministic
selector/regex parsing only, no LLM fallback for messy fields. If you
want the qwen3:8b-assisted version (better recovery when a site's
markup doesn't match a selector), run it locally instead — see below.

## Run it locally (with the Ollama fallback)

```bash
pip install -r requirements.txt
playwright install chromium
python scraper.py
```

### Read this before you run it

Several of these sites run bot-detection (Cloudflare / PerimeterX) in
front of search results, and CBRE / Marcus & Millichap / JLL commonly
gate detailed deal data behind a broker login. This scraper is written
to degrade gracefully when a site blocks it or a selector goes stale:
it logs a warning, screenshots the page, and moves to the next site
rather than crashing. **Don't be surprised if a cold run comes back
with 0 rows from one or more sources on the first try** — check
`logs/scraper.log` and `logs/screenshots/` to see what actually
rendered, then adjust the selectors in `scrapers/<site>.py` to match.

### Why Ollama is in here, and where

Ollama (`qwen3:8b`) is **not** driving navigation or deciding what to
scrape — that's all deterministic Playwright selectors, same as any
other scraper. It's used in exactly one place: `scrapers/ollama_helper.py`,
as a fallback that converts a raw scraped text blob into structured
JSON fields (`units`, `cap_rate`, `date_listed`, etc.) when the regex/
selector-based parser in `scrapers/normalize.py` comes up empty. If
Ollama isn't running, the fallback silently no-ops and the scraper
keeps going with whatever the deterministic parser found.

To enable it:

```bash
ollama serve
ollama pull qwen3:8b
```

It's on by default in `config.json` (`ollama.enabled: true`). Set it
to `false` to skip the LLM fallback entirely and rely only on
deterministic parsing.

## Project structure

```
PropertyScraper/
├── scraper.py              # orchestrator: launches browser, runs each site, exports CSV
├── requirements.txt
├── config.json              # filters, timeouts, retry counts, per-site URLs, Ollama settings
├── scrapers/
│   ├── base.py              # shared retry/timeout/screenshot/page scaffolding
│   ├── normalize.py         # deterministic price/units/cap-rate/date/state cleaning
│   ├── ollama_helper.py     # local LLM fallback field extractor (qwen3:8b via Ollama)
│   ├── crexi.py
│   ├── loopnet.py
│   ├── cbre.py
│   ├── marcus.py
│   └── jll.py
├── output/
│   └── properties.csv       # final export (generated at runtime, not committed)
├── logs/
│   ├── scraper.log           # generated at runtime, not committed
│   └── screenshots/          # captured automatically on a failed/empty scrape
└── .github/workflows/scrape-iowa-multifamily.yml   # the "1-click" Actions workflow (repo root)
```

## Configuration (`config.json`)

| Key | Meaning |
|---|---|
| `state_abbr` | Normalized state code written to every row (`IA`) |
| `date_range_days` | Listings older than this are dropped when a listing date is known |
| `headless` | Run Chromium headless (`true`) or visibly (`false`, useful for debugging selector drift) |
| `retry_count` | Retries per site on navigation/scrape failure |
| `timeout` | Playwright navigation timeout, ms |
| `max_pages_per_site` | Pagination cap per site |
| `parallel` | `true` runs all five sites concurrently in separate browser contexts |
| `ollama.*` | Local LLM fallback settings |
| `email_report.*` | Optional SMTP report after each run (off by default) |

## Output columns

`source, property_name, address, city, state, asking_price, units, cap_rate, property_type, broker_name, broker_email, date_listed, listing_url, scraped_at`

- `date_listed` is left blank when a site doesn't expose a listing date — the row is still kept, per spec.
- Data normalization: price → `$3,500,000`; units → `180`; cap rate → `5.4`; dates → `YYYY-MM-DD`; state → `IA`.

## Error handling

- Each site scraper runs inside a retry wrapper (`config.retry_count` attempts, exponential backoff) and is fully isolated — one site raising an exception never stops the others.
- A failed or empty scrape triggers a full-page screenshot under `logs/screenshots/`.
- CSV export writes to a temp file and atomically renames it over `output/properties.csv`, so a crash mid-export never corrupts the previous good file.
- All of the above is logged to `logs/scraper.log` (site started/completed, listings found/exported, errors, retry attempts).

## Known limitations (read before filing a bug)

- Selectors are best-effort based on each site's structure at time of writing. Real-estate marketplaces change their DOM frequently — expect to re-inspect and update `CARD_SELECTORS` / etc. in the relevant `scrapers/<site>.py` if a site returns 0 listings.
- Crexi and LoopNet may return a bot-check interstitial to headless Chromium instead of results; if so, try `headless: false` and/or add a longer `page.wait_for_timeout` after navigation.
- CBRE Deal Flow, Marcus & Millichap, and JLL Investor Center do not publish stable query-string search APIs; this scraper drives their on-page filter controls, which is more fragile than a direct URL and is the first thing to check if those three return nothing.
- `cap_rate` and `broker_email` are frequently just not present in public listing data on several of these sites — that's the site, not a bug in the scraper.
