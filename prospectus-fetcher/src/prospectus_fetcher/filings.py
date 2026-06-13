"""Select the best 485BPOS (or 485APOS) filing for a resolved FundIdentity.

Key findings from RECON.md:
  - filings.recent holds up to 1000 entries in parallel arrays
  - For multi-fund registrants (e.g. Vanguard Admiral Funds), 485BPOS appears
    at index 52 — not in the top 20. Always scan the full recent array.
  - The Atom feed (browse-edgar) is NOT series-scoped even when CIK=seriesId;
    it returns all filings for the registrant. Use submissions JSON instead.
  - primaryDocument field from submissions is the reliable way to identify the
    main .htm; index.json has no primary-document marker.
  - The primary document may be a multi-fund bundle (e.g. all Vanguard Admiral
    funds in one file). series_scoped=False should be set in that case.
"""

from __future__ import annotations

from prospectus_fetcher.errors import NoProspectusFound
from prospectus_fetcher.models import Filing, FundIdentity

_PROSPECTUS_FORMS = ("485BPOS", "485APOS")


# TODO: implement select_filing(identity, session) -> Filing
#   1. Call edgar.get_submissions(identity.cik, session)
#   2. Scan filings.recent parallel arrays for the most recent 485BPOS (prefer over 485APOS)
#      Arrays: form, filingDate, accessionNumber, primaryDocument
#   3. Build Filing(
#          form=..., filing_date=date.fromisoformat(filingDate),
#          accession=accessionNumber,  # keep dashed form
#          primary_document=primaryDocument,
#          series_scoped=False,        # submissions-based lookup is registrant-scoped
#          selection_reason="submissions_recent_scan",
#      )
#   4. If no 485* found in recent 1000, fall back to full_text_search (edgar.py)
#      and raise NoProspectusFound if that also yields nothing
def select_filing(identity: FundIdentity) -> Filing:
    # TODO: implement
    raise NoProspectusFound(identity.ticker, list(_PROSPECTUS_FORMS))
