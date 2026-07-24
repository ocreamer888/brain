"""Extraction helpers for claw-code-main source files."""
import ast
import json
import re
import sys
from pathlib import Path
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

CLAW_DIR = Path("/Users/macm1air/Documents/AI/claw-code-main")


def extract_python_record(file_path: Path, base_dir: Path) -> dict:
    """Extract a memory record from a Python source file using AST."""
    rel = str(file_path.relative_to(base_dir))
    try:
        source = file_path.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(source)
    except SyntaxError:
        return _make_record(rel, f"Python file: {rel} (parse error)", ["python"], file_path)

    parts = [f"Python module: {rel}"]

    # Module docstring
    mod_doc = ast.get_docstring(tree)
    if mod_doc:
        parts.append(mod_doc[:300])

    # Classes
    classes = [n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]
    for cls in classes[:10]:
        doc = ast.get_docstring(cls)
        entry = f"class {cls.name}"
        if doc:
            entry += f": {doc[:150]}"
        parts.append(entry)

    # Top-level functions
    funcs = [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    for fn in funcs[:15]:
        args = [a.arg for a in fn.args.args]
        doc = ast.get_docstring(fn)
        entry = f"def {fn.name}({', '.join(args)})"
        if doc:
            entry += f": {doc[:100]}"
        parts.append(entry)

    tags = _tags_from_path(rel)
    return _make_record(rel, " | ".join(parts), tags, file_path)


def extract_rust_record(file_path: Path, base_dir: Path) -> dict:
    """Extract a memory record from a Rust source file via regex."""
    rel = str(file_path.relative_to(base_dir))
    try:
        source = file_path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return _make_record(rel, f"Rust file: {rel}", ["rust"], file_path)

    parts = [f"Rust file: {rel}"]

    # Crate name from path (e.g. rust/crates/runtime/src/session.rs → runtime)
    path_parts = Path(rel).parts
    if "crates" in path_parts:
        crate_idx = list(path_parts).index("crates")
        if crate_idx + 1 < len(path_parts):
            parts.append(f"crate: {path_parts[crate_idx + 1]}")

    # Leading doc comments (/// lines before first non-comment)
    doc_lines = []
    for line in source.splitlines()[:30]:
        stripped = line.strip()
        if stripped.startswith("///"):
            doc_lines.append(stripped[3:].strip())
        elif stripped and not stripped.startswith("//"):
            break
    if doc_lines:
        parts.append(" ".join(doc_lines)[:300])

    # Public items
    pub_items = re.findall(r"^pub\s+(?:async\s+)?(?:fn|struct|enum|trait|type)\s+(\w+)", source, re.MULTILINE)
    if pub_items:
        parts.append("pub: " + ", ".join(pub_items[:20]))

    tags = _tags_from_path(rel) + ["rust"]
    return _make_record(rel, " | ".join(parts), tags, file_path)


def extract_json_record(file_path: Path, base_dir: Path) -> dict:
    """Extract a memory record from a reference_data subsystem JSON file."""
    rel = str(file_path.relative_to(base_dir))
    try:
        data = json.loads(file_path.read_text())
    except Exception:
        return _make_record(rel, f"JSON subsystem: {rel}", ["reference"], file_path)

    parts = [f"Subsystem: {data.get('archive_name', file_path.stem)}"]
    if "package_name" in data:
        parts.append(f"package: {data['package_name']}")
    if "module_count" in data:
        parts.append(f"{data['module_count']} modules")
    sample = data.get("sample_files", [])
    if sample:
        parts.append("samples: " + ", ".join(Path(s).name for s in sample[:5]))

    return _make_record(rel, " | ".join(parts), ["reference", "subsystem"], file_path)


# ── helpers ──────────────────────────────────────────────────────────────────

def _tags_from_path(rel: str) -> list[str]:
    parts = Path(rel).parts
    tags = []
    for p in parts[:-1]:  # skip filename
        if p not in ("src", "crates", "rust", ".", ".."):
            tags.append(p)
    stem = Path(rel).stem
    if stem not in tags:
        tags.append(stem)
    return tags[:6]


def _make_record(file_path: str, text: str, tags: list[str], source_path: Path | None = None) -> dict:
    # Use file mtime as event time so re-ingests don't stamp everything "today".
    ts = datetime.now(timezone.utc).isoformat()
    if source_path is not None:
        try:
            mtime = source_path.stat().st_mtime
            ts = datetime.fromtimestamp(mtime, tz=timezone.utc).isoformat()
        except OSError:
            pass
    return {
        "file_path": file_path,
        "text": text,
        "metadata": {
            "type": "solution",
            "project": "claw-code",
            "tags": ",".join(tags),
            "source": "claw_code",
            "file_path": file_path,
            "importance": "0.8",
            "timestamp": ts,
        }
    }
