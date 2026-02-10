# Memory Legacy Deprecation Plan

This document defines the removal order for legacy memory fallbacks after Phase2 cutover.

## Current Rule

- `LEGACY_MEMORY_READ_ONLY=1` is the default operating mode.
- `LEGACY_MEMORY_TABLES_ENABLED=0` is the default schema mode.
- In this mode, legacy SQL write paths are blocked or redirected to `memory_events`.
- Legacy read fallbacks are skipped in critical API/read paths.

## Memory Role Policy

- Source of Truth (SoT): `memory_events`
- Derived retrieval index: `memory_index`
- Derived similarity index: `VectorStore`

### UI/Stats policy

- `memory_graph` keeps using `VectorStore`.
  - Reason: graph edges are embedding/cosine-based and belong to similarity index responsibilities.
  - `memory_events` is not required to store embeddings.
- `memory_timeline` can be migrated to `memory_events` when needed (low priority).
  - Reason: timeline is timestamp/text grouping and does not require embeddings.
  - Current behavior may remain as-is if there is no operational issue.

### Decision Rule

- If a feature requires embedding similarity, use `VectorStore`.
- If a feature requires chronological/event correctness, use `memory_events` (optionally via `memory_index`).
- Keep `VectorStore` as a derived index synchronized from event data, not as a source of truth.

## Remaining Deprecated Fallbacks (instrumented)

Status note (current): API/controller fallback reads and service-level fallback reads were removed.
There are no active legacy fallback code paths in memory retrieval.
`/api/stats/summary` memory counters are now sourced from `memory_events`.

## Removal Sequence

1. **Observe logs for 7 days**
2. **Drop API/controller fallback reads** (done)
3. **Drop service-level SQL fallback reads** (done)
4. **Remove legacy table writes still used only for maintenance scripts** (in progress)
   - `sync_vector_from_sql.py` migrated to `memory_events` source.
   - `backfill_origin_message_id.py` migrated to backfill `memory_events.turn_id`.
   - `debug_check_db.py` now includes `memory_events` inspection.
   - `migrate_episodic_to_memory_events.py` kept as one-time legacy migration helper only.
5. **Archive and remove legacy tables (`episodic_captures`, `long_term_memories`, old `events` memory usage)**
   - Added helper script: `backend/scripts/archive_drop_legacy_memory_tables.py`
   - Default is dry-run.
   - Execute mode requires explicit token:
     - `python -m backend.scripts.archive_drop_legacy_memory_tables --execute --confirm DROP_LEGACY_MEMORY_TABLES`

## Exit Criteria

- No `DEPRECATED legacy fallback used` logs in production logs during the observation window.
- Core tests pass with `LEGACY_MEMORY_READ_ONLY=1`.
- Migration/backfill scripts have completed and been verified.
