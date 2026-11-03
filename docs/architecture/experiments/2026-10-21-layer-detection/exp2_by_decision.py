"""Experiment 2: tier detection split by curator decision (UPDATE = real change, MERGE = near-dup)."""
import json, sqlite3, sys
sys.argv = ["x"]
exec(open("/tmp/brain-exp/exp1_pairs.py").read().split("res = {")[0])  # reuse loaders + profile()
dec = {}
for fid, d in conn.execute("select fact_id, decision from curation_events where decision in ('UPDATE','MERGE')"):
    dec.setdefault(fid, set()).add(d)
groups = {"UPDATE": [], "MERGE": [], "unknown": []}
for o, n in pairs:
    d = dec.get(n, set())
    groups["UPDATE" if "UPDATE" in d else "MERGE" if "MERGE" in d else "unknown"].append((o, n))
res = {k: profile(k, v) for k, v in groups.items() if v}
for k, v in groups.items():
    if v:
        res[k]["ingest_newer"] = round(sum(rows[n]["ts"] > rows[o]["ts"] for o, n in v) / len(v), 3)
json.dump(res, open("/tmp/brain-exp/exp2.json", "w"), indent=2)
print(json.dumps(res, indent=1))
