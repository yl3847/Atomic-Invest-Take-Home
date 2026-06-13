# prospectus-fetcher

CLI tool to retrieve the latest SEC fund prospectus for a given ticker from EDGAR.

## Installation

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## Usage

```bash
prospectus-fetch VUSXX
prospectus-fetch VUSXX SPY QQQ --output-dir ./output
```
