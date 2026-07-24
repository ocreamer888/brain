#!/usr/bin/env python3
"""Root-cause diagnostic for why noise detection fails. Read-only."""
from __future__ import annotations
import sys, time
from pathlib import Path
import numpy as np

_R = Path(__file__).resolve().parents[2]
if str(_R) not in sys.path:
    sys.path.insert(0, str(_R))
from brain.tools.noise_detect import fragility_score
from brain.tools.retrieval_eval_kfold import load_corpus

DB = _R / "brain" / "rust" / "brain.db"
SIGMA, K, TRIALS, SEED = 0.05, 10, 5, 42

metas, M = load_corpus(DB)
N = len(metas)
print(f"corpus: {N} memories", file=sys.stderr)

rng = np.random.default_rng(SEED)
frag = np.empty(N, dtype=np.float32)
t0 = time.time()
for i in range(N):
    frag[i] = fragility_score(i, M, SIGMA, K, TRIALS, rng)
print(f"fragility computed in {time.time()-t0:.0f}s", file=sys.stderr)

# neighbor density: mean cosine to top-K neighbors (excl self)
def topk_mean_sim(i, k=K):
    s = M @ M[i]; s[i] = -9
    top = np.argpartition(s, -k)[-k:]
    return float(s[top].mean()), top

print("\n=== A) WHAT are the top-fragility memories? (junk vs legit) ===")
order = np.argsort(-frag)
for i in order[:12]:
    dens, top = topk_mean_sim(i)
    nn = top[np.argmax(M[top] @ M[i])]
    print(f"[frag={frag[i]:.3f} dens={dens:.2f}] ({metas[i]['type']}/{metas[i]['project']}) {metas[i]['title'][:55]}")
    print(f"    nearest: {metas[nn]['title'][:60]!r} (cos={float(M[nn]@M[i]):.3f})")

print("\n=== C) Does fragility separate by density? (corr) ===")
dens_all = np.empty(N, dtype=np.float32)
for i in range(N):
    s = M @ M[i]; s[i] = -9
    dens_all[i] = np.partition(s, -K)[-K:].mean()
corr = float(np.corrcoef(frag, dens_all)[0, 1])
print(f"  corr(fragility, neighbor_density) = {corr:.3f}")
print("  (strong NEGATIVE => fragility just measures 'how isolated', not 'junk')")
# bucket density
for lo, hi in [(0.9, 1.01), (0.8, 0.9), (0.7, 0.8), (0.6, 0.7), (0.0, 0.6)]:
    m = (dens_all >= lo) & (dens_all < hi)
    if m.sum():
        print(f"  density [{lo:.1f},{hi:.1f}): n={int(m.sum()):>5}  mean_frag={frag[m].mean():.3f}")

print("\n=== B) Did dedup kill the 0.95 signal? (inject an exact duplicate) ===")
victim = int(order[N//2])  # a median-fragility memory
print(f"  victim: ({metas[victim]['type']}) {metas[victim]['title'][:50]}  frag_now={frag[victim]:.3f}")
M2 = np.vstack([M, M[victim:victim+1]])  # add exact copy at end
fv = fragility_score(victim, M2, SIGMA, K, TRIALS, np.random.default_rng(SEED))
print(f"  frag WITH an exact duplicate present = {fv:.3f}")
print("  (if it jumps toward ~1.0 => 0.95 threshold only ever fired on exact dups,")
print("   which BVH/title dedup now remove first => noise-detect is redundant)")

print("\n=== D) sigma sweep (is the perturbation miscalibrated?) ===")
sample = order[::N//200][:200]
for sg in [0.01, 0.02, 0.05, 0.1]:
    r = np.random.default_rng(SEED)
    vals = [fragility_score(int(i), M, sg, K, TRIALS, r) for i in sample]
    print(f"  sigma={sg:<5} mean_frag={np.mean(vals):.3f}  max={np.max(vals):.3f}")
