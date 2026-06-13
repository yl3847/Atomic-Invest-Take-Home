from __future__ import annotations


class ProspectusFetcherError(Exception):
    """Base error for all prospectus-fetcher failures."""


class TickerNotFound(ProspectusFetcherError):
    def __init__(self, ticker: str, suggestion: str | None = None) -> None:
        self.ticker = ticker
        self.suggestion = suggestion
        msg = f"Ticker '{ticker}' not found in any EDGAR index"
        if suggestion:
            msg += f" (did you mean '{suggestion}'?)"
        super().__init__(msg)


class NoProspectusFound(ProspectusFetcherError):
    def __init__(self, ticker: str, forms_tried: list[str]) -> None:
        self.ticker = ticker
        self.forms_tried = forms_tried
        super().__init__(
            f"No prospectus found for '{ticker}' after searching forms: {forms_tried}"
        )


class DownloadError(ProspectusFetcherError):
    def __init__(self, url: str, reason: str) -> None:
        self.url = url
        self.reason = reason
        super().__init__(f"Failed to download '{url}': {reason}")


class ValidationError(ProspectusFetcherError):
    def __init__(self, path: str, reason: str) -> None:
        self.path = path
        self.reason = reason
        super().__init__(f"Validation failed for '{path}': {reason}")
