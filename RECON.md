# SEC EDGAR Recon — VUSXX End-to-End

**Date:** 2026-06-13  
**User-Agent used:** `YizeLu yl3847@cornell.edu`  
**All requests kept well under 10/s (sequential or lightly parallel).**

---

## Step 1 — `company_tickers_mf.json`

**URL:** `https://www.sec.gov/files/company_tickers_mf.json`

**Shape confirmed:** `{"fields": [...], "data": [[...], ...]}` — arrays, not objects. ✅

**Exact `fields` array (index order matters):**
```
["cik", "seriesId", "classId", "symbol"]
```
Index 0 = `cik` (integer, NOT zero-padded), 1 = `seriesId`, 2 = `classId`, 3 = `symbol`.

**VUSXX row:**
| Field    | Value        |
|----------|--------------|
| cik      | `891190`     |
| seriesId | `S000002233` |
| classId  | `C000005732` |
| symbol   | `VUSXX`      |

**Notes:**
- CIK is an integer in this file, not a string. Zero-pad it yourself: `str(cik).zfill(10)` → `0000891190`.
- The field is named `symbol`, not `ticker`.

---

## Step 2 — Submissions JSON

**URL:** `https://data.sec.gov/submissions/CIK0000891190.json`

**Entity:** `VANGUARD ADMIRAL FUNDS` (CIK `0000891190`)

**`filings.recent` parallel arrays (confirmed keys):**
```
accessionNumber, filingDate, reportDate, acceptanceDateTime, act, form,
fileNumber, filmNumber, items, core_type, size, isXBRL, isInlineXBRL,
isXBRLNumeric, primaryDocument, primaryDocDescription
```

**Deviation from spec:** `filings.recent` does NOT have a `primaryDocDescription` field in the spec description — it DOES exist in reality (`primaryDocDescription`). Also note `core_type` exists but was not in the spec. There is no plain `description` field.

**20 most recent form types (indices 0–19):**
```
0  N-MFP3   2026-06-05
1  497      2026-05-20
2  N-MFP3   2026-05-07
3  N-CSRS   2026-04-29
4  N-CSRS   2026-04-29
5  NPORT-P  2026-04-28
6  NPORT-P  2026-04-28
7  NPORT-P  2026-04-28
8  NPORT-P  2026-04-28
9  NPORT-P  2026-04-28
10 NPORT-P  2026-04-28
11 NPORT-P  2026-04-28
12 NPORT-P  2026-04-28
13 497      2026-04-16
14 N-MFP3   2026-04-07
15 497      2026-03-25
16 497      2026-03-25
17 N-MFP3   2026-03-06
18 497      2026-02-11
19 N-MFP3   2026-02-06
```

**VANGUARD ADMIRAL FUNDS files many form types** — this is a multi-fund registrant. The recent 25 filings contain N-MFP3, 497, N-CSRS, and NPORT-P. No 485BPOS appears until index 52.

**Most recent 485BPOS (index 52):**
| Field           | Value                        |
|-----------------|------------------------------|
| filingDate      | `2025-12-19`                 |
| accessionNumber | `0001193125-25-325143`       |
| primaryDocument | `f43635d1.htm`               |

**`filings.recent` holds 1000 entries** (the API returns up to 1000 recent filings). Older filings are in paginated `filings.files` array (not explored here, but the JSON has a `files` key alongside `recent`).

---

## Step 3 — Series-Scoped Atom Feed

**URL:** `https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK=S000002233&type=485&output=atom`

**CRITICAL DEVIATION:** The URL accepts `CIK=S000002233` (the series ID), but the response is **NOT scoped to that series alone**. The `<cik>` in `<company-info>` resolves to `0000891190` (the registrant CIK, Vanguard Admiral Funds), and the feed returns **all 485 filings for the entire registrant** — not just VUSXX's series.

- **Total entries returned:** 40 (EDGAR caps browse-edgar feeds at 40)
- Using `CIK=S000002233` returns **the same 40 entries** as `CIK=0000891190` with `type=485`. No filtering by series occurs.
- **`type=485` matches ONLY `485BPOS`** for this registrant — no `485APOS` filings present. Type prefix filtering is real but the dataset only had `485BPOS`.

**XML structure for extracting filing info:**
```xml
<entry>
  <category label="form type" scheme="https://www.sec.gov/" term="485BPOS" />
  <content type="text/xml">
    <accession-number>0001193125-25-325143</accession-number>
    <filing-date>2025-12-19</filing-date>
    <filing-type>485BPOS</filing-type>
    <filing-href>https://www.sec.gov/.../index.htm</filing-href>
    <form-name>Post-effective amendment [Rule 485(b)]</form-name>
    <size>21 MB</size>
  </content>
  <link href="https://www.sec.gov/Archives/edgar/data/891190/000119312525325143/0001193125-25-325143-index.htm" />
</entry>
```

**Parse note:** The `<content>` children (`<accession-number>`, `<filing-date>`, `<filing-type>`) have **no XML namespace** — do NOT use the Atom namespace when selecting them. `entry.find('{http://www.w3.org/2005/Atom}content').find('filing-type').text` works.

**One accession appears twice** (once for Act 33, once for Act 40 registration) — deduplicate by accession number when iterating.

---

## Step 4 — Filing Index JSON

**URL:** `https://www.sec.gov/Archives/edgar/data/891190/000119312525325143/index.json`
- Accession `0001193125-25-325143` → strip dashes → `000119312525325143`
- CIK is **unpadded** in the path: `891190`, not `0000891190`

**Shape:**
```json
{"directory": {"item": [...], "name": "...", "parent-dir": "..."}}
```

**`item` entries** each have: `name` (filename), `type` (icon gif name), `size` (bytes as string or empty).

**DEVIATION:** `index.json` does **not** have a `description` or `documentType` field on each item. All files have `type=text.gif` or `type=image2.gif` or `type=compressed.gif`. There is no machine-readable "primary document" flag in this JSON — you cannot tell from `index.json` alone which `.htm` is the prospectus.

**How to identify the primary prospectus `.htm`:**
The reliable method is to use the `primaryDocument` field from `filings.recent` in the submissions JSON (step 2). That field gives `f43635d1.htm` directly. The `index.json` file list confirms the file exists but doesn't mark it as primary.

**Non-image, non-generated files in this filing:**
```
f43635d1.htm   — 5,802,893 bytes  ← PRIMARY PROSPECTUS (from submissions metadata)
f43635d2.htm   — 1,516,475 bytes  ← additional document
f43635d3.htm   —   316,495 bytes
f43635d4.htm   —     2,821 bytes
f43635d5.htm   —   328,470 bytes
f43635d6.htm   —   320,680 bytes
f43635d7.htm   —    31,862 bytes
admiral-20250831.xsd  — XBRL schema
FilingSummary.xml, MetaLinks.json, R1.htm–R177.htm  — XBRL viewer artifacts
```
The primary document is by far the largest `.htm` file (~5.8 MB vs ~1.5 MB for the next).

---

## Step 5 — Primary Prospectus Document

**URL:** `https://www.sec.gov/Archives/edgar/data/891190/000119312525325143/f43635d1.htm`

**Confirmed:** It is a valid HTML prospectus. ✅

- **Total size:** 5,802,893 characters (~5.8 MB)
- **Format:** Inline XBRL (iXBRL) — `<html xmlns:ix="http://www.xbrl.org/2013/inlineXBRL" ...>`
- **Title:** `<title>485BPOS</title>`
- **Contains VUSXX series data:** Confirmed via `contextRef="RetailProspectusMember_S000002233_C000005732"` in the XBRL hidden section.
- **Multi-fund document:** This single `.htm` contains prospectuses for ALL funds in Vanguard Admiral Funds, not just VUSXX. The VUSXX section must be located within the document (e.g., by searching for `S000002233` or the fund name).

---

## Step 6 — `company_tickers.json`

**URL:** `https://www.sec.gov/files/company_tickers.json`

**Shape:** Object-of-objects keyed by sequential integer strings (`"0"`, `"1"`, …), NOT by CIK or ticker.

**Each entry:**
```json
{"cik_str": 1045810, "ticker": "NVDA", "title": "NVIDIA CORP"}
```
`cik_str` is an **integer** (not zero-padded string, despite the name).

**Total entries:** 10,412

**SPY and QQQ:**
| Ticker | cik_str   | title                        |
|--------|-----------|------------------------------|
| SPY    | `884394`  | SPDR S&P 500 ETF TRUST       |
| QQQ    | `1067839` | INVESCO QQQ TRUST, SERIES 1  |

**VUSXX:** NOT in this file. ✅ Confirmed — mutual fund share classes (VUSXX) are in `company_tickers_mf.json`, not `company_tickers.json`. ETFs like SPY and QQQ ARE in this file because they trade on exchanges.

---

## Step 7 — EFTS Full-Text Search

**URL:** `https://efts.sec.gov/LATEST/search-index?q=%22VUSXX%22&forms=485BPOS`

**DEVIATION:** The spec says `search-index` endpoint returns a `message` key on error — in practice, it returned a **valid 200 response** with full Elasticsearch-style results. There is no `message` wrapper.

**Top-level keys:**
```
took, timed_out, _shards, hits, aggregations, query
```

**`hits` structure:**
```json
{
  "total": {"value": 60, "relation": "eq"},
  "max_score": 11.888,
  "hits": [...]
}
```
- `hits.total.value` = `60` total 485BPOS documents mentioning "VUSXX"
- Returns **all 60 hits in one response** (no pagination needed for this query)

**Each hit:**
```json
{
  "_index": "edgar_file",
  "_id": "0000932471-01-500118:admprossai.txt",
  "_score": 11.888,
  "_source": {
    "adsh": "0000932471-01-500118",       ← accession number (dashed)
    "ciks": ["0000891190"],               ← array of CIKs (strings, zero-padded)
    "form": "485BPOS",
    "file_type": "485BPOS",
    "root_forms": ["485BPOS"],
    "file_date": "2001-05-15",
    "display_names": ["VANGUARD ADMIRAL FUNDS INC  (CIK 0000891190)"],
    "file_description": "VANGUARD ADMIRAL TREASURY MONEY MARKET FUND",
    "file_num": ["811-07043"],
    "sequence": 1,
    ...
  }
}
```

**Key fields for the CLI tool:**
- `_source.adsh` → accession number (already dashed, e.g., `0001193125-25-325143`)
- `_source.ciks[0]` → zero-padded CIK string (e.g., `"0000891190"`)
- `_source.form` → form type (e.g., `"485BPOS"`)
- `_source.file_date` → filing date

**DEVIATION:** The `_id` field is `"{accession}:{filename}"` — not just the accession. Strip the `:{filename}` suffix to get the accession (or use `_source.adsh`).

**DEVIATION:** Results include 485BPOS filings from **multiple CIKs** — VUSXX has appeared in filings by at least three registrants: `0000891190` (Vanguard Admiral Funds), `0000106830` (another Vanguard entity), and `0001021882` (Vanguard Treasury Fund). To get the most recent filing for CIK 891190 specifically, filter `_source.ciks` after retrieval.

**Most recent VUSXX 485BPOS from CIK 0000891190:**
```
adsh:      0001193125-25-325143
file_date: 2025-12-19
ciks:      ["0000891190"]
```

---

## Summary of Deviations from Spec

| # | Spec assumption | Reality |
|---|----------------|---------|
| 1 | Atom feed scoped to series when `CIK=S000002233` | **NOT scoped** — resolves to registrant CIK 891190; returns all 485 filings for the whole fund family |
| 2 | Atom feed deduplicates by filing | **Each accession appears twice** (Act 33 + Act 40 registrations); deduplicate by accession |
| 3 | `index.json` identifies the primary document | **No `description` or `type` flag** on items; use `primaryDocument` from `submissions/CIK*.json` instead |
| 4 | Primary document is single-fund prospectus | **Multi-fund document** — all Vanguard Admiral Funds in one `.htm`; must locate VUSXX section within it |
| 5 | `filings.recent` has no `primaryDocDescription` | Field **exists** in reality; also has `core_type` |
| 6 | EFTS `search-index` returns error `message` key | Returns **valid 200** with full ES results when query works |
| 7 | EFTS results scoped to one CIK | Returns hits across **multiple CIKs** for `q="VUSXX"` — must filter by CIK |
| 8 | 485BPOS is in the most recent 20–25 filings | For this registrant, **485BPOS appears at index 52** (filed once/year); recent filings are N-MFP3/497/NPORT-P |
| 9 | `cik_str` in `company_tickers.json` is a string | **Is an integer** despite the name `cik_str` |
| 10 | `company_tickers_mf.json` `cik` field is zero-padded | **Is an integer** — must zero-pad it when constructing submission URLs |

---

## Recommended Lookup Flow for CLI Tool

```
ticker (VUSXX)
  │
  ▼
GET company_tickers_mf.json
  → find row where fields[3] == ticker
  → extract cik (int), seriesId, classId
  │
  ▼
GET submissions/CIK{cik:010d}.json
  → scan filings.recent[form] for "485BPOS"
  → take first match: accessionNumber, primaryDocument
  │
  ▼
Build URL: https://www.sec.gov/Archives/edgar/data/{cik}/{accession_no_dashes}/{primaryDocument}
  → that is the prospectus HTML
```

**Fallback** (if ticker not in `_mf.json` or no 485BPOS in recent 1000):
```
GET efts.sec.gov/LATEST/search-index?q="{ticker}"&forms=485BPOS
  → sort hits by file_date desc
  → filter _source.ciks to match known CIK
  → use _source.adsh as accession
```
