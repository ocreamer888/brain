#!/usr/bin/env python3
"""
Ingest HAPI FHIR documentation into brain with project="fhir".
Ingests all files from /Users/abundancia888/Documents/AI/FHIR/

Run: .venv/bin/python3 brain/bootstrap/17_ingest_fhir.py
Reset: .venv/bin/python3 brain/bootstrap/17_ingest_fhir.py --reset
"""
import json
import sys
import time
import argparse
from pathlib import Path

script_dir = Path(__file__).resolve().parent
project_root = script_dir.parent.parent
sys.path.insert(0, str(project_root))

from brain.api_client import save_memory, get_stats

FHIR_DIR = Path("/Users/abundancia888/Documents/AI/FHIR")
CHECKPOINT = script_dir / "checkpoint_fhir.json"
PROJECT = "fhir"
DELAY = 0.15  # seconds between saves (rate limiting)


# Map file paths to brain memory metadata
FILE_METADATA = {
    "00_MODULE_MAP.md": {
        "memory_type": "fact",
        "tags": ["fhir", "hapi", "modules", "architecture", "java"],
        "title": "HAPI FHIR Module Map — all 63 modules",
    },
    "01_OFFICIAL_DOCS/01_getting_started.md": {
        "memory_type": "pattern",
        "tags": ["fhir", "hapi", "getting-started", "FhirContext", "java"],
        "title": "HAPI FHIR Getting Started — FhirContext, Maven",
    },
    "01_OFFICIAL_DOCS/02_parsers.md": {
        "memory_type": "pattern",
        "tags": ["fhir", "hapi", "parsing", "json", "xml", "serialization"],
        "title": "HAPI FHIR Parsers — JSON/XML parse and encode",
    },
    "01_OFFICIAL_DOCS/03_rest_client.md": {
        "memory_type": "pattern",
        "tags": ["fhir", "hapi", "client", "IGenericClient", "rest", "java"],
        "title": "HAPI FHIR REST Client — IGenericClient CRUD operations",
    },
    "01_OFFICIAL_DOCS/04_plain_server.md": {
        "memory_type": "pattern",
        "tags": ["fhir", "hapi", "server", "plain-server", "RestfulServer", "java"],
        "title": "HAPI FHIR Plain Server — RestfulServer, resource providers",
    },
    "01_OFFICIAL_DOCS/05_jpa_server.md": {
        "memory_type": "pattern",
        "tags": ["fhir", "hapi", "jpa", "server", "spring", "hibernate", "database"],
        "title": "HAPI FHIR JPA Server — Spring Boot JPA server setup",
    },
    "01_OFFICIAL_DOCS/06_interceptors_security.md": {
        "memory_type": "pattern",
        "tags": ["fhir", "hapi", "interceptors", "security", "authorization", "CORS"],
        "title": "HAPI FHIR Interceptors & Security — AuthorizationInterceptor patterns",
    },
    "01_OFFICIAL_DOCS/07_validation.md": {
        "memory_type": "pattern",
        "tags": ["fhir", "hapi", "validation", "profiles", "StructureDefinition"],
        "title": "HAPI FHIR Validation — FhirValidator, NPM packages, profiles",
    },
    "01_OFFICIAL_DOCS/08_mdm.md": {
        "memory_type": "pattern",
        "tags": ["fhir", "hapi", "mdm", "deduplication", "golden-resource", "matching"],
        "title": "HAPI FHIR MDM — Master Data Management patient deduplication",
    },
    "01_OFFICIAL_DOCS/09_batch2_partitioning.md": {
        "memory_type": "pattern",
        "tags": ["fhir", "hapi", "batch", "bulk-export", "partitioning", "multitenancy"],
        "title": "HAPI FHIR Batch2 & Partitioning — bulk jobs and multitenancy",
    },
    "01_OFFICIAL_DOCS/10_custom_structures.md": {
        "memory_type": "pattern",
        "tags": ["fhir", "hapi", "custom", "extensions", "profiles", "StructureDefinition"],
        "title": "HAPI FHIR Custom Structures — extending resources with extensions",
    },
    "02_MODULE_DOCS/01_hapi-fhir-base.md": {
        "memory_type": "fact",
        "tags": ["fhir", "hapi", "base", "FhirContext", "IParser", "interceptors", "java"],
        "title": "hapi-fhir-base module — FhirContext, IParser, interceptor framework",
    },
    "02_MODULE_DOCS/02_hapi-fhir-server.md": {
        "memory_type": "fact",
        "tags": ["fhir", "hapi", "server", "RestfulServer", "IResourceProvider", "java"],
        "title": "hapi-fhir-server module — RestfulServer, providers, IBundleProvider",
    },
    "02_MODULE_DOCS/03_hapi-fhir-storage.md": {
        "memory_type": "fact",
        "tags": ["fhir", "hapi", "storage", "IFhirResourceDao", "SearchParameterMap", "java"],
        "title": "hapi-fhir-storage module — IFhirResourceDao, DAO interface layer",
    },
    "02_MODULE_DOCS/04_hapi-fhir-jpaserver-base.md": {
        "memory_type": "fact",
        "tags": ["fhir", "hapi", "jpa", "dao", "hibernate", "spring", "search", "java"],
        "title": "hapi-fhir-jpaserver-base module — JPA DAO implementation, search",
    },
    "02_MODULE_DOCS/05_subscriptions_mdm_batch.md": {
        "memory_type": "fact",
        "tags": ["fhir", "hapi", "subscriptions", "mdm", "batch2", "notification", "java"],
        "title": "hapi-fhir subscriptions, MDM engine, Batch2 module docs",
    },
    "03_ARCHITECTURE/01_overall_architecture.md": {
        "memory_type": "project_context",
        "tags": ["fhir", "hapi", "architecture", "layers", "request-lifecycle"],
        "title": "HAPI FHIR Overall Architecture — layers, request lifecycle, modules",
    },
    "03_ARCHITECTURE/02_database_schema.md": {
        "memory_type": "fact",
        "tags": ["fhir", "hapi", "database", "schema", "HFJ_RESOURCE", "sql", "hibernate"],
        "title": "HAPI FHIR Database Schema — HFJ_RESOURCE, HFJ_SPIDX_*, table descriptions",
    },
    "03_ARCHITECTURE/03_fhir_versions.md": {
        "memory_type": "fact",
        "tags": ["fhir", "hapi", "versions", "R4", "R5", "DSTU3", "DSTU2", "HL7"],
        "title": "HAPI FHIR Versions — R4, R5, DSTU3, DSTU2 differences and migration",
    },
    "03_ARCHITECTURE/04_security_model.md": {
        "memory_type": "pattern",
        "tags": ["fhir", "hapi", "security", "auth", "SMART", "JWT", "authorization"],
        "title": "HAPI FHIR Security Model — auth layers, SMART on FHIR patterns",
    },
    "04_IMPLEMENTATION_GUIDE.md": {
        "memory_type": "solution",
        "tags": ["fhir", "hapi", "implementation", "recipes", "spring-boot", "java"],
        "title": "HAPI FHIR Implementation Guide — practical recipes for our projects",
    },
    # Tutorials (from github.com/hapifhir/fhir-tutorial)
    "05_TUTORIALS/01_crud_operations.md": {
        "memory_type": "pattern",
        "tags": ["fhir", "crud", "rest", "read", "create", "update", "delete", "expunge", "tutorial"],
        "title": "FHIR CRUD Operations Tutorial — read, create, update, delete, expunge",
    },
    "05_TUTORIALS/02_fhirpath.md": {
        "memory_type": "pattern",
        "tags": ["fhir", "fhirpath", "xpath", "navigation", "query", "filter", "tutorial"],
        "title": "FHIRPath Tutorial — navigation, where(), select(), ofType(), aggregate()",
    },
    "05_TUTORIALS/03_profiling.md": {
        "memory_type": "pattern",
        "tags": ["fhir", "profiling", "StructureDefinition", "slicing", "extensions", "validation", "tutorial"],
        "title": "FHIR Profiling Tutorial — StructureDefinition, slicing, $validate, extensions",
    },
    "05_TUTORIALS/04_search_parameters.md": {
        "memory_type": "pattern",
        "tags": ["fhir", "search", "SearchParameter", "token", "date", "quantity", "modifiers", "prefixes", "tutorial"],
        "title": "FHIR Search Parameters Tutorial — types, modifiers, prefixes, custom params",
    },
    "05_TUTORIALS/05_search_chain_has_include.md": {
        "memory_type": "pattern",
        "tags": ["fhir", "search", "chain", "_has", "_include", "_revinclude", "references", "tutorial"],
        "title": "FHIR Search: chain, _has, _include, _revinclude — multi-resource queries",
    },
    "05_TUTORIALS/06_terminology.md": {
        "memory_type": "pattern",
        "tags": ["fhir", "terminology", "CodeSystem", "ValueSet", "LOINC", "SNOMED", "$expand", "$validate-code", "tutorial"],
        "title": "FHIR Terminology Tutorial — CodeSystem, ValueSet, $expand, $validate-code",
    },
    "05_TUTORIALS/07_transactions_bundles.md": {
        "memory_type": "pattern",
        "tags": ["fhir", "bundle", "transaction", "batch", "history", "OperationOutcome", "paging", "tutorial"],
        "title": "FHIR Transactions & Bundles Tutorial — batch vs transaction, paging, OperationOutcome",
    },
}

# Max chars per memory (split long files)
MAX_CHARS = 8000


def load_checkpoint() -> dict:
    if CHECKPOINT.exists():
        return json.loads(CHECKPOINT.read_text())
    return {"files_processed": [], "memories_saved": 0}


def save_checkpoint(state: dict) -> None:
    CHECKPOINT.write_text(json.dumps(state, indent=2))


def split_content(content: str, max_chars: int) -> list[str]:
    """Split long content at section boundaries."""
    if len(content) <= max_chars:
        return [content]

    chunks = []
    current = []
    current_len = 0

    for line in content.split("\n"):
        line_len = len(line) + 1
        if current_len + line_len > max_chars and current:
            # Split at section boundary (## heading)
            if line.startswith("## ") or line.startswith("# "):
                chunks.append("\n".join(current))
                current = [line]
                current_len = line_len
            else:
                current.append(line)
                current_len += line_len
        else:
            current.append(line)
            current_len += line_len

    if current:
        chunks.append("\n".join(current))

    return chunks


def ingest_file(rel_path: str, meta: dict, state: dict) -> int:
    """Ingest a single file. Returns number of memories saved."""
    full_path = FHIR_DIR / rel_path
    if not full_path.exists():
        print(f"  ⚠ File not found: {full_path}")
        return 0

    content = full_path.read_text(encoding="utf-8")
    chunks = split_content(content, MAX_CHARS)

    saved = 0
    for i, chunk in enumerate(chunks):
        title = meta["title"]
        if len(chunks) > 1:
            title = f"{title} (part {i + 1}/{len(chunks)})"

        try:
            save_memory(
                content=chunk,
                memory_type=meta["memory_type"],
                tags=meta["tags"],
                project=PROJECT,
                source="hapifhir_docs",
                file_path=str(full_path),
                title=title,
                auto_entities=False,  # bulk ingest: backfill_entities.py links these
            )
            saved += 1
            time.sleep(DELAY)
        except Exception as e:
            print(f"  ✗ Error saving chunk {i+1}: {e}")
            time.sleep(1.0)

    return saved


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--reset", action="store_true", help="Reset checkpoint and re-ingest all")
    args = parser.parse_args()

    if args.reset and CHECKPOINT.exists():
        CHECKPOINT.unlink()
        print("[RESET] Checkpoint deleted. Will re-ingest all files.")

    state = load_checkpoint()
    processed = set(state["files_processed"])

    print(f"\n[FHIR INGEST] Starting HAPI FHIR documentation ingestion")
    print(f"[FHIR INGEST] Project: {PROJECT}")
    print(f"[FHIR INGEST] Total files: {len(FILE_METADATA)}")
    print(f"[FHIR INGEST] Already processed: {len(processed)}")
    print(f"[FHIR INGEST] To process: {len(FILE_METADATA) - len(processed)}")

    # Verify brain is accessible
    try:
        stats = get_stats()
        print(f"[FHIR INGEST] Brain has {stats.get('total', '?')} memories")
    except Exception as e:
        print(f"[FHIR INGEST] ✗ Brain API not accessible: {e}")
        print("[FHIR INGEST] Make sure brain server is running: .venv/bin/python3 brain/core/server.py")
        sys.exit(1)

    total_saved = state["memories_saved"]
    new_saved = 0

    for rel_path, meta in FILE_METADATA.items():
        if rel_path in processed:
            print(f"  ✓ Skip (already done): {rel_path}")
            continue

        print(f"  → Ingesting: {rel_path}")
        n = ingest_file(rel_path, meta, state)

        if n > 0:
            processed.add(rel_path)
            state["files_processed"] = list(processed)
            state["memories_saved"] = total_saved + new_saved + n
            save_checkpoint(state)
            new_saved += n
            print(f"    ✓ Saved {n} memor{'y' if n == 1 else 'ies'}")
        else:
            print(f"    ✗ No memories saved for {rel_path}")

    print(f"\n[FHIR INGEST] Complete!")
    print(f"[FHIR INGEST] New memories saved this run: {new_saved}")
    print(f"[FHIR INGEST] Total memories saved: {total_saved + new_saved}")
    print(f"[FHIR INGEST] Files processed: {len(processed)}/{len(FILE_METADATA)}")

    # Final stats
    try:
        stats = get_stats()
        print(f"[FHIR INGEST] Brain now has {stats.get('total', '?')} total memories")
    except Exception:
        pass


if __name__ == "__main__":
    main()
