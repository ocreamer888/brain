"""Locks retrieval_eval_kfold.salience_weights() to the documented production
formula (brain.rs:437, `salience_w = (1.0 + 0.3*(sal-0.5)).clamp(0.85,1.15)`).

This is a third independent copy of that formula (brain.rs is the source of
truth; brain/tools/corroboration.py's trust_w() deliberately reuses the same
shape for a different metric, not this same quantity). Python and Rust can't
share a literal constant, so nothing stops this copy from silently drifting
if brain.rs's formula is retuned. This test can't prevent that, but it makes
an *accidental* edit to the Python copy fail loudly, and documents the exact
values a *deliberate* brain.rs retune needs to mirror here too.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from brain.tools.retrieval_eval_kfold import (
    SALIENCE_BASE,
    SALIENCE_BETA,
    SALIENCE_CLAMP,
    salience_weights,
)


def test_constants_match_brain_rs_437():
    assert SALIENCE_BASE == 1.0
    assert SALIENCE_BETA == 0.3
    assert SALIENCE_CLAMP == (0.85, 1.15)


@pytest.mark.parametrize(
    "salience,expected",
    [
        (0.5, 1.0),   # neutral
        (1.0, 1.15),  # max boost, at the clamp
        (0.0, 0.85),  # max suppression, at the clamp
        (0.75, 1.075),  # unclamped midpoint: 1.0 + 0.3*(0.75-0.5)
    ],
)
def test_salience_weights_matches_documented_production_formula(salience, expected):
    result = salience_weights([{"salience": salience}])
    assert result[0] == pytest.approx(expected, abs=1e-6)


def test_salience_weights_never_exceeds_clamp_bounds():
    extreme = salience_weights([{"salience": -5.0}, {"salience": 5.0}])
    assert extreme[0] == pytest.approx(SALIENCE_CLAMP[0])
    assert extreme[1] == pytest.approx(SALIENCE_CLAMP[1])


def test_salience_weights_is_elementwise_over_a_batch():
    metas = [{"salience": 0.5}, {"salience": 1.0}, {"salience": 0.0}]
    result = salience_weights(metas)
    assert isinstance(result, np.ndarray)
    assert len(result) == 3
    assert result[0] == pytest.approx(1.0)
    assert result[1] == pytest.approx(1.15)
    assert result[2] == pytest.approx(0.85)
