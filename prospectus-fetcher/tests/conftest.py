"""Pytest configuration: marks, shared fixtures."""

from __future__ import annotations

from pathlib import Path

import pytest


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "network: mark test as requiring live EDGAR network access (deselect with -m 'not network')",
    )


FIXTURES_DIR = Path(__file__).parent / "fixtures"
