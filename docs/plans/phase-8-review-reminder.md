# Phase 8 review (2-week feedback soak)

**Soak started:** 2026-04-07  
**Come back here:** **2026-04-21** (14 days later)

## When you reopen this

1. Check feedback volume: `GET /stats` → `feedback_events_total`, `feedback_last_event_ts`, or export:

   `python3 brain/tools/export_feedback.py --since-days 14 > feedback_review.jsonl`

2. **Go / no-go for Phase 8** (eval harness + reranker prototype, Path A2):
   - Enough events and usable labels? → start Phase 8 slice (baseline metrics + flag-gated reranker).
   - Sparse or noisy? → improve where/how feedback is collected before training.

## Links

- Phase 7 plan: `docs/plans/2026-04-07-phase-7-feedback-and-observability.md`
- Phase 7 how-to: `docs/PHASE7.md`
- Evolution Path A2: `docs/plans/2026-04-07-possible-evolution-neural-memory-to-autonomy.md`


<!-- brain-linker -->
## Related
- [[brain-graph/conversation/User]]
- [[brain-graph/conversation/Claude Code session AI Ended 2026-04-09T050638.779691+0000 C]]
- [[brain-graph/conversation/Claude Code session AI Ended 2026-04-09T045953.269990+0000 C]]
- [[brain-graph/pattern/Ran command python3 braintoolsingest_session_chunks.py --all]]
- [[brain-graph/pattern/Successfully committed `07_ingest_claude_code.py` to the rep]]
<!-- /brain-linker -->
