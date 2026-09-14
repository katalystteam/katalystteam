# Weekly Kickoff — Market Intelligence Pipeline

Automated Central Iowa multifamily market intelligence report for KataLYST Team.

## Architecture

```
Python scrapers (Playwright)          Excel workbook              PDF report
─────────────────────────────         ─────────────────           ──────────────
Crexi      ─┐                         Sheet: Crexi              Page 1: New Listings KPIs + charts
LoopNet    ─┤                         Sheet: LoopNet            Page 2: Recent Sales KPIs + charts
CBRE       ─┼─► Filter (IA, 7 days) ─► Sheet: CBRE       ───► Page 3: Submarket Scorecard
DealFlow   ─┤                         Sheet: DealFlow           Page 4: New Listing cards
JLL        ─┤                         Sheet: JLL                Page 5: Recent Sales cards
Marcus & Millichap ─┘                 Sheet: MarcusMillichap    Page 6: Market Intelligence
                                      Sheet: All Listings
                                      Sheet: All Sales
                                      Sheet: Summary
```

## Setup

```bash
cd weekly-kickoff
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m playwright install chromium
```

## Run

**Backtest mode** — regenerates the report and compares every metric against the frozen source of truth (166 checks):

```bash
python main.py --backtest
```

**Validation mode** — replicates the May 28, 2026 kickoff report from seed data:

```bash
python main.py --validate
```

**Live scrape mode** — scrapes all sites + KataLYST tracker for a specific week:

```bash
# Watch browsers open on each site:
python main.py --scrape --week-ending 2026-06-06 --visible

# Background mode (no windows):
python main.py --scrape --week-ending 2026-06-06 --headless
```

This also writes `output/source_of_truth_YYYY-MM-DD.json` as the baseline for that week.

## Output

Files are written to `output/`:

- `weekly_kickoff_data_YYYY-MM-DD.xlsx` — one sheet per source + consolidated sheets
- `KataLYST_Market_Intelligence_MMM-DD-YYYY.pdf` — 6-page weekly report

## Backtest / Source of Truth

The reference PDF (`KataLYST_Market_Intelligence_May-28-2026.pdf` at repo root) is frozen into:

| File | Role |
|------|------|
| `data/source_of_truth_may_28_2026.json` | Expected KPIs, properties, scorecard, brokers (166 assertions) |
| `data/seed_may_28_2026.py` | Pipeline input data derived from the reference |
| `output/backtest_report.json` | Pass/fail results after each backtest run |

```bash
python main.py --backtest
# → PASS 166/166 means generated PDF + Excel match source of truth
```

When you change scrapers, analytics, or PDF layout, re-run `--backtest` to confirm nothing regressed.
