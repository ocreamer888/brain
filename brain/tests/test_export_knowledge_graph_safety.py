"""Security audit 2026-11-05, finding #8: export_knowledge_graph.py used to
wipe --out by DEFAULT (needed --no-clean to opt out), and `_VAULT / args.out`
never checked the result stayed inside the vault -- an absolute --out value
silently discards `_VAULT` entirely (pathlib's own `/` semantics), so the
unconditional wipe could rmtree anywhere. Both are fixed: --clean is now the
explicit opt-in, and out_dir must resolve inside _VAULT or the tool refuses.

Uses an empty `memories` table (0 rows) so the per-memory loop (which calls
out to the live brain API for semantic neighbours) never runs -- this test
is about the out_dir/--clean wiring, not the export content.
"""
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


def _empty_db(tmp_path: Path) -> Path:
    db_path = tmp_path / "brain.db"
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE memories (id TEXT, content TEXT, type TEXT, project TEXT, source TEXT, importance REAL)")
    conn.commit()
    conn.close()
    return db_path


def _run_main(monkeypatch, argv, vault, module):
    monkeypatch.setattr(module, "_VAULT", vault)
    monkeypatch.setattr(sys, "argv", ["export_knowledge_graph.py", *argv])
    return module.main()


def test_default_run_does_not_wipe_existing_out_dir(tmp_path, monkeypatch):
    import brain.tools.export_knowledge_graph as mod
    vault = tmp_path / "vault"
    vault.mkdir()
    out_dir = vault / "brain-graph"
    out_dir.mkdir()
    sentinel = out_dir / "keep-me.md"
    sentinel.write_text("should survive a default (non --clean) run")
    db = _empty_db(tmp_path)

    rc = _run_main(monkeypatch, ["--db", str(db)], vault, mod)

    assert rc == 0
    assert sentinel.exists(), "default run must not wipe out_dir (opt-in --clean required now)"


def test_clean_flag_wipes_out_dir(tmp_path, monkeypatch):
    import brain.tools.export_knowledge_graph as mod
    vault = tmp_path / "vault"
    vault.mkdir()
    out_dir = vault / "brain-graph"
    out_dir.mkdir()
    (out_dir / "stale.md").write_text("stale note from a previous run")
    db = _empty_db(tmp_path)

    rc = _run_main(monkeypatch, ["--db", str(db), "--clean"], vault, mod)

    assert rc == 0
    assert not (out_dir / "stale.md").exists(), "--clean must still wipe when explicitly requested"


def test_out_escaping_vault_is_refused(tmp_path, monkeypatch, capsys):
    import brain.tools.export_knowledge_graph as mod
    vault = tmp_path / "vault"
    vault.mkdir()
    outside = tmp_path / "outside_the_vault"
    outside.mkdir()
    (outside / "do-not-touch.txt").write_text("important")
    db = _empty_db(tmp_path)

    # An absolute --out value: pathlib's `/` operator discards _VAULT
    # entirely for an absolute right-hand side, so without the containment
    # check this would resolve straight to `outside`.
    rc = _run_main(monkeypatch, ["--db", str(db), "--out", str(outside), "--clean"], vault, mod)

    assert rc == 1
    assert (outside / "do-not-touch.txt").exists(), "must refuse before ever calling rmtree"
    assert "must resolve inside" in capsys.readouterr().err
