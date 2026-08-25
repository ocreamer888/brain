"""V-15: lazy brain.ingest must expose submodules (bi.payloads, bi.entity_extractor, …)."""

from __future__ import annotations

import importlib
import sys

import pytest


@pytest.fixture()
def fresh_ingest():
    """Drop cached brain.ingest so each test hits __getattr__."""
    for key in list(sys.modules):
        if key == "brain.ingest" or key.startswith("brain.ingest."):
            del sys.modules[key]
    return importlib.import_module("brain.ingest")


@pytest.mark.parametrize(
    "subname,attr",
    [
        ("payloads", "TAG_BRAIN_INGEST"),
        ("text_chunking", "chunk_by_sections"),
        ("entity_extractor", "extract_entities"),
        ("transcript", "normalize_messages"),
        ("project_infer", "infer_projects"),
    ],
)
def test_lazy_submodule_attribute_access(fresh_ingest, subname, attr):
    """import brain.ingest as bi; bi.payloads must resolve (V-15)."""
    sub = getattr(fresh_ingest, subname)
    assert sub.__name__ == f"brain.ingest.{subname}"
    assert hasattr(sub, attr)


def test_lazy_submodule_heavy_fact_extractor(fresh_ingest):
    sub = fresh_ingest.fact_extractor
    assert sub.__name__ == "brain.ingest.fact_extractor"
    assert hasattr(sub, "extract_facts")


def test_lazy_symbol_still_works(fresh_ingest):
    assert fresh_ingest.TAG_BRAIN_INGEST == "brain/ingest"


def test_dir_includes_submodules(fresh_ingest):
    names = fresh_ingest.__dir__()
    assert "payloads" in names
    assert "entity_extractor" in names


def test_import_ingest_does_not_eagerly_import_torch():
    """INV-INGEST-01 teeth: package import must not pull torch."""
    for key in list(sys.modules):
        if (
            key == "brain.ingest"
            or key.startswith("brain.ingest.")
            or key == "torch"
            or key.startswith("torch.")
        ):
            del sys.modules[key]
    importlib.import_module("brain.ingest")
    assert "torch" not in sys.modules
