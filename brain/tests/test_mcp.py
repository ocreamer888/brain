import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
import pytest
import json
import chromadb
from unittest.mock import patch, MagicMock


def test_mcp_server_module_imports():
    """MCP server module must import without errors."""
    import brain.mcp.server
    assert hasattr(brain.mcp.server, 'mcp')


def test_search_brain_tool_exists():
    import brain.mcp.server as server
    tool_names = [t.name for t in server.mcp._tools.values()] if hasattr(server.mcp, '_tools') else []
    # FastMCP registers tools differently — just check the function exists
    assert hasattr(server, 'search_brain')


def test_save_memory_tool_exists():
    import brain.mcp.server as server
    assert hasattr(server, 'save_memory_tool')


def test_get_context_tool_exists():
    import brain.mcp.server as server
    assert hasattr(server, 'get_context_tool')


def test_reflect_tool_exists():
    import brain.mcp.server as server
    assert hasattr(server, 'reflect_tool')


def test_get_stats_tool_exists():
    import brain.mcp.server as server
    assert hasattr(server, 'get_stats_tool')


# --- Active learning behavior (Task 1) -------------------------------------

def _result(rid, dist, content="x"):
    return {
        "id": rid,
        "content": content,
        "distance": dist,
        "metadata": {"type": "fact", "project": "AI", "tags": "", "source": "test"},
    }


def test_search_brain_flags_uncertain_top2():
    """Near-equal top-2 distances must emit the active-learning feedback prompt."""
    import brain.mcp.server as server
    with patch.object(server, "backend_mode", return_value="api"), \
         patch.object(server, "api_template_search",
                      return_value=[_result("a", 0.50), _result("b", 0.52)]):
        out = server.search_brain(query="q")
    assert "Uncertain retrieval" in out
    assert "memory_id='a'" in out and "memory_id='b'" in out


def test_search_brain_no_flag_when_distances_far():
    """A clear winner (gap >= _UNCERTAINTY_GAP) must NOT emit the prompt."""
    import brain.mcp.server as server
    with patch.object(server, "backend_mode", return_value="api"), \
         patch.object(server, "api_template_search",
                      return_value=[_result("a", 0.50), _result("b", 0.80)]):
        out = server.search_brain(query="q")
    assert "Uncertain retrieval" not in out


def test_record_feedback_accepted_nudges_salience_up():
    """accepted feedback bumps salience +0.05 via update_salience."""
    import brain.mcp.server as server
    with patch.object(server, "backend_mode", return_value="api"), \
         patch.object(server, "api_record_feedback", return_value="fid-1"), \
         patch.object(server, "api_get_observations",
                      return_value=[{"metadata": {"salience": 0.5}}]), \
         patch.object(server, "api_update_salience", return_value=True) as upd:
        out = server.record_feedback(event_type="accepted", memory_id="m1")
    upd.assert_called_once_with("m1", 0.55)
    assert "0.50 → 0.55" in out


def test_search_brain_surfaces_trust_and_flags_low():
    """Each hit shows a Trust score; salience below _LOW_TRUST is flagged."""
    import brain.mcp.server as server
    hi = _result("a", 0.50); hi["metadata"]["salience"] = 0.9
    lo = _result("b", 0.80); lo["metadata"]["salience"] = 0.2
    with patch.object(server, "backend_mode", return_value="api"), \
         patch.object(server, "api_template_search", return_value=[hi, lo]):
        out = server.search_brain(query="q")
    assert "Trust: 0.90" in out
    assert "Trust: 0.20 ⚠ low-trust" in out


def test_search_brain_min_salience_filters_low_trust():
    """min_salience suppresses results below the threshold."""
    import brain.mcp.server as server
    hi = _result("a", 0.50); hi["metadata"]["salience"] = 0.9
    lo = _result("b", 0.80); lo["metadata"]["salience"] = 0.2
    with patch.object(server, "backend_mode", return_value="api"), \
         patch.object(server, "api_template_search", return_value=[hi, lo]):
        out = server.search_brain(query="q", min_salience=0.5)
    assert "memory_id" not in out  # only one result left → no uncertainty prompt
    assert "Trust: 0.90" in out
    assert "Trust: 0.20" not in out


def test_search_brain_min_salience_all_filtered():
    """When everything is below threshold, return a clear message."""
    import brain.mcp.server as server
    lo = _result("b", 0.80); lo["metadata"]["salience"] = 0.2
    with patch.object(server, "backend_mode", return_value="api"), \
         patch.object(server, "api_template_search", return_value=[lo]):
        out = server.search_brain(query="q", min_salience=0.5)
    assert "above trust threshold" in out


def test_record_feedback_rejected_nudges_salience_down():
    """rejected feedback drops salience -0.10 via update_salience."""
    import brain.mcp.server as server
    with patch.object(server, "backend_mode", return_value="api"), \
         patch.object(server, "api_record_feedback", return_value="fid-2"), \
         patch.object(server, "api_get_observations",
                      return_value=[{"metadata": {"salience": 0.5}}]), \
         patch.object(server, "api_update_salience", return_value=True) as upd:
        out = server.record_feedback(event_type="rejected", memory_id="m1")
    upd.assert_called_once_with("m1", 0.4)
    assert "0.50 → 0.40" in out
