# Plan: cerebro Rust como sistema principal (production-ready)

> Objetivo estratégico: **Rust es la única fuente de verdad en producción** (SQLite + índice vectorial + `brain_api`). Python queda como **herramientas auxiliares** (MCP stdio, scripts de export/ETL, summarizers legacy, automatización), no como store primario de memorias en runtime.

Este plan complementa la documentación ya existente: `docs/PHASE4_API.md`, `docs/PHASE6_MIGRATION.md`, `docs/PHASE7.md`, `docs/architecture/system-diagrams.md`.

---

## 1. Definición de “production ready” (criterios de salida)

Se considera cumplido cuando **todas** estas condiciones son verdaderas en el entorno de producción:

1. **Un solo store activo** para memorias consultables por hooks/MCP/usuarios: Rust (`BRAIN_DB_PATH` + `BRAIN_INDEX_PATH`). No hay escrituras nuevas de memorias “de producto” hacia Chroma en rutas calientes.
2. **`BRAIN_BACKEND=api`** (o equivalente explícito) en todos los procesos que usan `brain/api_client.py` y el MCP: `session_start`, `post_tool_use`, `session_end` (reflexión), servidor MCP.
3. **`brain_api` supervisado**: arranque automático, reinicio ante fallo, logs rotados, variables de entorno documentadas y secretos fuera del repo.
4. **Ingest continuo y batch** alimentan **Rust** (HTTP `/save` y/o binarios Rust de ingest), con idempotencia y checkpoints; no dependen de Chroma para quedar persistidos.
5. **Migración y corte**: datos históricos en Chroma exportados (`export_to_jsonl`) e importados (`brain_migrate`); procedimiento de **congelación** de Chroma como archivo/backup, no como sistema en línea.
6. **Observabilidad mínima**: `/health` monitorizado; `/stats` estable; Phase 7 (feedback + export + digest) operando sobre la **misma** SQLite que usa Rust (`feedback_events` presente cuando aplica).
7. **Runbook de incidentes**: backup de DB + índice, cómo rehidratar desde JSONL, cómo desactivar auto-ingest sin romper sesiones.
8. **Pruebas de regresión** automatizadas (ya existentes + ampliaciones) pasando antes de cada release del stack Rust.
9. **SLO de frescura en tiempo real** definido y medido: memoria guardada en rutas calientes es consultable en Rust en `< 2s` p95 (o umbral acordado) tras `save`.
10. **No pérdida de eventos de memoria** en fallos transitorios: existe cola durable de reintentos (spool) para escrituras fallidas en hooks/MCP y proceso de replay.
11. **Política de ack y degradación** explícita: cuándo se considera persistida una memoria, comportamiento bajo backpressure/API caída y alertas por atraso de cola.

---

## 2. Estado actual vs objetivo (breve)

| Área | Hoy (transición) | Objetivo producción |
|------|------------------|---------------------|
| Runtime búsqueda/guardado | `BRAIN_BACKEND` puede apuntar a API (Rust) o a Python/Chroma | Solo API → Rust |
| Ingest Claude Code (`07`) | Escribe en **Chroma** vía `brain.core.db` | Escribe en **Rust** (API o binario) |
| Migración | JSONL + `brain_migrate` documentado (Phase 6) | Parte del pipeline estándar post-corte |
| MCP | Python stdio; llama a API o core según modo | Siempre API hacia Rust |
| Chroma | Aún puede ser destino de ingest Python | Solo legado / export / emergencia |

---

## 3. Fases de ejecución (orden recomendado)

### Fase P0 — Baseline operativo Rust (sin cambiar ingest todavía)

- Documentar y fijar **un conjunto de env vars** por entorno (dev/staging/prod): `BRAIN_DB_PATH`, `BRAIN_INDEX_PATH`, `BRAIN_API_URL`, `BRAIN_API_KEY`, `BRAIN_ONNX_PATH`, límites de rate, auth.
- **Supervisar `brain_api`** (launchd, systemd, Docker, etc.) con reinicio y logs.
- Checklist de seguridad: API no expuesta públicamente sin TLS/proxy; claves rotadas.
- **Criterio de salida**: API estable 7 días (o ventana acordada) con monitoreo de `/health`.

**Referencias:** `docs/PHASE4_API.md`

---

### Fase P1 — Forzar tráfico de aplicación a Rust

- Establecer **`BRAIN_BACKEND=api`** (y `BRAIN_API_URL` correcto) en:
  - entorno del usuario / CI / máquina donde corren hooks y MCP.
- Verificar que **no queda código de producto** que asuma Chroma para `search`/`save` en rutas de usuario final.
- **Criterio de salida**: todas las memorías creadas por hooks/MCP en este entorno aparecen solo en SQLite Rust (verificación por `/stats` y muestra de IDs).

**Referencias:** `docs/architecture/system-diagrams.md` (diagrama runtime §2)

---

### Fase P2 — Redirigir ingest Python → Rust (punto crítico)

Objetivo: **ningún ingest “nuevo”** persista solo en Chroma.

Opciones de implementación (elegir una o combinar):

- **A)** Tras export de sesión, llamar **`POST /save`** (o endpoint batch si se añade) desde un pequeño cliente HTTP reutilizando el mismo esquema de metadatos que ya consume Rust.
- **B)** Invocar un **binario Rust** existente o nuevo que lea el JSON de `sessions_export/` y haga upsert idempotente (alineado con `brain_migrate` / ingest de sesiones).
- **C)** Pipeline: seguir generando JSONL intermedio solo si es necesario para batch, pero el **sink final** sigue siendo Rust.

Trabajos concretos:

- Diseñar **contrato de metadatos** único (tipo, source, project, tags, session_id) entre export hook y Rust.
- Sustituir o complementar el `07_ingest_claude_code.py` “sink Chroma” por el sink Rust elegido.
- Mantener **`--file`** / checkpoint / idempotencia para no duplicar memorias.
- **Criterio de salida**: cerrar sesión de prueba → memoria visible en Rust; Chroma no incrementa (o deja de usarse en esa ruta).

**Referencias:** `brain/bootstrap/07_ingest_claude_code.py`, `brain/rust/src/bin/brain_migrate.rs`, ingest bins bajo `brain/rust/src/bin/`

---

### Fase P3 — Batch / backfill / otras fuentes (Perplexity, Cursor, Claw)

- Alinear **orquestador** (`backfill_orchestrator`) para que etapas de ingest pesadas terminen en **Rust** (directo o vía migrate programado), no en Chroma como estado estable.
- Donde solo exista pipeline Python hoy: plan de **migración por etapas** o implementación Rust acotada.
- **Criterio de salida**: un run de backfill documentado deja el sistema consultable solo desde Rust post-run.

**Referencias:** `docs/BACKFILL_AUTOMATION.md`, scripts `06_*`, `03_*`, `05_*`

---

### Fase P4 — Corte Chroma y archivo

- Export final controlado: `export_to_jsonl.py` → `brain_migrate`.
- Validación de conteos / búsqueda de muestra (`brain_query` o tests de paridad).
- **Desactivar** escrituras a Chroma en producción; documentar ruta de solo lectura o backup.
- **Criterio de salida**: inventario “Chroma = archivo”; runtime = Rust únicamente.

**Referencias:** `docs/PHASE6_MIGRATION.md`

---

### Fase P5 — Production hardening

- **Backups**: copia programada de `brain.db` + `brain_index.bin`; prueba de restore.
- **Logs y retención**: API, digest, export, ingest en background.
- **Alertas**: fallo de health, disco lleno, errores de migrate.
- **Versionado**: etiquetar releases del binario `brain_api` y procedimiento de rollback.
- Phase 7: feedback + digest + export sobre SQLite real en prod (`docs/PHASE7.md`).
- **SLO/SLI realtime**: latencia save→search (p50/p95/p99), tasa de errores `/save`, tamaño/edad de cola de reintentos.
- **Alertas de lag de ingest**: disparar por cola creciente, replay atascado o frescura fuera de umbral.
- **Drill de degradación**: simular caída de API y verificar enqueue/replay sin pérdida de eventos.

**Criterio de salida**: runbook de incidentes probado una vez (tabletop o drill corto).

---

### Fase P6 — Python residual (explícito)

Lista blanca de lo que **sí** debe quedar en Python en producción, por ejemplo:

- `brain/mcp/server.py` (stdio MCP → HTTP Rust).
- Scripts de mantenimiento, export, digest, utilidades de desarrollo.
- Cualquier extractor que aún no tenga paridad Rust, **siempre** con salida hacia Rust.

**Criterio de salida**: documento de 1 página “Python allowed list” enlazado desde `docs/BRAIN.md` o este plan.

**Implementado (batch doc):** `docs/PYTHON_ALLOWED_LIST.md` (enlazado desde `docs/BRAIN.md`).

---

## 4. Checklist ejecutable (archivo por archivo)

> Objetivo: convertir P2/P3/P5 en tareas implementables sin ambiguedad.

### BLOQUEADORES (go-live Rust-only)

- [x] **Ruta `07` sin Chroma**  
  - Archivos: `brain/bootstrap/07_ingest_claude_code.py`, `brain/bootstrap/claude_code_extractors.py`  
  - Cambio: reemplazar `upsert_memory` de Chroma por sink Rust (HTTP batch o binario Rust).  
  - Hecho cuando: correr `--file` no incrementa Chroma y sí incrementa Rust (`/stats`).
  - Estado: implementado en código; falta validación en entorno de producción.

- [x] **Escritura realtime durable en hooks**  
  - Archivos: `brain/hooks/post_tool_use.py`, `brain/api_client.py`, `brain/hooks/session_end.py`  
  - Cambio: estado de escritura `success|queued|failed`, enqueue durable en fallo API, replay posterior.  
  - Hecho cuando: con API caída no se pierden eventos y aparecen tras replay.
  - Estado: implementado en código; falta drill explícito API-down en entorno objetivo.

- [x] **Spool/replay implementado y observable**  
  - Archivos nuevos sugeridos: `brain/hooks/spool.py`, `brain/tools/replay_spool.py`  
  - Cambio: cola local durable (JSONL/SQLite), dedupe/idempotency key, límites de reintentos, DLQ/cuarentena.  
  - Hecho cuando: métricas de cola (size/oldest_age) visibles y alertables.
  - Estado: implementado en código (queue_size/oldest_age + replay CLI); falta integrar alertas del entorno.

- [x] **Backfill termina en Rust**  
  - Archivos: `brain/tools/backfill_orchestrator.py`, scripts `brain/bootstrap/03_ingest.py`, `05_ingest_claw.py`, `06_ingest_perplexity.py`  
  - Cambio: asegurar sink final Rust (directo o migrate programado), no Chroma steady-state.  
  - Hecho cuando: un run completo deja datos consultables en Rust sin dependencia de Chroma.
  - Estado: ingest y orquestador pasados a sink Rust directo (con modo legacy opcional de migrate); falta validación de run completo en prod.

- [x] **Corte Chroma en producción**  
  - Archivos/docs: `docs/PHASE6_MIGRATION.md`, configuración de entorno y jobs  
  - Cambio: desactivar writes a Chroma, dejar solo export/backup/lectura histórica.  
  - Hecho cuando: inventario y runbook indican “Chroma archivo”.
  - Estado: guardrail + verificación ejecutada (`verify_cutover.py`), evidencia en `docs/deploy/PRODUCTION_CHECK_EVIDENCE.md`.

### REQUERIDOS (confiabilidad y operación)

- [x] **SLO/SLI de frescura realtime**  
  - Archivos: `docs/deploy/README.md`, monitoreo/alertas del entorno  
  - Cambio: definir umbral (`save->search` p95), error budget y panel de métricas.
  - Estado: umbral/SLI + probe + export Prometheus + reglas de alertas ejemplo, con evidencia en `docs/deploy/PRODUCTION_CHECK_EVIDENCE.md`.

- [x] **Pruebas de frescura + resiliencia**  
  - Archivos de tests sugeridos: `brain/tests/test_realtime_save_search.py`, `brain/tests/test_spool_replay.py`  
  - Cambio: smoke de save→search inmediato + caso API down→queue→replay.
  - Estado: tests añadidos en repo; falta validación final contra entorno de producción.

- [x] **Runbook de incidentes validado**  
  - Archivos: `docs/deploy/README.md` o doc dedicado runbook  
  - Cambio: pasos para API caída, cola creciendo, restore DB/index, replay seguro.
  - Estado: drill ejecutado y evidencia adjunta en `docs/deploy/incident-drill-evidence.json` y `docs/deploy/PRODUCTION_CHECK_EVIDENCE.md`.

### NICE (después de go-live)

- [x] **Endpoint batch `/save`** en `brain_api` para ingest de alto volumen.
  - Estado: implementado `/save-batch` + `api_client.save_memory_batch()` + uso en `07_ingest_claude_code.py`.
- [x] **Compaction/pruning de spool** con política de retención.
  - Estado: `brain/tools/spool_maintenance.py` + función `prune()` en spool con edad máxima configurable.
- [x] **Dashboard de “memory freshness”** por fuente (`post_tool_use`, `session_end`, batch).
  - Estado: export de métricas por fuente (`brain_spool_queue_by_source`) y reglas base; falta visual final en herramienta de dashboard elegida.

Prioridad recomendada:

1. Endpoint batch `/save` (impacto directo en throughput de ingest).
2. Dashboard de freshness por fuente (visibilidad operativa continua).
3. Compaction/pruning de spool (higiene y costo de almacenamiento).

---

## 4.1 Tickets listos (NICE)

### Ticket NICE-1 — Endpoint batch `/save` en `brain_api`

**Objetivo**
- Reducir overhead HTTP en ingest masivo enviando lotes en una sola llamada.

**Alcance**
- Añadir `POST /save-batch` en API Rust.
- Request: lista de memorias con mismo esquema de `/save`.
- Response: conteos `accepted`, `failed` y errores por item.
- Idempotencia por `id` o `idempotency_key` (si aplica).

**Archivos objetivo**
- `brain/rust/src/bin/brain_api.rs`
- `brain/rust/src/brain.rs` o capa de servicio equivalente
- `brain/api_client.py` (cliente `save_memory_batch`)

**Criterio de salida**
- Ingest scripts pueden usar batch.
- Pruebas API cubren éxito parcial y errores por item.
- Throughput medido mejor que N llamadas `/save` individuales.

### Ticket NICE-2 — Dashboard de memory freshness por fuente

**Objetivo**
- Ver en un panel único la salud de captura en tiempo real por pipeline.

**Alcance**
- Panel con series:
  - `brain_status_ok`
  - `brain_spool_queue_size`
  - `brain_spool_oldest_age_seconds`
  - latencia p95 save->search (si ya disponible)
- Separar por fuente: `post_tool_use`, `session_end`, batch.

**Archivos objetivo**
- `docs/deploy/alerts-example.yaml` (base de reglas)
- `brain/tools/export_metrics_prom.py` (extensiones de métricas)
- docs operativas de despliegue/dashboard

**Criterio de salida**
- Dashboard accesible en entorno target.
- Alertas enlazadas al dashboard para triage rápido.

### Ticket NICE-3 — Compaction/pruning de spool

**Objetivo**
- Evitar crecimiento indefinido de spool/DLQ manteniendo trazabilidad útil.

**Alcance**
- Política de retención configurable (ej. días máximos).
- Tarea de limpieza segura para registros ya replayed / DLQ antiguos.
- Reporte de limpieza (cuántos registros removidos).

**Archivos objetivo**
- `brain/hooks/spool.py`
- `brain/tools/replay_spool.py` o nuevo `brain/tools/spool_maintenance.py`
- docs operativas (`docs/deploy/README.md`)

**Criterio de salida**
- Ejecución periódica sin romper replay.
- Métricas reflejan tamaño bajo control tras limpieza.

---

## 5. Riesgos y mitigación

| Riesgo | Mitigación |
|--------|------------|
| Doble escritura (Chroma + Rust) y divergencia | P1 + P2 secuenciales; congelar Chroma tras P4 |
| Ingest en background falla en silencio | Logs dedicados; alertas; reintentos idempotentes |
| Coste/latencia LLM en ingest | Mantener `--no-llm` por defecto en rutas calientes; summarization opcional |
| Pérdida de datos en migrate | Backup pre-migrate; dry-run en staging |

---

## 6. Verificación continua (comandos mínimos)

```bash
# Tests Python del repo
python3 -m pytest brain/tests -q

# Tests Rust
cargo test --manifest-path brain/rust/Cargo.toml -q

# API viva
curl -fsS http://127.0.0.1:8787/health
```

Ampliar con pruebas de paridad búsqueda/guardado cuando P2 esté cerrada.

Añadir smoke tests de frescura realtime:

```bash
# save -> search inmediato (mismo contenido/ID visible)
# validar p95 de save->search bajo umbral acordado
# simular caída API: evento queda en spool y aparece tras replay
```

---

## 7. Próximo paso inmediato

Acordar **opción P2 (A vs B vs C)** y abrir tareas implementables (issues) con criterios de salida por PR. Sin cerrar P2, el objetivo “Rust único” no se cumple aunque la API esté en producción.

---

## Changelog del documento

- 2026-04-08: plan inicial (roadmap production-ready Rust primario).
- 2026-04-08: P0/P6 — añadidos `docs/BRAIN_ENV_MATRIX.md`, `docs/deploy/*`, `docs/PYTHON_ALLOWED_LIST.md` y enlaces en `docs/BRAIN.md` / `docs/PHASE4_API.md`.
- 2026-04-08: criterios realtime añadidos (SLO frescura, spool durable, ack/backpressure, alertas de lag, smoke tests save→search).
- 2026-04-08: checklist ejecutable añadida (bloqueadores/requeridos/nice) con targets por archivo.
- 2026-04-08: añadidos guardrails/ops (`BRAIN_ENFORCE_API_ONLY`, probe de observabilidad, template de alertas, helper de incident drill).
- 2026-04-08: cierre de pendientes core con evidencia (cutover verificado, SLO/SLI instrumentado, drill validado).
- 2026-04-08: NICE implementados (save-batch, pruning de spool, métricas por fuente para dashboard).
- 2026-04-08: P0/P1 verificados en producción — `brain_api` release binary bajo launchd (`com.brain.api`), env vars en `~/.zshrc`, `backend_mode()=api` confirmado, hook write test delta +1 (1580→1581). Evidencia en `docs/deploy/PRODUCTION_CHECK_EVIDENCE.md §4`.
- 2026-04-08: Fase P4 ejecutada — Phase 6 data migration completada. 1538 memorias exportadas de ChromaDB a JSONL, 0 errores en import a Rust SQLite + vector index. SQLite final: 1614 memorias (1538 históricas + 76 de hooks en vivo). `brain_query` verificado post-migración. Chroma pasa a estado archivo.


<!-- brain-linker -->
## Related
- [[brain-graph/conversation/User]]
- [[brain-graph/pattern/Edited Usersmacm1airDocumentsAIbrainrustsrcbrain.rs ( memori]]
- [[brain-graph/solution/Edited Usersmacm1airDocumentsAIbrainrustsrcbrain.rs pub stru]]
- [[brain-graph/solution/Edited Usersmacm1airDocumentsAIbrainrustsrcbrain.rs Ok(Self ]]
- [[brain-graph/pattern/Edited Usersmacm1airDocumentsAIbrainrustsrcconfig.rs ( memor]]
<!-- /brain-linker -->
