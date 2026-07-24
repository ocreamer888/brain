# Quantum Computing Full Ingest Plan

## Safety Guarantees

**Checkpoint System**: The ingest script uses `checkpoint_quantum.json` to track which notebooks have been processed. This ensures:
- ✅ **No overwriting**: Already-saved memories are skipped on re-runs
- ✅ **Resumable**: If the process crashes, it picks up where it left off
- ✅ **No duplicates**: Each notebook processed exactly once

## Current State

```
Checkpoint file: /Users/macm1air/Documents/AI/brain/bootstrap/checkpoint_quantum.json
Status: Has 1 notebook processed (QB23_Q24_One_Qubit.ipynb from earlier test)
```

## Full Ingest Process

**What will happen:**
1. Script scans all 142 notebooks in `/Users/Shared/hackathon-workshop/notebooks/`
2. Checks checkpoint - skips already-processed notebooks (1 notebook)
3. Processes remaining 141 notebooks section-by-section
4. For each section:
   - Extracts markdown + code
   - Tags with curriculum level (bronze/cobalt/nickel)
   - Saves to brain with project="quantum-computing"
5. Updates checkpoint after each successful save
6. On completion, final stats show total ingested

**Runtime**: ~45-60 minutes due to API rate limiting (0.1s delay + exponential backoff)

**Memory impact**: ~500-1000 new quantum sections added to brain (18k → ~19k total)

## Commands

**Run full ingest (safe - won't overwrite):**
```bash
.venv/bin/python3 brain/bootstrap/11_ingest_quantum.py
```

**Reset and re-ingest everything:**
```bash
.venv/bin/python3 brain/bootstrap/11_ingest_quantum.py --reset
```
(Warning: This deletes checkpoint and re-ingests all 142 notebooks)

**Ingest single notebook (testing):**
```bash
.venv/bin/python3 brain/bootstrap/11_ingest_quantum.py --notebook /path/to/notebook.ipynb
```

## Verification

After ingest completes, verify with:
```bash
# Search for quantum memories
.venv/bin/python3 -c "
import sys; sys.path.insert(0, '/Users/macm1air/Documents/AI')
from brain.api_client import search_memories
results = search_memories(project='quantum-computing', query='quantum', n=5)
print(f'Found {len(results)} quantum memories')
"
```

## Rollback (if needed)

If something goes wrong:
1. The checkpoint tracks progress - no duplicate data
2. Bad memories can be deleted from brain web UI
3. Restart ingest and it will skip already-processed notebooks
