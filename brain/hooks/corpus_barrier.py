"""Cubic barrier method for self-regulating corpus pressure (PPF Contact pattern).

As corpus grows past N_TARGET, the save threshold rises automatically.
At N_MAX, threshold reaches 1.0 — effectively a hard cap.
"""
from __future__ import annotations

N_TARGET = 18_000
N_MAX = 25_000
BASE_THRESHOLD = 0.3
K = 0.7


def barrier_force(n: int) -> float:
    if n <= N_TARGET:
        return 0.0
    ratio = min((n - N_TARGET) / (N_MAX - N_TARGET), 1.0)
    return K * ratio ** 3


def save_threshold(n: int) -> float:
    return BASE_THRESHOLD + barrier_force(n)


def should_save(confidence: float, n: int | None = None) -> bool:
    if n is None:
        try:
            from brain.api_client import get_stats
            n = get_stats().get("total_memories", 0)
        except Exception:
            n = 0
    return confidence >= save_threshold(n)
