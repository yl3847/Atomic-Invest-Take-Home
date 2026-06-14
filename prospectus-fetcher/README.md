# prospectus-fetch

## 1. What it does

`prospectus-fetch` is a CLI tool that retrieves the latest SEC fund prospectus for any US-listed mutual fund or ETF by ticker, downloading the HTML document directly from EDGAR and recording the result in a structured manifest. It resolves a ticker to the specific share-class identity registered with the SEC, selects the most recent effective prospectus (485BPOS preferred, 497K fallback), and handles any number of tickers in a single run with per-ticker isolation and graceful failure.

```
$ prospectus-fetch fetch VUSXX --out ./output
```

```
VUSXX        OK  2025-12-19  485BPOS
output/VUSXX/2025-12-19_485BPOS_000119312525325143/prospectus.htm
                            Prospectus Fetch Summary
┏━━━━┳━━━━━━━━┳━━━━━━━━┳━━━━━━━━━┳━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃    ┃ Ticker ┃ Status ┃ Form    ┃ Filed      ┃ Saved To / Error                                    ┃
┡━━━━╇━━━━━━━━╇━━━━━━━━╇━━━━━━━━━╇━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┩
│ ✓  │ VUSXX  │ OK     │ 485BPOS │ 2025-12-19 │ output/VUSXX/2025-12-19_485BPOS_.../prospectus.htm │
└────┴────────┴────────┴─────────┴────────────┴─────────────────────────────────────────────────────┘
1 succeeded
```

**See [`sample_run/`](sample_run/) for committed real output** — manifest, summary, and two prospectus stubs from a Checkpoint 3 run across seven funds (Schwab, T. Rowe Price, SPY, QQQ, Vanguard, Fidelity).

---

## 2. Quickstart

```bash
# Install (editable, from repo root)
pip install -e prospectus-fetcher/

# Set the SEC-required User-Agent (your name + email — SEC fair-access policy)
export SEC_USER_AGENT="Your Name your@email.com"

# Fetch a prospectus
prospectus-fetch fetch VUSXX --out ./output
```

Or install in an isolated environment with pipx:

```bash
pipx install ./prospectus-fetcher
export SEC_USER_AGENT="Your Name your@email.com"
prospectus-fetch fetch VUSXX --out ./output
```

> **Note:** The `SEC_USER_AGENT` environment variable is required. The SEC blocks
> requests without a descriptive `User-Agent` header identifying the requester.
> You can also pass it inline: `--user-agent "Your Name your@email.com"`.

---

## 3. Usage

### Single ticker (Checkpoint 1)

```bash
prospectus-fetch fetch VUSXX --out ./output
```

```
VUSXX        OK  2025-12-19  485BPOS
output/VUSXX/2025-12-19_485BPOS_000119312525325143/prospectus.htm
                            Prospectus Fetch Summary
┏━━━━┳━━━━━━━━┳━━━━━━━━┳━━━━━━━━━┳━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃    ┃ Ticker ┃ Status ┃ Form    ┃ Filed      ┃ Saved To / Error                                    ┃
┡━━━━╇━━━━━━━━╇━━━━━━━━╇━━━━━━━━━╇━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┩
│ ✓  │ VUSXX  │ OK     │ 485BPOS │ 2025-12-19 │ output/VUSXX/2025-12-19_485BPOS_.../prospectus.htm │
└────┴────────┴────────┴─────────┴────────────┴─────────────────────────────────────────────────────┘
1 succeeded
```

Running the same command a second time is a no-op (idempotent):

```
VUSXX        SKIPPED  2025-12-19  485BPOS
output/VUSXX/2025-12-19_485BPOS_000119312525325143/prospectus.htm
                            Prospectus Fetch Summary
┏━━━━┳━━━━━━━━┳━━━━━━━━━━━━━━━━━━┳━━━━━━━━━┳━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃    ┃ Ticker ┃ Status           ┃ Form    ┃ Filed      ┃ Saved To / Error                    ┃
┡━━━━╇━━━━━━━━╇━━━━━━━━━━━━━━━━━━╇━━━━━━━━━╇━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┩
│ ✓  │ VUSXX  │ SKIPPED_EXISTING │ 485BPOS │ 2025-12-19 │ output/VUSXX/2025-12-19_.../pros... │
└────┴────────┴──────────────────┴─────────┴────────────┴─────────────────────────────────────┘
1 succeeded  1 skipped (already exists)
```

### Batch (Checkpoint 2)

```bash
prospectus-fetch fetch VTSAX VMFXX --out ./output
```

```
VTSAX        OK  2026-04-28  485BPOS
output/VTSAX/2026-04-28_485BPOS_000003640526000181/prospectus.htm
VMFXX        OK  2025-12-19  485BPOS
output/VMFXX/2025-12-19_485BPOS_000119312525325144/prospectus.htm
                            Prospectus Fetch Summary
┏━━━━┳━━━━━━━━┳━━━━━━━━┳━━━━━━━━━┳━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃    ┃ Ticker ┃ Status ┃ Form    ┃ Filed      ┃ Saved To / Error                                    ┃
┡━━━━╇━━━━━━━━╇━━━━━━━━╇━━━━━━━━━╇━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┩
│ ✓  │ VTSAX  │ OK     │ 485BPOS │ 2026-04-28 │ output/VTSAX/2026-04-28_485BPOS_.../prospectus.htm │
│ ✓  │ VMFXX  │ OK     │ 485BPOS │ 2025-12-19 │ output/VMFXX/2025-12-19_485BPOS_.../prospectus.htm │
└────┴────────┴────────┴─────────┴────────────┴─────────────────────────────────────────────────────┘
2 succeeded
```

### Arbitrary tickers across fund families and providers (Checkpoint 3)

```bash
prospectus-fetch fetch SWPPX TRBCX SPY QQQ VOO SWVXX FDRXX BOGUS123 --out ./output
```

```
SWPPX        OK  2026-02-26  485BPOS  output/SWPPX/2026-02-26_485BPOS_.../prospectus.htm
TRBCX        OK  2026-02-25  485BPOS  output/TRBCX/2026-02-25_485BPOS_.../prospectus.htm
SPY          OK  2026-01-26  485BPOS  output/SPY/2026-01-26_485BPOS_.../prospectus.htm
QQQ          OK  2025-12-19  485BPOS  output/QQQ/2025-12-19_485BPOS_.../prospectus.htm
VOO          OK  2026-04-28  485BPOS  output/VOO/2026-04-28_485BPOS_.../prospectus.htm
SWVXX        OK  2026-04-28  485BPOS  output/SWVXX/2026-04-28_485BPOS_.../prospectus.htm
FDRXX        OK  2026-01-26  485BPOS  output/FDRXX/2026-01-26_485BPOS_.../prospectus.htm
BOGUS123     NOT FOUND  Ticker 'BOGUS123' not found in any EDGAR index (did you mean 'BGUS'?)
                            Prospectus Fetch Summary
┏━━━━┳━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━┳━━━━━━━━━┳━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃    ┃ Ticker   ┃ Status           ┃ Form    ┃ Filed      ┃ Saved To / Error                  ┃
┡━━━━╇━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━╇━━━━━━━━━╇━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┩
│ ✓  │ SWPPX    │ OK               │ 485BPOS │ 2026-02-26 │ output/SWPPX/…/prospectus.htm     │
│ ✓  │ TRBCX    │ OK               │ 485BPOS │ 2026-02-25 │ output/TRBCX/…/prospectus.htm     │
│ ✓  │ SPY      │ OK               │ 485BPOS │ 2026-01-26 │ output/SPY/…/prospectus.htm       │
│ ✓  │ QQQ      │ OK               │ 485BPOS │ 2025-12-19 │ output/QQQ/…/prospectus.htm       │
│ ✓  │ VOO      │ OK               │ 485BPOS │ 2026-04-28 │ output/VOO/…/prospectus.htm       │
│ ✓  │ SWVXX    │ OK               │ 485BPOS │ 2026-04-28 │ output/SWVXX/…/prospectus.htm     │
│ ✓  │ FDRXX    │ OK               │ 485BPOS │ 2026-01-26 │ output/FDRXX/…/prospectus.htm     │
│ ✗  │ BOGUS123 │ TICKER_NOT_FOUND │         │            │ Ticker 'BOGUS123' not found in    │
│    │          │                  │         │            │ any EDGAR index (did you mean      │
│    │          │                  │         │            │ 'BGUS'?)                           │
└────┴──────────┴──────────────────┴─────────┴────────────┴───────────────────────────────────┘
7 succeeded  1 failed
```

Exit code is 1 if any ticker fails; 0 if all succeed or skip.

### Inspect (dry-run, no download)

```bash
prospectus-fetch inspect VUSXX SPY
```

Prints the resolved CIK, series/class IDs, resolution source, chosen form, filing date, accession number, selection reason, and the document URL that *would* be fetched — without downloading anything. Useful for verifying resolution before committing to a large batch run.

### Key flags

| Flag | Default | Purpose |
|---|---|---|
| `--out PATH` | `output/` | Directory to save files and the manifest |
| `--forms 485BPOS,497K` | `485BPOS,497K` | Form priority, comma-separated |
| `--force` | off | Re-download even if the file already exists |
| `--from-file FILE` | — | Text file with one ticker per line (`#` lines ignored) |
| `--json` | off | Print structured JSON to stdout instead of the Rich table |
| `--extract` | off | Run LLM enrichment after download (see §3 LLM enrichment below) |
| `-v / --verbose` | off | Enable DEBUG logging to stderr |
| `--user-agent TEXT` | env `SEC_USER_AGENT` | Override the SEC User-Agent header |

### Output layout

```
output/
├── manifest.json                          # all runs, upserted by accession
├── summary.json                           # last run metadata + per-ticker results
├── summary.csv                            # same, tabular
└── VUSXX/
    └── 2025-12-19_485BPOS_000119312525325143/
        ├── prospectus.htm
        └── extracted.json                 # present only when --extract was used
```

`manifest.json` entry example (with `--extract`):

```json
{
  "ticker": "VUSXX",
  "cik": 891190,
  "series_id": "S000002233",
  "class_id": "C000005732",
  "form": "485BPOS",
  "filing_date": "2025-12-19",
  "accession": "0001193125-25-325143",
  "source_url": "https://www.sec.gov/Archives/edgar/data/891190/000119312525325143/f43635d1.htm",
  "saved_path": "output/VUSXX/2025-12-19_485BPOS_000119312525325143/prospectus.htm",
  "sha256": "788bbe973ca258d8877624d54cf03939a040f2723858018d2ac29c083a39b3b7",
  "selection_reason": "latest 485BPOS covering series S000002233",
  "retrieved_at": "2026-06-14T00:18:57+00:00",
  "validation": {
    "passed": true,
    "signals_found": ["series_id:S000002233", "class_id:C000005732", "ticker:VUSXX"],
    "note": "covers this fund (series/class ID match)"
  },
  "extraction": {
    "investment_objective": "Seeks to provide current income consistent with the preservation of capital and liquidity.",
    "expense_ratio": "0.0011",
    "minimum_investment": 3000,
    "principal_risks": ["Credit risk", "Interest rate risk", "Liquidity risk", "Market risk"],
    "model": "claude-haiku-4-5-20251001",
    "prompt_version": "v1",
    "ticker": "VUSXX"
  }
}
```

### LLM enrichment (`--extract`)

```bash
pip install 'prospectus-fetcher[extract]'
export ANTHROPIC_API_KEY="sk-ant-..."
prospectus-fetch fetch VUSXX --extract --out ./output
```

After downloading and validating each prospectus, `--extract` runs the HTML through `claude-haiku` to produce `extracted.json` with four fields: `investment_objective`, `expense_ratio` (decimal string), `minimum_investment` (integer USD), and `principal_risks` (list). Output is validated with Pydantic; one automatic re-prompt is attempted on schema violations before failing cleanly. The retrieval pipeline always runs regardless of whether the API key is present — if `ANTHROPIC_API_KEY` is not set, extraction is silently skipped with a log message and everything else proceeds normally.

### Running in Docker

```bash
docker build -t prospectus-fetch ./prospectus-fetcher

# Single ticker
docker run --rm \
  -e SEC_USER_AGENT="Your Name your@email.com" \
  -v "$(pwd)/output:/app/output" \
  prospectus-fetch fetch VUSXX --out /app/output

# With extraction
docker run --rm \
  -e SEC_USER_AGENT="Your Name your@email.com" \
  -e ANTHROPIC_API_KEY="sk-ant-..." \
  -v "$(pwd)/output:/app/output" \
  prospectus-fetch fetch VUSXX --extract --out /app/output
```

### Scheduled GitHub Actions refresh

The workflow at [`.github/workflows/refresh.yml`](../.github/workflows/refresh.yml) runs every Monday at 06:00 UTC and on `workflow_dispatch`. It reads `watchlist.txt` (edit to add/remove tickers), fetches all prospectuses, and uploads `output/` as a build artifact retained for 90 days.

**Required secret:** Add `SEC_USER_AGENT` as a repository secret under Settings → Secrets and variables → Actions. Format: `"Your Name your@email.com"`. Never hardcode it.

---

## 4. How it works

### Pipeline

```
ticker
  └─ normalize (strip, uppercase, deduplicate)
       └─ resolve identity (mf_map → company_map → full-text search)
            └─ select filing (Atom feed or submissions API)
                 └─ locate document (primaryDocument or largest .htm in index.json)
                      └─ download (atomic write, sha256)
                           └─ validate (series/class ID signals in scan window)
                                └─ extract (--extract: LLM → Pydantic → extracted.json)  [optional]
                                     └─ record (manifest.json, summary.json, summary.csv)
```

### The EDGAR identity model

The SEC registers funds in three nested layers:

**Registrant (trust / CIK)** — the legal entity that files with the SEC. A single CIK can cover dozens of funds. Vanguard Admiral Funds files under CIK 891190 and encompasses all its money-market and bond share classes under one umbrella registrant. Vanguard Index Funds files separately under CIK 36405 and covers VOO, VTSAX, and others.

**Series (S-id)** — one fund within the registrant trust. VUSXX belongs to series `S000002233` (Vanguard Treasury Money Market Fund) within CIK 891190. VMFXX belongs to a different series (`S000002852`, Vanguard Federal Money Market Fund) within the same CIK. The series is the economic unit — it has its own NAV, holdings, and prospectus sections.

**Class (C-id)** — one share class within a series. VUSXX maps to class `C000005732`. A series often has Investor, Admiral, and Institutional classes with different minimums and expense ratios; each gets a distinct ticker and C-id.

**Why this matters for filing selection:** A 485BPOS filed by CIK 891190 is a single multi-hundred-page HTML document covering *all* series and classes under that trust. Without series-scoping, downloading the trust's latest filing is easy — but confirming you got the right fund requires checking that the document actually mentions the specific series or class you requested. The tool uses the series ID as the primary filing selector (via the EDGAR browse-Atom feed keyed by series ID) to find the right accession, then verifies the correct IDs appear in the downloaded document.

---

## 5. Design decisions

| Decision | Rationale |
|---|---|
| **Structured EDGAR API endpoints over HTML scraping** | EDGAR exposes machine-readable JSON at `data.sec.gov/submissions/`, `sec.gov/files/company_tickers_mf.json`, and `sec.gov/files/company_tickers.json`. These are stable, versioned interfaces that require no HTML parsing. The only XML consumed is the browse-edgar Atom feed, which is also a documented endpoint. Scraping the HTML search pages would be brittle, slower, and more likely to trigger rate limits. |
| **485BPOS first, 497K fallback; 497 / 497J / 485APOS excluded** | A 485BPOS is a post-effective registration amendment — the complete, current prospectus. A 497K is a summary prospectus (Key Information Document) — legally sufficient but abbreviated. A plain 497 is a supplement or sticker update; a 497J is a notice of no-amendment; a 485APOS is a not-yet-effective amendment. Only the first two are prospectuses an investor would actually read. Including supplements would return partial documents; including 485APOS would return documents not yet in legal effect. |
| **Series-scoped selection as primary defense + post-download content validation as recorded sanity check** | Series-scoped selection (querying the EDGAR browse-Atom feed by series ID) narrows candidates to the correct fund family *before* downloading anything, which is cheaper than fetching a 5–7 MB document and then checking it. However, the browse-Atom feed is not truly series-scoped — it returns all filings for the registrant CIK — and a multi-fund trust's 485BPOS covers every series in the trust. Post-download validation (scanning for series/class IDs in the HTML) confirms that the document mentions this specific fund and records the evidence in the manifest. The two layers are complementary: selection finds the right *accession and filing date*; validation confirms the *document content*. Validation is a recorded observation, never a gate that deletes the file — a missed scan does not mean the document is wrong, and keeping the file enables manual inspection. |
| **Sequential requests with a token-bucket rate limiter at 5 req/s** | The SEC fair-access policy caps automated clients at 10 req/s and blocks user agents that do not identify themselves. A token-bucket rate limiter at 5 req/s leaves headroom, avoids 429 responses, and is a responsible default for a government API that serves the entire financial industry. Aggressive async concurrency would save seconds per run but risks a 24-hour IP block that would affect all SEC data access. |
| **Manifest + idempotent re-runs** | Writing a manifest keyed by accession number after every successful download turns a one-shot script into a reusable automation building block. Re-running the same tickers skips existing files (`SKIPPED_EXISTING`), enabling scheduled refreshes that only fetch newly filed prospectuses without re-downloading stale ones. `--force` overrides this for explicit refreshes. The sha256 hash in the manifest enables downstream change detection without re-reading the full document. |

---

## 6. Edge cases handled

| Case | Behavior |
|---|---|
| **Unknown / invalid ticker** | All three resolution strategies fail → `TickerNotFound` → `TICKER_NOT_FOUND` status + did-you-mean suggestion via `difflib.get_close_matches` (e.g. `BOGUS123` → "did you mean 'BGUS'?"). Never crashes; other tickers in the batch continue. |
| **ETF vs mutual fund routing** | `company_tickers_mf.json` covers Investment Company Act registrants and includes series/class IDs. `company_tickers.json` covers exchange-listed securities more broadly but lacks series/class IDs. SPY (CIK 884394) and QQQ (CIK 1067839) resolve via the company map and are selected via submissions; VOO (CIK 36405, series `S000002545`) resolves via the MF map and is selected via the series-scoped Atom feed. The three-tier chain handles both transparently. |
| **497K fallback** | When no 485BPOS is found (unusual but possible for newer or smaller ETFs), the tool selects the most recent 497K summary prospectus. |
| **Supplement exclusion** | Forms 497 (supplement/sticker) and 497J (notice of no-update) are filtered at the candidate stage and never selected, even if they were filed more recently than a 485BPOS. |
| **Multiple tickers sharing one filing** | VOO and VTSAX (both CIK 36405) share accession `0000036405-26-000181`. An in-run accession cache prevents double-downloading: the second ticker reuses the already-saved path and sha256, and a separate manifest entry is written for each ticker. |
| **Multi-fund trust documents** | A single Vanguard 485BPOS covers all series under CIK 891190. Series-scoped selection finds the right accession; content validation confirms the series/class IDs appear in the document. |
| **403 / 429 / 5xx responses** | `tenacity` retries up to 4 attempts with exponential backoff (2 s, 4 s, 8 s, capped at 60 s). `Retry-After` headers are respected when present. The token bucket prevents most 429 responses before they occur. |
| **Idempotent re-runs** | Files already on disk are skipped with `SKIPPED_EXISTING`. `--force` re-downloads and overwrites. |
| **Input hygiene** | Tickers are stripped and uppercased before any lookup. Blank lines and `#`-prefixed comment lines are skipped in `--from-file` input. Duplicate tickers in a single run are silently de-duplicated. |

---

## 7. Assumptions and limitations

**Definition of "latest prospectus":** The most recent *effective* registration statement (485BPOS) whose filing date appears in `filings.recent` and that covers the fund's series. If no 485BPOS is present, the most recent 497K summary prospectus is used. Plain 497 supplements and 497J no-amendment notices are excluded because they do not constitute a complete prospectus. 485APOS amendments are excluded because they are not yet legally effective at the time of filing.

**`filings.recent` window:** The EDGAR submissions API returns up to 1,000 filings in `filings.recent`. For long-operating registrants, older filings are paginated under `filings.files`. This tool assumes the latest prospectus is always within the 1,000-entry window, which holds for any fund that has filed anything in the past several years. Extremely dormant registrants with no recent activity are not handled.

**EDGAR full-text search index:** The EFTS full-text search endpoint used as a last-resort resolver indexes filings back to approximately 2001. Funds registered before that year that have never re-filed may not be discoverable via the third resolution tier.

**US-listed funds only:** The tool resolves tickers via SEC EDGAR, which covers US-domiciled investment companies. Foreign funds, closed-end funds with unusual registration paths, and instruments that file under different form types (e.g. N-14 for mergers) may not resolve correctly.

**HTML format assumed:** The tool downloads `.htm`/`.html` documents. A small number of very old EDGAR filings are text-only (`.txt`) or XBRL-only. These would be saved correctly but may not render as expected.

---

## 8. Testing

### Unit tests (no network required)

```bash
pip install -e "prospectus-fetcher[dev]"
cd prospectus-fetcher
pytest -m "not network" -v
```

```
tests/test_url_builders.py::test_submissions_url_zero_pads_to_10   PASSED
tests/test_url_builders.py::test_archive_index_url_strips_dashes   PASSED
... (41 tests total)
41 passed, 3 deselected in 0.12s
```

Tests cover:

- **URL builders** — exact URL shapes for all 5 EDGAR endpoints
- **Resolver** — MF-map hit (VUSXX), company-map hit (SPY/QQQ), full-text fallback, ticker normalization, `TickerNotFound`
- **Filing selection** — form priority, EXCLUDE set, NEVER_EFFECTIVE set, recency + accession tie-break, Atom parsing + accession deduplication, `NoProspectusFound`
- **Validation** — strong signals (series/class ID), weak signal (ticker whole-word), no-signal failure, missing file

All fixtures are static JSON/XML files under `tests/fixtures/`; no live network calls are made.

### Lint and type checks

```bash
cd prospectus-fetcher
ruff check src/ tests/    # All checks passed!
mypy src/                 # Success: no issues found in 11 source files
```

### Live smoke tests (requires network)

```bash
export SEC_USER_AGENT="Your Name your@email.com"
cd prospectus-fetcher
pytest -m network -v
```

Runs three live EDGAR calls for VUSXX (resolve → select → locate) and asserts that real accession numbers and archive URLs come back correctly. Skipped by default in CI.

---

## 9. Future work

- **Object storage backend (e.g. S3):** Replace the local filesystem output with an S3 sink so prospectuses are accessible to downstream services without sharing a filesystem. The existing output layout (`{ticker}/{date}_{form}_{accession}/prospectus.htm`) maps cleanly to an S3 key prefix with no structural changes. The GitHub Actions workflow already produces a self-contained `output/` artifact that could be pushed to S3 as a post-step.

- **Change-detection alerting:** The weekly refresh workflow currently uploads all output as an artifact. Comparing new accession numbers against the previous run's `manifest.json` would detect newly filed prospectuses and emit an event (webhook, SNS, Slack) automatically. The sha256 field enables content-level diffing for cases where the same accession is amended.

- **Manifest in a database:** Move `manifest.json` to a lightweight SQL store (SQLite locally, Postgres in production) keyed on `(ticker, accession)`. This enables queries like "which funds updated their prospectus in the last 30 days?" and eliminates the read-modify-write race condition in the current JSON approach.

- **Observability:** Add structured JSON logging and optional OpenTelemetry spans so a scheduled run in a container can be monitored with standard tooling. The current logging is human-readable and useful interactively but not machine-parseable for alerting.
