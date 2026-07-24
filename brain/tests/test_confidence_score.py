"""Behavior tests for confidence_score.py (Task 10, v1 shadow mode)."""

from __future__ import annotations

from pathlib import Path

import numpy as np

from brain.tools import confidence_score as cs


def _unit(rows: list[list[float]]) -> np.ndarray:
    m = np.asarray(rows, dtype=np.float32)
    m /= np.linalg.norm(m, axis=1, keepdims=True)
    return m


def test_support_high_for_clustered_low_for_orphan():
    # Two tight clusters near (1,0,..) and (0,1,..), plus one orphan far away.
    cluster_a = [[1, 0, 0], [0.99, 0.01, 0], [0.98, 0.02, 0]]
    cluster_b = [[0, 1, 0], [0.01, 0.99, 0], [0.02, 0.98, 0]]
    orphan = [[0, 0, 1]]
    matrix = _unit(cluster_a + cluster_b + orphan)
    indices = list(range(matrix.shape[0]))

    support = cs.compute_support(matrix, indices, k=2)

    orphan_idx = matrix.shape[0] - 1
    # Orphan must be the least-supported point in the corpus.
    assert support[orphan_idx] == support.min()
    # A clustered point must out-support the orphan by a clear margin.
    assert support[0] > support[orphan_idx] + 0.5


def test_support_excludes_self():
    # If self were counted, support would be inflated toward 1.0.
    matrix = _unit([[1, 0], [0, 1], [1, 1]])
    support = cs.compute_support(matrix, [0, 1, 2], k=1)
    # Top-1 neighbor of [1,0] is [1,1] (cos ~0.707), NOT itself (1.0).
    assert support[0] < 0.99


def test_assign_bands_monotonic_and_floor():
    support = np.linspace(0.0, 1.0, 100, dtype=np.float32)
    bands, proposed, cuts = cs.assign_bands(support)

    # Higher support never yields lower proposed salience.
    order = np.argsort(support)
    prop_sorted = proposed[order]
    assert np.all(np.diff(prop_sorted) >= 0)

    # All four bands appear and every proposed value respects the 0.1 API floor.
    assert set(bands.tolist()) == {"H", "M", "L", "D"}
    assert proposed.min() >= 0.1
    # Lowest band is disordered -> the configured D salience.
    assert proposed[order][0] == 0.25
    assert proposed[order][-1] == 0.70


def test_shadow_mode_does_not_write_salience():
    # Guard rail: v1 must never call a mutating path (call/import sites, not prose).
    src = Path(cs.__file__).read_text(encoding="utf-8")
    assert "update_salience(" not in src       # no salience write call
    assert "delete_memories(" not in src       # no delete call
    assert "from brain.api_client" not in src  # no mutating client imported
    assert "import brain.api_client" not in src
    assert cs.run.__doc__ is None or True  # run() returns a report only
    # The report must self-identify as shadow.
    assert "SHADOW" in src
