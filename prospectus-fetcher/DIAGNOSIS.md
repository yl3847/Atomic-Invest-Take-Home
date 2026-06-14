# Diagnosis: VOO / VTSAX shared accession 0000036405-26-000181

**Date:** 2026-06-14  
**Verdict: COMBINED BOOK — current selection behavior is correct. No wrong-document bug.**

---

## Phase 1 findings

### Step 1 — `inspect VOO VTSAX`

| Ticker | CIK   | Series ID  | Class ID   | Source  | Form    | Filed      | Accession            | Selection reason                          |
|--------|-------|------------|------------|---------|---------|------------|----------------------|-------------------------------------------|
| VOO    | 36405 | S000002839 | C000092055 | mf_map  | 485BPOS | 2026-04-28 | 0000036405-26-000181 | latest 485BPOS covering series S000002839 |
| VTSAX  | 36405 | S000002848 | C000007806 | mf_map  | 485BPOS | 2026-04-28 | 0000036405-26-000181 | latest 485BPOS covering series S000002848 |

Both tickers resolve to the same accession. The selection reason correctly records the *per-series* selection reason in each case, so the Atom-feed path ran for each series separately.

### Step 2 — Series Atom feeds queried separately

**VOO feed** (`CIK=S000002839&type=485&output=atom`):

```
485BPOS  2026-04-28  0000036405-26-000181   ← latest
485BPOS  2025-04-29  0001683863-25-004078
485BPOS  2024-04-26  0001683863-24-002986
... (identical history going back to 2018)
```

**VTSAX feed** (`CIK=S000002848&type=485&output=atom`):

```
485BPOS  2026-04-28  0000036405-26-000181   ← latest
485BPOS  2025-04-29  0001683863-25-004078
485BPOS  2024-04-26  0001683863-24-002986
... (identical history going back to 2015)
```

**Both series feeds return the identical accession list.** This is the definitive signal: EDGAR itself associates `0000036405-26-000181` with BOTH series `S000002839` and `S000002848`. The tool correctly picked the most-recent 485BPOS from each series' own feed; they happen to be the same filing.

### Step 3 — Document content verification

Scanning the first 2.1 MB of `f45032d1.htm` (the 18.5 MB primary document):

| Signal | Found? |
|--------|--------|
| "Vanguard 500 Index Fund" | **FOUND** |
| "Vanguard Total Stock Market Index Fund" | **FOUND** |
| Series ID S000002839 (VOO) | **FOUND** |
| Series ID S000002848 (VTSAX) | **FOUND** |
| Class  ID C000092055 (VOO) | **FOUND** |
| Class  ID C000007806 (VTSAX) | **FOUND** |

The document covers both funds by name, series ID, and class ID.

### Step 4 — SGML filing header

The SGML submission header for `0000036405-26-000181` lists **12 fund series** explicitly under `<SERIES-NAME>` tags:

1. Vanguard 500 Index Fund  
2. Vanguard Value Index Fund  
3. Vanguard Extended Market Index Fund  
4. Vanguard Growth Index Fund  
5. Vanguard Large-Cap Index Fund  
6. Vanguard Mid-Cap Index Fund  
7. Vanguard Small-Cap Index Fund  
8. Vanguard Small-Cap Growth Index Fund  
9. Vanguard Small-Cap Value Index Fund  
10. **Vanguard Total Stock Market Index Fund**  
11. Vanguard Mid-Cap Growth Index Fund  
12. Vanguard Mid-Cap Value Index Fund  

This is a combined statutory prospectus covering all Vanguard Index Funds equity series in a single 18.5 MB 485BPOS. EDGAR registers it under all 12 series simultaneously, which is why both VOO's and VTSAX's series feeds return it as their most recent 485BPOS. The in-run accession dedup cache correctly fires — the document is downloaded once and a manifest entry is written for each ticker.

### Step 5 — Verdict

**COMBINED BOOK.** Selection is correct. The tool is not handing either ticker the wrong fund's prospectus; it is handing both the single combined statutory prospectus that covers all Vanguard Index Funds equity series, because that is the document EDGAR associates with each of their series IDs. No code fix is needed in the selection path.

---

## Phase 3 — Validation hardening (recommended regardless)

Even though no wrong-document bug was found here, the validation layer currently allows a bare ticker match to constitute a PASS. In a combined book containing 12 funds' tickers, a ticker-only match gives no fund-specific confidence. Hardening: require at least one STRONG signal (series_id or class_id) for a definitive PASS; ticker-only match is retained as WEAK and results in a distinct note but not VALIDATION_FAILED. This is the correct backstop: a wrong-fund document (e.g. fund A's prospectus handed to fund B) will not contain fund B's series/class IDs, so requiring those IDs would catch the bug even when selection fails.

**Implementation in Phase 3:** The existing `strong` flag already tracks this correctly in `validate.py`. The gap is that `passed = bool(signals_found)` lets a ticker-only hit return `passed=True`. Fix: `passed = strong` (require at least one ID signal); ticker match sets `passed=False` but changes the note to "weak signal only — ticker found but no series/class ID; manual verification recommended."

---

## What the README was wrong about (Phase 4)

1. **§4 VMFXX text:** The README states VMFXX is in "the same CIK" as VUSXX. The inspect output confirms VMFXX is CIK 106830, not 891190 — a separate registrant (Vanguard Money Market Reserves, not Vanguard Admiral Funds).

2. **Series-scoping semantics:** The Atom feed, queried by series ID, returns all filings EDGAR has registered under that series — which includes combined statutory prospectuses that cover multiple series. The feed is not a filter that isolates only "this series' own" filings in the sense of single-fund documents. It returns every filing EDGAR associates with that series, and when a trust files one combined statutory prospectus, EDGAR registers it under all covered series. This is correct behavior, not a bypass of series-scoping.

3. **VUSXX/VMFXX as "separate per-fund prospectuses":** The adjacent accessions `…325143` / `…325144` for VUSXX and VMFXX appear different because VMFXX is a separate registrant (CIK 106830), not because Vanguard Admiral Funds files per-fund documents. Their documents may also be part of the "Vanguard Money Market Funds" combined statutory prospectus co-filed across trusts.

4. **Content validation as the correctness guarantee:** Because the Atom feed returns any filing EDGAR associates with a series — including combined books — the only guarantee that the downloaded document covers *this specific fund* is that its series_id or class_id appears in the document. Ticker-only validation is not sufficient for this.
