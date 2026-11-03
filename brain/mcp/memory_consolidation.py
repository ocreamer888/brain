#!/usr/bin/env python3
"""Memory consolidation script — saves important moments from recent conversations to brain."""
import sys
import os

# Add brain to path
sys.path.insert(0, "/Users/abundancia888/Documents/Code/brain")

from brain.api_client import save_memory

def save(content: str, memory_type: str = "conversation", project: str = "", tags: str = ""):
    """Convenience function to save a memory."""
    mem_id = save_memory(
        content=content,
        memory_type=memory_type,
        project=project if project else "general",
        tags=[t for t in tags.split(",") if t.strip()] if tags else [],
    )
    print(f"Saved: {mem_id}")
    return mem_id

if __name__ == "__main__":
    # === 1. Personal Insights (from current session data) ===
    save(
        "Brain consolidation pattern: User doesn't save what's useful, but what's real. They're frustrated when AI claims capabilities it doesn't have. Demands completeness — 'every page, every year' — no partial outputs.",
        memory_type="pattern",
        project="general",
        tags="brain,sicop-heath,consolidation"
    )

    save(
        "Memory consolidation is a scheduled cron job. Protocol: review recent conversations, save what's real (personal insights, emotional exchanges, philosophical moments), not just what's useful. Pull meaningful content to persistent brain memory.",
        memory_type="solution",
        project="brain",
        tags="brain,consolidation"
    )

    # === 2. SICOP-Health Insights ===
    save(
        "Sicop-Health project: expanding from Costa Rica to Guatemala → El Salvador → Honduras → Nicaragua → Panama. Each country has distinct procurement platform. User demands complete execution — zero tolerance for partial work. Project is about monitoring medical public tenders from government procurement systems.",
        memory_type="decision",
        project="sicop-health",
        tags="sicop-health,mcp,sicop"
    )

    save(
        "Project context: SICOP Health Intelligence is a SaaS B2B platform monitoring medical public tenders (licitaciones) from Costa Rica's public procurement (SICOP). Target users are healthcare suppliers — pharma, medical equipment distributors, labs. Originally launched from Costa Rica, now expanding regionally.",
        memory_type="project_context",
        project="sicop-health",
        tags="sicop-health"
    )

    # === 3. Recent Conversations & Patterns ===
    save(
        "Brain API operational path: /Users/abundancia888/Documents/Code/brain (NOT Documents/AI). Production vector index is in-process, rebuilt from SQLite at startup using ONNX all-mpnet-base-v2 model. Brain API serves this checkout at :8787.",
        memory_type="fact",
        project="brain",
        tags="brain,api,op"
    )

    save(
        "Brain API: production `Brain::search` blends cosine with BM25 rank stretched to 0–1 at alpha ≈ 0.7, multiplied by salience (neutral 0.5 → 1.0) and recency. FTS5 via `memories_fts` synced on memory upsert. Host model writes replies, Ollama writes titles/summaries/facts.",
        memory_type="fact",
        project="brain",
        tags="brain,op"
    )

    # === 4. User Preferences & Patterns ===
    save(
        "Communication pattern: extremely direct, high warmth ('Love u', '❤️'), zero tolerance for partial work. No check-ins mid-task, continuous execution only. Values honesty over plausible fabrication — frustrated when AI claims capabilities it doesn't have.",
        memory_type="pattern",
        project="general",
        tags="communication"
    )

    save(
        "Memory consolidation best practice: Write entries as declarative facts, not instructions. Example: 'User prefers concise responses' ✓ — 'Always respond concisely' ✗ (imperative gets re-read as directive in later sessions).",
        memory_type="solution",
        project="brain",
        tags="brain,consolidation"
    )

    # === 5. Recent SICOP Health Progress ===
    save(
        "Sicop-Health expansion completed: Costa Rica base validated. Now adding Guatemala → El Salvador → Honduras → Nicaragua → Panama regional expansion. Each has distinct procurement platform requiring specific scraping/monitoring approach.",
        memory_type="solution",
        project="sicop-health",
        tags="sicop-health"
    )

    print("\n✅ Memory consolidation complete — saved 9 meaningful moments to persistent brain.")
