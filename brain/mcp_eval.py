#!/usr/bin/env python3
"""Deprecated path. Live scorer is brain.tools.mcp_eval (V-30).

The old copy lacked the dangling-gold skip, so a direct import scored missing
ids as guaranteed misses. Re-export the fixed functions so that path cannot
diverge again.
"""
from brain.tools.mcp_eval import load_gold, offline_rrf_p1, run_mcp_eval

__all__ = ["load_gold", "offline_rrf_p1", "run_mcp_eval"]
