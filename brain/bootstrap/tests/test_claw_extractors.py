"""Tests for claw-code-main extraction helpers."""
import ast
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from brain.bootstrap.claw_extractors import extract_python_record


def test_extract_python_record_basic(tmp_path):
    src = tmp_path / "example.py"
    src.write_text('''"""Module docstring."""

class Foo:
    """Foo class."""
    pass

def bar(x, y):
    """Bar function."""
    return x + y
''')
    result = extract_python_record(src, base_dir=tmp_path)
    assert result["file_path"] == "example.py"
    assert "Module docstring" in result["text"]
    assert "Foo" in result["text"]
    assert "bar" in result["text"]
    assert result["metadata"]["type"] == "solution"
    assert result["metadata"]["project"] == "claw-code"
    assert result["metadata"]["source"] == "claw_code"


def test_extract_python_record_no_docstring(tmp_path):
    src = tmp_path / "plain.py"
    src.write_text("x = 1\n")
    result = extract_python_record(src, base_dir=tmp_path)
    assert result["file_path"] == "plain.py"
    assert "plain.py" in result["text"]


from brain.bootstrap.claw_extractors import extract_rust_record, extract_json_record


def test_extract_rust_record_pub_items(tmp_path):
    src = tmp_path / "lib.rs"
    src.write_text('''/// Session management module.
/// Handles persisting conversations to disk.

pub struct Session {
    id: String,
}

pub fn save_session(s: &Session) -> Result<(), Error> {
    todo!()
}

pub enum SessionError {
    NotFound,
    IoError,
}
''')
    result = extract_rust_record(src, base_dir=tmp_path)
    assert "Session" in result["text"]
    assert "save_session" in result["text"]
    assert "SessionError" in result["text"]
    assert "Session management" in result["text"]
    assert result["metadata"]["source"] == "claw_code"


def test_extract_json_record_subsystem(tmp_path):
    f = tmp_path / "hooks.json"
    f.write_text('{"archive_name": "hooks", "package_name": "hooks", "module_count": 104, "sample_files": ["hooks/foo.ts"]}')
    result = extract_json_record(f, base_dir=tmp_path)
    assert "hooks" in result["text"]
    assert "104" in result["text"]
    assert result["metadata"]["type"] == "solution"
