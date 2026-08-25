"""AST trace of hook entry points → required deploy-parity sync files (V-16).

The live Claude Code hooks execute from ``BRAIN_LIVE_HOOK_TREE`` (default
``~/Documents/AI``), not this repo. This module computes which ``brain/`` files
must be byte-identical there by statically tracing ``brain.*`` imports from the
hook scripts ``settings.json`` actually runs.
"""
from __future__ import annotations

import ast
from pathlib import Path

# Files the harness executes directly — always seeds for the trace even if
# nothing else imports them (V-38: entry points were missing from the old list).
HOOK_ENTRY_POINTS: tuple[str, ...] = (
    "brain/hooks/post_tool_use.py",
    "brain/hooks/session_end.py",
)

# Deliberately not synced — tree-local config or off the hook golden path.
EXCLUDED: frozenset[str] = frozenset(
    {
        "brain/config.py",
        "brain/tools/mcp_eval.py",
    }
)

# When any ingest submodule is required, the lazy package init must match too.
_INGEST_INIT = "brain/ingest/__init__.py"


def module_to_relpath(module: str, repo_root: Path) -> str | None:
    """Map ``brain.foo.bar`` to the first existing ``brain/foo/bar.py`` or package ``__init__``."""
    if module != "brain" and not module.startswith("brain."):
        return None
    parts = module.split(".")
    for i in range(len(parts), 0, -1):
        candidate = "/".join(parts[:i]) + ".py"
        if (repo_root / candidate).is_file():
            return candidate
        candidate_init = "/".join(parts[:i]) + "/__init__.py"
        if (repo_root / candidate_init).is_file():
            return candidate_init
    return None


def extract_brain_imports(path: Path) -> set[str]:
    """All static ``brain`` / ``brain.*`` import targets in *path* (any scope)."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                name = alias.name
                if name == "brain" or name.startswith("brain."):
                    modules.add(name)
        elif isinstance(node, ast.ImportFrom):
            mod = node.module
            if mod and (mod == "brain" or mod.startswith("brain.")):
                modules.add(mod)
    return modules


def _apply_package_rules(files: set[str]) -> None:
    """Pull in package ``__init__`` when any sibling submodule under it is synced."""
    ingest_subs = {
        f
        for f in files
        if f.startswith("brain/ingest/") and f.endswith(".py") and f != _INGEST_INIT
    }
    if ingest_subs:
        files.add(_INGEST_INIT)


def derive_sync_set(repo_root: Path) -> set[str]:
    """Transitive ``brain.*`` import closure from :data:`HOOK_ENTRY_POINTS`."""
    files: set[str] = set()
    queue: list[str] = list(HOOK_ENTRY_POINTS)

    while queue:
        rel = queue.pop()
        if rel in files or rel in EXCLUDED:
            continue
        path = repo_root / rel
        if not path.is_file():
            continue
        files.add(rel)
        for mod in extract_brain_imports(path):
            mapped = module_to_relpath(mod, repo_root)
            if mapped and mapped not in files and mapped not in EXCLUDED:
                queue.append(mapped)

    _apply_package_rules(files)
    files -= EXCLUDED
    return files
