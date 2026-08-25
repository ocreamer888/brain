---
name: brain-forge-canary
description: 100-row canary sample before any bulk Brain job. Use before backfills, retags, quarantines, or irreversible DB mutations. Hard rule — no bulk without a canary artifact path on the certificate.
---

# Brain Forge Canary

**Hard rule:** no bulk / irreversible job without a canary artifact path on the Masterpiece Certificate.

> Four minutes of canary would have prevented 23,470 edges of damage (V-07).

## Input

- Bulk job description (what will change)
- Sample query (SQL or tool args) that mirrors production selection
- Optional limit (default 100)

## Procedure

1. Run the helper (read-only on `brain.db`):

```bash
.venv/bin/python brain/harness/canary_sample.py \
  --label JOB_LABEL \
  --limit 100 \
  --out-dir brain/eval/runs/canary-JOB_LABEL
```

Or pass `--sql` for a custom SELECT (must be read-only).

2. **Inspect** `sample.jsonl` + `summary.md` yourself — do not skip eyeballing.
3. Put the canary directory path on the certificate.
4. Only then run the bulk job.

## Output

```
brain/eval/runs/canary-<label>/
  sample.jsonl    # one JSON object per row
  summary.md      # counts, columns, eyeball checklist
  meta.json       # query, limit, timestamp
```

## Hard limits

- Helper opens DB **read-only** (`file:...?mode=ro`)
- Never run bulk from this skill
- Owner must eyeball the sample before approving scale-up

## Related

- Verification handoff canary rule: `docs/superpowers/specs/2026-07-29-verification-queue-handoff.md`
- Certificate template: `docs/superpowers/specs/brain-forge/templates/masterpiece-certificate.md`
