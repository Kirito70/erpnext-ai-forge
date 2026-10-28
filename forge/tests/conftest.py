"""Shared pytest fixtures for forge tests."""

from __future__ import annotations

from pathlib import Path

import pytest


FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(autouse=True)
def _isolated_overlay(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """No test reads a developer's forge.config.yaml or ~/.forge.yaml.

    $FORGE_CONFIG wins even when the file is absent, so pointing it at nothing
    gives every test the bare tracked defaults unless it opts into an overlay.
    """
    monkeypatch.setenv("FORGE_CONFIG", str(tmp_path / "no-overlay.yaml"))


@pytest.fixture
def company_overlay(monkeypatch: pytest.MonkeyPatch) -> Path:
    """Opt in to a sample company overlay (managed/lint apps, owned remotes)."""
    path = FIXTURES / "company-overlay.yaml"
    monkeypatch.setenv("FORGE_CONFIG", str(path))
    return path


@pytest.fixture(scope="session")
def repo_root() -> Path:
    """Locate the erpnext-ai-forge repo root for integration tests."""
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "forge.config.example.yaml").is_file():
            return parent
    raise RuntimeError("Could not locate erpnext-ai-forge repo root from tests")
