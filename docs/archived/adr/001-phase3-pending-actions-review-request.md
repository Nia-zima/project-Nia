# ADR 001: Phase3 v0 Pending Actions and Review Request Linkage

Status: Accepted (Phase3 v0)

## Purpose
Clarify how **memory_add delayed execution (pending_actions)** links to SSE/UI review requests (hold_request) in a way that is safe for future action expansion (tool_call / move / etc.).

## Scope
- Action: `memory_add` only (Phase3 v0)
- Layers: DB / Service / API / SSE / UI / Tests / Logs
- Excludes: Phase4 body / Phase6 learning (future expansion hooks only)

## Terms
- **pending_action**: Record awaiting approval (DB: `pending_actions`)
- **hold_request**: SSE event notifying UI to open the review window
- **review_token**: Temporary token binding UI actions to a review session
- **kind**: UI-facing action type (v0 fixed to `"memory_add"`)

## Data Model (Phase3 v0)
`pending_actions`:
- `action_type`: `"memory_add"` (v0 fixed)
- `status`: `PENDING | HELD | APPROVED | APPLIED | REJECTED | CANCELLED | ERROR`
- `payload_json`: completed episodic_captures record (single row)
- `created_at`: fixed at enqueue time (not overwritten on approve)
- `schema_version`: `"v0"` in payload
- `dedupe_key`: `sha256(thread_id:message_id:memory_add)` (UNIQUE)

## Flow
### 1) Enqueue (Generation)
Nia builds a complete episodic payload and calls `enqueue_memory_add()`:
- Insert into `pending_actions` with `status=PENDING`
- Dedupe by `dedupe_key` (idempotent)
- `commit_log`: `MEMORY_ADD_ENQUEUED`

### 2) Review Request (SSE)
`hold_request` notifies UI that an approval window must open:
- payload must include:
  - `review_token`
  - `preview.kind = "memory_add"` (v0 required)
  - `preview_text` (existing summary text)
- Reason: SSE can arrive before UI fetches the pending list. `kind` lets UI choose a safe template immediately.

### 3) UI Actions (approve / reject / hold)
UI calls API with `review_token`:
- `POST /actions/{id}/approve`
- `POST /actions/{id}/reject`
- `POST /actions/{id}/hold`

After action, UI re-fetches pending list.

## Invariants
### A. Irreversible Status Transitions
Terminal states do not revert to `PENDING/HELD`.
All transitions are guarded by **conditional UPDATE**:
- hold/reject/approve only succeed when status ∈ {PENDING, HELD}
- APPLIED/CANCELLED/ERROR only from APPROVED (two-step approve)

### B. Physical Deduping
Same `thread_id + message_id` results in a single pending action.
Retries (SSE replay, UI reload) cannot create duplicates.

### C. Payload Freshness
`payload_json` is complete; **no re-inference at approve time**.
`episodic_captures.created_at` preserves enqueue time.
Approval time is tracked in `commit_log`.

### D. Token Mismatch
`review_token` mismatch is **no-op**:
- No DB mutation of status/reason/updated_at
- API returns `applied=false` (no conflict side effects)

## Recovery
### APPROVED Orphans
If a process fails after APPROVED but before APPLIED:
- `scripts/recover_pending_actions.py` scans APPROVED
  - APPLIED on success
  - CANCELLED(ALREADY_EXISTS) on text_hash conflict
  - ERROR on failure

## Kind and Compatibility
- v0: only `"memory_add"`
- UI branches by `kind`; if missing/unknown, show safe fallback (raw_json).
- Server should always emit `kind` (SSE + pending API), but UI must be tolerant.

## Observability
### commit_log
- `line`: short grep-friendly string  
  Example: `[COMMIT] applied:1 action:memory_add event:MEMORY_ADD_APPLIED memory:+1 D:0.01->0.00 reasons:...`
- `meta` (machine-readable):
  - `action_kind="memory_add"`
  - `memory_delta` (+1 only for APPLIED, 0 otherwise)
  - `pending_action_id`, `thread_id`, `message_id`, `text_hash`
  - `schema_version`, `kind`
  - `dissonance_before/after` (v0.1 uses pending_count-derived approximation; v1 will use true dissonance)

### UI Meta
- `pending_count` = count(status ∈ {PENDING, HELD})
- `dissonance_delta` = min(0.15, pending_count * 0.01)
- UI shows both in Review Window header.

## Tests (Minimum)
- Dedupe: same message enqueues once
- Approve double-exec: INSERT once, second approve conflicts
- text_hash collision: CANCELLED(ALREADY_EXISTS) + memory_delta=0
- Irreversibility: terminal states cannot transition
- SSE: hold_request includes `preview.kind="memory_add"`
- UI: unknown kind does not break rendering
