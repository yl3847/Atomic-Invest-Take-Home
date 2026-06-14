"""LLM enrichment layer: extract structured fund data from a prospectus HTML.

This module is an optional enrichment layer that sits on top of the deterministic
retrieval core. The core (resolve → select → download) always runs; this module
runs only when --extract is passed AND an Anthropic API key is available.

Design
------
- API key is read from ANTHROPIC_API_KEY env var. No key → no-op with a clear
  message; the rest of the pipeline is unaffected.
- Pydantic validates the model's JSON output. One automatic re-prompt is
  attempted on schema violations before failing cleanly.
- The extracted JSON is saved as extracted.json next to prospectus.htm.
- The manifest entry is updated with model_name, prompt_version, and the
  extraction result.
- Input to the model is a truncated plain-text rendering of the prospectus
  (HTML tags stripped) to stay well within context limits while covering the
  key information sections at the top of the document.

Prompt versioning
-----------------
PROMPT_VERSION is a short string that changes whenever the prompt text changes.
Recording it in the manifest lets consumers know which extraction schema/logic
produced a given extracted.json.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import re
import tempfile
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

# Bump this whenever the system prompt or schema changes.
PROMPT_VERSION = "v1"

# Model to use for extraction. Haiku is fast and cheap; sufficient for structured extraction.
_MODEL = "claude-haiku-4-5-20251001"

# How many characters of plain text to feed the model (~40-50K tokens for large docs).
_TEXT_CHAR_LIMIT = 120_000

# Tag stripper
_TAG_RE = re.compile(r"<[^>]+>")
# Collapse whitespace runs
_WS_RE = re.compile(r"\s{3,}")

_SYSTEM_PROMPT = """\
You are a financial data extraction assistant. You will be given the text of an SEC \
fund prospectus (485BPOS or 497K). Extract exactly the following fields and return \
ONLY a JSON object — no prose, no markdown fences, no explanation:

{
  "investment_objective": "<one or two sentence summary of the fund's stated objective>",
  "expense_ratio": "<annual expense ratio as a decimal string, e.g. '0.0003' for 0.03%, \
or null if not found>",
  "minimum_investment": "<minimum initial investment as an integer (USD), e.g. 3000, \
or null if not stated>",
  "principal_risks": ["<risk name or short phrase>", ...]
}

Rules:
- expense_ratio: look for 'Total Annual Fund Operating Expenses', 'Expense Ratio', or \
'Annual Fund Operating Expenses'. Return the decimal (e.g. 0.0003 not 0.03%). If multiple \
share classes are shown, return the one for the share class described in the document header.
- minimum_investment: look for 'Minimum Initial Investment', 'Minimum Purchase'. Return \
an integer (no commas or $ sign). If it is $0 or waived, return 0. If not stated, return null.
- principal_risks: list each named risk as a short phrase (3–6 words). Return at most 10.
- If a field genuinely cannot be determined from the text, return null for scalars or [] \
for the list.
- Return valid JSON only. No markdown, no comments."""


def _html_to_text(html: str) -> str:
    """Strip HTML tags and collapse whitespace."""
    text = _TAG_RE.sub(" ", html)
    text = _WS_RE.sub("  ", text)
    return text.strip()


def _load_anthropic() -> Any:
    """Return an anthropic.Anthropic client, or None if the package is not installed."""
    try:
        import anthropic
        return anthropic
    except ImportError:
        return None


def _parse_and_validate(raw: str) -> dict[str, Any]:
    """Parse model output as JSON and validate against the expected schema.

    Returns the dict if valid. Raises ValueError with a descriptive message if not.
    """
    try:
        from pydantic import BaseModel, field_validator
    except ImportError:
        # pydantic not installed — minimal validation only
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise ValueError("Model returned non-dict JSON") from None
        return data

    class ExtractionSchema(BaseModel):
        investment_objective: str
        expense_ratio: str | None = None
        minimum_investment: int | None = None
        principal_risks: list[str] = []

        @field_validator("expense_ratio")
        @classmethod
        def expense_ratio_looks_like_decimal(cls, v: str | None) -> str | None:
            if v is None:
                return v
            try:
                float(v)
            except ValueError as e:
                raise ValueError(f"expense_ratio must be a decimal string, got {v!r}") from e
            return v

    parsed = json.loads(raw)
    validated = ExtractionSchema.model_validate(parsed)
    return validated.model_dump()


def extract(
    saved_path: str | Path,
    ticker: str,
) -> dict[str, Any] | None:
    """Run LLM extraction on a saved prospectus HTML.

    Returns a dict with the extracted fields plus metadata, or None if:
    - ANTHROPIC_API_KEY is not set (logs an info message)
    - anthropic package is not installed (logs a warning)
    - extraction fails after one re-prompt (logs a warning, does not raise)

    The extracted.json file is written atomically next to prospectus.htm on success.
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        log.info(
            "--extract requested but ANTHROPIC_API_KEY is not set; "
            "skipping extraction for %s",
            ticker,
        )
        return None

    anthropic_mod = _load_anthropic()
    if anthropic_mod is None:
        log.warning(
            "anthropic package not installed; install with "
            "'pip install prospectus-fetcher[extract]' to use --extract"
        )
        return None

    path = Path(saved_path)
    try:
        html = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        log.warning("extract: could not read %s: %s", path, exc)
        return None

    text = _html_to_text(html)[:_TEXT_CHAR_LIMIT]
    client = anthropic_mod.Anthropic(api_key=api_key)

    user_message = (
        f"Fund ticker: {ticker}\n\n"
        f"Prospectus text (truncated to {_TEXT_CHAR_LIMIT:,} characters):\n\n{text}"
    )

    def _call(messages: list[dict[str, str]]) -> str:
        response = client.messages.create(
            model=_MODEL,
            max_tokens=1024,
            system=_SYSTEM_PROMPT,
            messages=messages,
        )
        return response.content[0].text.strip()

    messages: list[dict[str, str]] = [{"role": "user", "content": user_message}]

    # First attempt
    try:
        raw = _call(messages)
        data = _parse_and_validate(raw)
    except (json.JSONDecodeError, ValueError) as first_err:
        log.info("extract: first attempt invalid for %s (%s); re-prompting", ticker, first_err)
        # One re-prompt: show the model its bad output and ask it to fix
        messages += [
            {"role": "assistant", "content": raw},
            {
                "role": "user",
                "content": (
                    f"Your response was not valid JSON matching the required schema. "
                    f"Error: {first_err}. "
                    "Return ONLY a valid JSON object with the four required keys. "
                    "No markdown, no prose."
                ),
            },
        ]
        try:
            raw2 = _call(messages)
            data = _parse_and_validate(raw2)
        except (json.JSONDecodeError, ValueError) as second_err:
            log.warning(
                "extract: both attempts failed for %s: %s", ticker, second_err
            )
            return None
    except Exception as exc:
        log.warning("extract: API call failed for %s: %s", ticker, exc)
        return None

    result: dict[str, Any] = {
        **data,
        "model": _MODEL,
        "prompt_version": PROMPT_VERSION,
        "ticker": ticker,
    }

    # Write extracted.json atomically next to prospectus.htm
    out_path = path.parent / "extracted.json"
    _atomic_write(out_path, json.dumps(result, indent=2))
    log.info("extract: wrote %s", out_path)

    return result


def _atomic_write(dest: Path, text: str) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=dest.parent, prefix=".tmp_extract_")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.replace(tmp, dest)
    except Exception:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise
