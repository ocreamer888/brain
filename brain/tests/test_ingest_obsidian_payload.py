"""Obsidian ingest passes vault provenance into save_memory."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def obsidian_ingest_mod(tmp_path, monkeypatch):
    repo = Path(__file__).resolve().parents[2]
    monkeypatch.chdir(repo)
    monkeypatch.syspath_prepend(str(repo))
    mock_save = MagicMock()
    with patch("brain.api_client.save_memory", mock_save):
        spec = importlib.util.spec_from_file_location(
            "_ingest_obsidian_test_mod",
            repo / "brain" / "bootstrap" / "09_ingest_obsidian.py",
        )
        mod = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(mod)
    vault = tmp_path / "vault"
    (vault / "02 Areas" / "acme").mkdir(parents=True)
    mod.VAULT = vault
    monkeypatch.setattr(mod.time, "sleep", lambda *a, **k: None)
    return mod, vault, mock_save


def test_ingest_obsidian_small_file_sends_vault_file_path(obsidian_ingest_mod):
    mod, vault, mock_save = obsidian_ingest_mod
    p = vault / "02 Areas" / "acme" / "Note.md"
    body = " ".join(["word"] * 60)
    p.write_text(body, encoding="utf-8")
    processed: set[str] = set()
    n = mod.ingest_file(p, processed, dry_run=False)
    assert n == 1
    mock_save.assert_called_once()
    kw = mock_save.call_args.kwargs
    assert kw["file_path"] == "vault/02 Areas/acme/Note.md"
    assert kw["title"] == "Note"
    assert kw["source"] == "obsidian"
