"""Experiment 1: how well does each 'same subject' tier detect REAL layers?

Ground truth: rows whose superseded_by points at another existing memory (old -> new).
Baseline: random pairs from the same project + type (mostly NOT the same subject),
so each tier's hit rate on real pairs can be compared to its false-link rate.
Read-only on a snapshot copy of brain.db.
"""
import json, random, re, sqlite3, sys
from collections import Counter
import numpy as np

DB = "/tmp/brain-exp/brain.db"
random.seed(42)
conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)

def emb(blob):
    v = np.frombuffer(blob, dtype="<f4")
    n = np.linalg.norm(v)
    return v / n if n else v

rows = {}
for r in conn.execute("""select id,type,project,content,file_path,timestamp,event_time,
                         superseded_by,embedding from memories"""):
    rows[r[0]] = dict(type=r[1], project=r[2], content=r[3] or "", file_path=r[4],
                      ts=r[5], et=r[6], sup=r[7], emb=r[8])

def y(m):  # layer order: event_time, fallback timestamp (same as recency_w)
    return m["et"] or m["ts"]

# entity document frequency + per-memory entity names
df = Counter()
ents = {}
for mid, name, eid in conn.execute("""select g.src_memory_id, e.name, e.id
                                      from edges g join entities e on e.id=g.dst_entity_id"""):
    ents.setdefault(mid, set()).add((eid, name))
    df[eid] += 1

pairs = [(o, m["sup"]) for o, m in rows.items()
         if m["sup"] and m["sup"] in rows]
print("real pairs:", len(pairs))

# ---- baseline: random same-project+type pairs among non-superseded rows
by_pt = {}
for mid, m in rows.items():
    if not m["sup"]:
        by_pt.setdefault((m["project"], m["type"]), []).append(mid)
base = []
for o, n in pairs:  # match the type/project mix of the real pairs
    pool = by_pt.get((rows[n]["project"], rows[n]["type"]), [])
    if len(pool) >= 2:
        a, b = random.sample(pool, 2)
        base.append((a, b))
print("baseline pairs:", len(base))

def cos(a, b):
    ea, eb = rows[a]["emb"], rows[b]["emb"]
    if ea is None or eb is None:
        return None
    return float(np.dot(emb(ea), emb(eb)))

def shares_specific_entity(old, new, dmax):
    """Does OLD's text mention a specific entity linked to NEW? (old rows have no edges)"""
    text = rows[old]["content"].lower()
    for eid, name in ents.get(new, ()):
        if 2 <= df[eid] <= dmax and len(name) >= 3:
            if re.search(r"(?<![\w])" + re.escape(name.lower()) + r"(?![\w])", text):
                return True
    return False

def profile(label, ps):
    out = {"n": len(ps)}
    sims = [s for s in (cos(a, b) for a, b in ps) if s is not None]
    out["sim_pctiles"] = {p: round(float(np.percentile(sims, p)), 3) for p in (5, 25, 50, 75, 95)}
    for t in (0.70, 0.75, 0.80, 0.85, 0.90, 0.95):
        out[f"sim>={t}"] = round(sum(s >= t for s in sims) / len(sims), 3)
    out["same_project"] = round(sum(rows[a]["project"] == rows[b]["project"] for a, b in ps) / len(ps), 3)
    out["same_file_path"] = sum(1 for a, b in ps if rows[a]["file_path"] and rows[a]["file_path"] == rows[b]["file_path"])
    has_ent = [(a, b) for a, b in ps if ents.get(b)]
    out["second_has_entities"] = len(has_ent)
    for dmax in (5, 20, 50, 200, 10**9):
        k = sum(shares_specific_entity(a, b, dmax) for a, b in has_ent)
        out[f"entity_df<={dmax if dmax < 10**9 else 'inf'}"] = round(k / max(1, len(has_ent)), 3)
    return out

res = {"real": profile("real", pairs), "baseline": profile("baseline", base)}

# ---- time order on real pairs: is the replacement actually newer?
order = Counter()
for o, n in pairs:
    yo, yn = y(rows[o]), y(rows[n])
    order["newer" if yn > yo else "same" if yn == yo else "OLDER"] += 1
    order["old_has_event_time"] += bool(rows[o]["et"])
    order["new_has_event_time"] += bool(rows[n]["et"])
res["time_order"] = dict(order)
res["type_mix"] = dict(Counter(rows[o]["type"] for o, _ in pairs))
json.dump(res, open("/tmp/brain-exp/exp1.json", "w"), indent=2)
print(json.dumps(res, indent=2))
