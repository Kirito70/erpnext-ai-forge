"""Shared pytest fixtures for forge tests."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture(scope="session")
def repo_root() -> Path:
    """Locate the erpnext-ai-forge repo root for integration tests."""
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "forge.config.yaml").is_file():
            return parent
    raise RuntimeError("Could not locate erpnext-ai-forge repo root from tests")
