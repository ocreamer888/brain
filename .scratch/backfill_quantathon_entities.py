import sys
from pathlib import Path

sys.path.insert(0, ".")
sys.path.insert(0, "brain")

from brain.tools.backfill_entities import run

QUANTATHON_DB = Path("/Users/abundancia888/.brain/instances/quantathon-lifehub/brain.db")
CHECKPOINT = Path("brain/bootstrap/checkpoint_entity_backfill_quantathon_lifehub.json")

result = run(
    db_path=QUANTATHON_DB,
    checkpoint_path=CHECKPOINT,
    checkpoint_every=10,
)
print("RESULT:", result)
