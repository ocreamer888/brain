# brain/tests/test_ingest_knowledge.py
"""Idempotent corpus ingest (spec 2026-08-06): content-hash skip, supersede
on change, provenance shape."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from unittest.mock import patch

from brain.tools import ingest_knowledge as ik


def test_provenance_round_trip():
    p = ik.provenance("abc123", 4, "deadbeef00112233")
    assert p == "corpus:abc123:c4:sha:deadbeef00112233"
    assert ik.sha_of_provenance(p) == "deadbeef00112233"
    assert ik.sha_of_provenance(None) is None
    assert ik.sha_of_provenance("legacy string") is None


def test_build_chunks_deterministic_hashes():
    text = "# Title\n\n" + ("alpha beta gamma delta " * 40) + "\n\n## Section\n\n" + ("word " * 80)
    a = ik.build_chunks(text, "doc")
    b = ik.build_chunks(text, "doc")
    assert a == b
    assert all(len(sha) == 16 for _, _, sha in a)


def _write_doc(tmp_path, body):
    f = tmp_path / "manual.md"
    f.write_text(body, encoding="utf-8")
    return f


_DOC_V1 = "# Manual\n\n" + ("stable intro words " * 40) + "\n\n## Webhooks\n\n" + ("retry logic detail " * 40)
_DOC_V2 = "# Manual\n\n" + ("stable intro words " * 40) + "\n\n## Webhooks\n\n" + ("changed retry semantics " * 40)


def test_first_ingest_saves_all_chunks(tmp_path):
    f = _write_doc(tmp_path, _DOC_V1)
    with patch.object(ik, "existing_chunks", return_value=[]), \
         patch.object(ik, "save_memory", return_value="m-1") as save:
        saved, skipped, superseded = ik.ingest_file(
            f, project="p", corpus="manuals", source="obsidian",
            entities=False, dry_run=False,
        )
    assert saved == save.call_count and saved > 0
    assert skipped == 0 and superseded == 0
    kw = save.call_args.kwargs
    assert kw["memory_type"] == "knowledge"
    assert kw["file_path"] == str(f)
    assert kw["extracted_by"].startswith("corpus:")
    assert "corpus:manuals" in kw["tags"] and "brain/ingest" in kw["tags"]


def test_reingest_unchanged_doc_adds_zero_rows(tmp_path):
    f = _write_doc(tmp_path, _DOC_V1)
    chunks = ik.build_chunks(_DOC_V1, "manual")
    doc_id = ik.doc_id_for(str(f))
    existing = [
        (f"old-{i}", ik.provenance(doc_id, i, sha))
        for i, (_, _, sha) in enumerate(chunks)
    ]
    with patch.object(ik, "existing_chunks", return_value=existing), \
         patch.object(ik, "save_memory") as save, \
         patch.object(ik, "mark_superseded") as sup:
        saved, skipped, superseded = ik.ingest_file(
            f, project="p", corpus=None, source="obsidian",
            entities=False, dry_run=False,
        )
    save.assert_not_called()
    sup.assert_not_called()
    assert saved == 0 and skipped == len(chunks) and superseded == 0


def test_changed_chunk_superseded_unchanged_skipped(tmp_path):
    f = _write_doc(tmp_path, _DOC_V2)
    old_chunks = ik.build_chunks(_DOC_V1, "manual")
    doc_id = ik.doc_id_for(str(f))
    existing = [
        (f"old-{i}", ik.provenance(doc_id, i, sha))
        for i, (_, _, sha) in enumerate(old_chunks)
    ]
    with patch.object(ik, "existing_chunks", return_value=existing), \
         patch.object(ik, "save_memory", return_value="new-id") as save, \
         patch.object(ik, "mark_superseded") as sup:
        saved, skipped, superseded = ik.ingest_file(
            f, project="p", corpus=None, source="obsidian",
            entities=False, dry_run=False,
        )
    # The intro section is byte-identical between versions → skipped;
    # the webhooks section changed → saved fresh, old row superseded.
    assert skipped >= 1
    assert saved >= 1
    assert superseded == saved
    sup.assert_called_with(sup.call_args.args[0], "new-id")


def test_dry_run_never_writes(tmp_path):
    f = _write_doc(tmp_path, _DOC_V1)
    with patch.object(ik, "existing_chunks", return_value=[]), \
         patch.object(ik, "save_memory") as save, \
         patch.object(ik, "mark_superseded") as sup:
        saved, _, _ = ik.ingest_file(
            f, project="p", corpus=None, source="obsidian",
            entities=False, dry_run=True,
        )
    save.assert_not_called()
    sup.assert_not_called()
    assert saved > 0


# ---------------------------------------------------------------------------
# existing_chunks / mark_superseded are API-routed (never direct SQLite) —
# spec 2026-08-06 footgun fix. These mock brain.api_client, not sqlite3.
# ---------------------------------------------------------------------------

def test_existing_chunks_calls_api_not_sqlite():
    api_rows = [
        {"id": "m-1", "extracted_by": "corpus:abc:c0:sha:deadbeef00112233"},
        {"id": "m-2", "extracted_by": None},
    ]
    with patch.object(ik.api_client, "knowledge_chunks_for_file", return_value=api_rows) as call:
        result = ik.existing_chunks("/docs/manual.md")
    call.assert_called_once_with("/docs/manual.md")
    assert result == [
        ("m-1", "corpus:abc:c0:sha:deadbeef00112233"),
        ("m-2", None),
    ]


def test_mark_superseded_calls_api_not_sqlite():
    with patch.object(ik.api_client, "mark_superseded") as call:
        ik.mark_superseded("old-id", "new-id")
    call.assert_called_once_with("old-id", "new-id")


def test_no_direct_sqlite_usage_in_module():
    """Acceptance criterion: the CLI must never open brain.db directly."""
    src = Path(ik.__file__).read_text(encoding="utf-8")
    assert "sqlite3" not in src


# ---------------------------------------------------------------------------
# --on-db-host guard: refuse non-loopback BRAIN_API_URL unless explicitly
# overridden. Loopback always runs freely.
# ---------------------------------------------------------------------------

def test_guard_allows_loopback_without_flag(monkeypatch):
    monkeypatch.setenv("BRAIN_API_URL", "http://127.0.0.1:8787")
    ik.guard_api_host(on_db_host=False)  # must not raise


def test_guard_allows_localhost_without_flag(monkeypatch):
    monkeypatch.setenv("BRAIN_API_URL", "http://localhost:8787")
    ik.guard_api_host(on_db_host=False)  # must not raise


def test_guard_allows_missing_env_default_loopback(monkeypatch):
    monkeypatch.delenv("BRAIN_API_URL", raising=False)
    ik.guard_api_host(on_db_host=False)  # must not raise


def test_guard_refuses_remote_host_without_flag(monkeypatch):
    monkeypatch.setenv("BRAIN_API_URL", "http://192.168.1.50:8787")
    try:
        ik.guard_api_host(on_db_host=False)
        assert False, "expected SystemExit"
    except SystemExit as e:
        assert "192.168.1.50" in str(e)
        assert "--on-db-host" in str(e)


def test_guard_allows_remote_host_with_flag(monkeypatch):
    monkeypatch.setenv("BRAIN_API_URL", "http://192.168.1.50:8787")
    ik.guard_api_host(on_db_host=True)  # must not raise
