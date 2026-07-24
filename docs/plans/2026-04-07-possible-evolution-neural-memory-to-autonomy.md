# Possible Evolution Paths: Neural Memory -> Adaptive Intelligence

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Define a realistic, non-definitive set of possible paths from the current neural retrieval brain toward (a) online-learning capability and (b) bounded autonomous behavior.

**Architecture:** Keep the existing Rust brain memory core stable while adding optional capability layers (feedback signals, trainable reranking/adapters, planner/executor, governance). Treat each layer as reversible and independently measurable. Do not assume one fixed route.

**Tech Stack:** Rust (`brain/rust`), Python training/evaluation scripts, ONNX inference artifacts, CI workflows, SQLite/vector index, optional policy/eval services.

---

## Constraints and Framing (Read First)

- This is a **possible way**, not the definitive path.
- Favor reversible steps with measurable outcomes.
- Keep operational brain reliability first; experimental components run behind flags.
- No "AGI" claims: target capability milestones with explicit bounds.

---

## Path A (Possible): Toward Online Self-Training Neural Behavior

### Phase A1: Feedback Signal Layer (No weight updates yet)

**Intent:** Create reliable supervision signals from real usage before training anything.

**Tasks:**
- Add a normalized feedback event schema (`accepted`, `rejected`, `edited`, `time_to_success`, `rollback`).
- Persist feedback to a dedicated table/file separate from core memories.
- Add a daily/weekly export job for training datasets.
- Add quality checks for label noise and sparse signals.

**Exit Criteria:**
- Stable event ingestion for 2+ weeks.
- Data quality report with false-signal estimates.

**Decision Gate:**
- If feedback is noisy or sparse, improve signal design before any model training.

---

### Phase A2: Trainable Reranker (Safer than full embedding retraining)

**Intent:** Improve retrieval relevance with low-risk learnable component.

**Tasks:**
- Introduce reranker stage after vector retrieval (top-K -> reranked top-N).
- Train reranker offline using collected feedback.
- Add offline evaluation suite (NDCG/MRR/Recall@K, regression set).
- Deploy reranker behind feature flag (`BRAIN_RERANKER=on/off`).

**Exit Criteria:**
- Statistically significant relevance gain on holdout set.
- No latency/cost regression beyond agreed budget.

**Decision Gate:**
- If reranker gains are weak, refine features/data before moving on.

---

### Phase A3: Adapter-Based Incremental Learning (Optional)

**Intent:** Add limited parameter updates safely (LoRA/adapters), not full model retraining.

**Tasks:**
- Create adapter training pipeline in Python.
- Version adapters and export inference-ready artifacts.
- Add canary rollout + rollback in CI/CD.
- Add forgetting/drift checks (historical benchmark suite).

**Exit Criteria:**
- New adapter version beats baseline and passes regression/safety checks.
- Rollback tested and proven.

**Decision Gate:**
- If drift/forgetting risk is high, stay with reranker-only approach.

---

## Path B (Possible): Toward Bounded Autonomy (Not AGI)

### Phase B1: Planner + Executor with Human Approval

**Intent:** Move from reactive retrieval to structured task execution.

**Tasks:**
- Add explicit plan object (goal, constraints, subtasks, verification).
- Implement executor that runs steps with tool permission boundaries.
- Add mandatory verification hooks before completion claims.
- Require human approval for high-impact actions.

**Exit Criteria:**
- End-to-end completion quality improves on benchmark tasks.
- No increase in unsafe tool actions.

**Decision Gate:**
- If verification fails frequently, improve planner quality before more autonomy.

---

### Phase B2: Policy and Governance Layer

**Intent:** Ensure bounded behavior as autonomy increases.

**Tasks:**
- Define policy tiers (read-only, workspace-write, network, external side effects).
- Add hard guardrails + deny lists + approval workflows.
- Add full audit trails for decisions/actions.
- Implement incident replay and postmortem tooling.

**Exit Criteria:**
- All high-impact actions are traceable and policy-compliant.
- Security and operations review sign-off.

**Decision Gate:**
- If governance overhead is too high, narrow autonomy scope by domain.

---

### Phase B3: Domain-Bounded Autonomy Pilots

**Intent:** Validate autonomy in constrained contexts first.

**Tasks:**
- Choose one bounded domain (e.g., codebase maintenance workflows).
- Define strict success/failure metrics and stop conditions.
- Run staged rollout (internal -> small pilot -> broader use).
- Compare against human-in-loop baseline.

**Exit Criteria:**
- Sustained quality and safety above baseline over multiple cycles.

**Decision Gate:**
- If outcomes degrade, revert scope and reinforce human-in-loop controls.

---

## Cross-Cutting Requirements (Apply to Every Phase)

- **Evaluation First:** no promotion without fresh metrics.
- **Version Everything:** prompts, models, adapters, policies, datasets.
- **Rollback Always:** every deployment has a tested rollback path.
- **Observe Continuously:** latency, correctness, cost, safety incidents.
- **Prefer Simplicity:** avoid architecture expansion without measured value.

---

## Suggested Milestone Timeline (Flexible)

- **M1-M2:** A1 complete (feedback quality foundation)
- **M3-M4:** A2 reranker pilot
- **M5-M6:** B1 planner/executor with approval gates
- **M7+:** A3 adapters (optional), B2 governance hardening, B3 bounded autonomy pilots

This timeline is illustrative only; reorder or pause phases based on gate outcomes.

---

## Explicit Non-Goals (For Clarity)

- Not claiming biological neural equivalence.
- Not claiming autonomous AGI.
- Not replacing human oversight for high-risk actions.

---

## Implementation Checklist Starter

- [ ] Define feedback schema and storage.
- [ ] Add retrieval evaluation harness and baseline report.
- [ ] Prototype reranker behind feature flag.
- [ ] Introduce plan object + verification step contract.
- [ ] Add policy tier enforcement and audit logs.
- [ ] Run one domain-bounded pilot with measured outcomes.

---

## How to Use This Plan

- Treat each phase as optional until its gate passes.
- Re-prioritize by measured impact, not by ambition.
- Keep the operational brain stable while experimentation happens in isolated lanes.
<!-- brain-linker -->
## Related
- [[brain-graph/conversation/User i want to verify what kind of strong features would thi]]
- [[brain-graph/conversation/User]]
- [[brain-graph/pattern/Edited Usersmacm1airDocumentsAIbrainrustsrcbrain.rs ( memori]]
- [[brain-graph/project_context/This README introduces an open-source, clean-room reimplemen]]
- [[brain-graph/conversation/User this brain must preserve research and general learning.]]
<!-- /brain-linker -->
