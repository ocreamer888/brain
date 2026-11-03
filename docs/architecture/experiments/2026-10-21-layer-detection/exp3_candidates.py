"""Experiment 3: uncensored candidate layers. Pairs of live memories in the same project that
share a SPECIFIC entity (2<=df<=20), ordered by ingest time, sampled across similarity bands,
for hand labelling: LAYER / RELATED / UNRELATED."""
import json, random, sqlite3
from collections import Counter, defaultdict
import numpy as np
random.seed(7)
conn = sqlite3.connect("file:/tmp/brain-exp/brain.db?mode=ro", uri=True)
live = {}
for mid, t, p, c, ts, e in conn.execute("""select id,type,project,content,timestamp,embedding from memories
        where superseded_by is null and embedding is not null"""):
    v = np.frombuffer(e, dtype="<f4"); live[mid] = (t, p, c, ts, v / np.linalg.norm(v))
by_ent = defaultdict(list); names = {}
for mid, eid, name in conn.execute("select g.src_memory_id, e.id, e.name from edges g join entities e on e.id=g.dst_entity_id"):
    by_ent[eid].append(mid); names[eid] = name
cands = {}
stats = Counter()
for eid, mids in by_ent.items():
    if not (2 <= len(mids) <= 20) or len(names[eid]) < 3:
        continue
    ms = [m for m in mids if m in live]
    for i in range(len(ms)):
        for j in range(i + 1, len(ms)):
            a, b = ms[i], ms[j]
            if live[a][1] != live[b][1]:
                continue
            old, new = (a, b) if live[a][3] < live[b][3] else (b, a)
            key = (old, new)
            if key in cands: continue
            sim = float(live[old][4] @ live[new][4])
            cands[key] = (sim, names[eid])
            stats["pairs"] += 1
            stats["same_type"] += live[old][0] == live[new][0]
bands = [(0.0, .5), (.5, .65), (.65, .78), (.78, .92), (.92, 1.01)]
dist = {f"{lo}-{hi}": sum(lo <= s < hi for s, _ in cands.values()) for lo, hi in bands}
print("candidate pairs (same project, shared specific entity):", stats["pairs"], "same type:", stats["same_type"])
print("by similarity band:", dist)
sample = []
for lo, hi in bands:
    pool = [k for k, (s, _) in cands.items() if lo <= s < hi]
    for old, new in random.sample(pool, min(14, len(pool))):
        s, ent = cands[(old, new)]
        sample.append(dict(band=f"{lo}-{hi}", sim=round(s, 3), entity=ent, project=live[old][1],
            old_type=live[old][0], new_type=live[new][0], old_ts=live[old][3][:16], new_ts=live[new][3][:16],
            old=live[old][2][:400], new=live[new][2][:400], old_id=old, new_id=new))
json.dump(sample, open("/tmp/brain-exp/exp3_sample.json", "w"), indent=1, ensure_ascii=False)
json.dump({"n_pairs": stats["pairs"], "same_type": stats["same_type"], "bands": dist}, open("/tmp/brain-exp/exp3_stats.json", "w"))
print("sample size:", len(sample))
