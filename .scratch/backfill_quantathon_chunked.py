import sys
import time
from pathlib import Path

sys.path.insert(0, ".")
sys.path.insert(0, "brain")

import requests

from brain.tools.backfill_entities import run, select_edgeless_durable

QUANTATHON_DB = Path("/Users/abundancia888/.brain/instances/quantathon-lifehub/brain.db")
CHECKPOINT = Path("brain/bootstrap/checkpoint_entity_backfill_quantathon_lifehub.json")
API = "http://127.0.0.1:8787"
HEADERS = {"x-api-key": "local-dev-key", "content-type": "application/json"}
CHUNK = 20


def ensure_active():
    for attempt in range(3):
        r = requests.get(f"{API}/stats", headers=HEADERS, timeout=5).json()
        if r["active_instance"]["id"] == "quantathon-lifehub":
            return True
        print(f"  [guard] active instance drifted to {r['active_instance']['id']!r}, re-switching...")
        requests.post(f"{API}/v1/instances/quantathon-lifehub/switch", headers=HEADERS, timeout=10)
        time.sleep(0.5)
    raise RuntimeError("could not keep quantathon-lifehub active after 3 attempts")


total_linked = 0
round_num = 0
while True:
    remaining = select_edgeless_durable(QUANTATHON_DB)
    if not remaining:
        print("done — no edgeless durable memories remain")
        break
    round_num += 1
    ensure_active()
    print(f"round {round_num}: {len(remaining)} remaining, processing next {min(CHUNK, len(remaining))}")
    # Fresh checkpoint per round -- the frozen work_set from a --limit run
    # would otherwise keep resuming the SAME batch instead of advancing,
    # since the underlying edgeless set shrinks after each successful round.
    CHECKPOINT.unlink(missing_ok=True)
    result = run(
        db_path=QUANTATHON_DB,
        checkpoint_path=CHECKPOINT,
        checkpoint_every=5,
        limit=CHUNK,
    )
    total_linked += result["linked_total"]
    print(f"  round {round_num} linked={result['linked_total']} (cumulative={total_linked})")
    ensure_active()

print("FINISHED")
