# Phase2 Implementation Checklist (Vertical Slice Minimal / Approve-Reject / Review Window)

This checklist captures the fixed plan, required state, constants, naming rules, and minimal behavior for Phase2.

## 0) Fixed Direction
- [ ] Use Plan (pending_actions) -> Hold -> Commit flow (not generation).
- [ ] `final_text` is the only source of truth for display/persistence.
- [ ] While on HOLD, `final_text` must be "WAIT".
- [ ] Hold reasons/candidates are sent via SSE events (avoid state bloat).
- [ ] Approval UI is only Approve / Reject (Edit is deferred).

## 1) State Additions (Lightweight)
- [ ] `pending_actions: list[dict] = []` (max 10)
- [ ] `hold_required: bool = False`
- [ ] `hold_kind: str | None = None` (initially "speech_preview" only)
- [ ] `review_token: str | None = None`
- [ ] `reason_codes: list[str] = []` (max 10)
- [ ] `suppressed_actions: list[dict] = []` (max 5)
- [ ] `rejected_actions: list[dict] = []` (or shadow_logs, max 10)
- [ ] `final_text: str = ""` (only source of final output)

## 2) Constants (Initial Values)
- [ ] `D_LOW = 0.30`
- [ ] `D_MAX = 0.95`
- [ ] `K_HOLD = 0.03`
- [ ] `K_REJECT = 0.07` (2-3x K_HOLD)
- [ ] `MAX_PENDING = 10`
- [ ] `MAX_SUPPRESSED = 5`
- [ ] `MAX_REJECTED = 10`

## 3) reason_codes Naming Rules (Fixed)
Format: `<domain>_<rule>` (snake_case, lower-case, 1 code = 1 reason).
Rule name must map 1:1 to the code string (DSPy teacher data requirement).

- risk:
  - [ ] `risk_long_text`
  - [ ] `risk_dissonance_on`
  - [ ] `risk_high_dissonance`
- keyword:
  - [ ] `keyword_memory`
  - [ ] `keyword_policy`
  - [ ] `keyword_public`
  - [ ] `keyword_identity`
  - [ ] `keyword_decision`
- safety:
  - [ ] `safety_blocked`
- system:
  - [ ] `system_review_window`
  - [ ] `system_hold_cancelled`
  - [ ] `system_wait_passthrough`
  - [ ] `system_review_token_mismatch`
  - [ ] `system_hold_cancelled_new_input`
- action:
  - [ ] `action_say_held`
  - [ ] `action_rejected`

## 4) MED Keyword Rules (Minimal Set)
memory / policy (MED):
- [ ] ["覚えて","記録","保存","メモ","忘れないで"] -> `keyword_memory`
- [ ] ["設定","ルール","方針","今後は","これからは"] -> `keyword_policy`
- [ ] ["名前","呼び方"] -> `keyword_identity`

public / broadcast (HIGH-leaning):
- [ ] ["配信","公開","視聴者","SNS","投稿","拡散"] -> `keyword_public`

decision (MED):
- [ ] ["決めて","判断して","どっち","結論","正しい","間違い","最適","おすすめ","ランキング"] -> `keyword_decision`

## 5) Decision Logic (Priority Fixed)
### 5.1 Exception: say_candidate == "WAIT"
- [ ] Do not hold (`hold_required=False`)
- [ ] `final_text="WAIT"`
- [ ] `reason_codes += ["system_wait_passthrough"]`

### 5.2 HIGH (Forced Hold or Safety)
- [ ] If `safety_route != "safe"`:
  - `hold_required=True` (or return safety_text)
  - `reason_codes += ["safety_blocked"]`
- [ ] If public keyword + sensitive:
  - `reason_codes += ["risk_public_context"]`

### 5.3 MED (ASK = Review Window)
Any of the following triggers MED:
- [ ] `dissonance_on == True` -> `risk_dissonance_on`
- [ ] `dissonance >= D_LOW` -> `risk_high_dissonance`
- [ ] `len(user_text) >= 120` -> `risk_long_text`
- [ ] `len(say_candidate) >= 200` -> `risk_long_reply`
- [ ] keyword hit -> `keyword_*`
- [ ] `memory_candidates` count >= 1 -> `risk_memory_candidate`

### 5.4 LOW (AUTO)
- [ ] If none of the above, AUTO (no hold).

## 6) HoldPlanner (Plan Generation)
LOW:
- [ ] `final_text = say_candidate`
- [ ] `pending_actions = []`
- [ ] `hold_required = False`

MED/HIGH (start with say only):
- [ ] `pending_actions = [{"kind":"say","text": say_candidate, "risk": risk_level}]`
- [ ] `hold_required=True`
- [ ] `hold_kind="speech_preview"`
- [ ] `review_token = new_token()`
- [ ] `final_text="WAIT"`
- [ ] `reason_codes` fixed and attached
- [ ] Suppress heat:
  - `dissonance = min(dissonance + K_HOLD, D_MAX)`
- [ ] `suppressed_actions += {"kind":"say","text": say_candidate,"token":review_token,"reasons":reason_codes}` (cap)

## 7) SSE Event (UI)
When `hold_required=True`, emit immediately:
- [ ] `hold_request` event with minimal payload:
```json
{
  "review_token": "...",
  "hold_kind": "speech_preview",
  "preview_text": "...",
  "reason_codes": ["risk_long_text","keyword_memory"],
  "pending_actions": [{"kind":"say","text":"...","risk":"med"}]
}
```

## 8) Review Window (Exclusive Control)
### 8.1 API
- [ ] `POST /api/review/approve` (token required)
- [ ] `POST /api/review/reject` (token required)

### 8.2 Token Match (Critical)
- [ ] If received token != `state.review_token`, ignore (no commit)
- [ ] `reason_codes += ["system_review_token_mismatch"]` (log only)

### 8.3 New Input While Waiting
- [ ] Cancel old hold (no commit)
- [ ] Emit `hold_cancelled` event
- [ ] Move `pending_actions` to shadow_logs / `rejected_actions` (cap)
- [ ] `reason_codes += ["system_hold_cancelled_new_input"]`

## 9) Commit Node
Approve:
- [ ] Execute `pending_actions` (say only for now)
- [ ] `final_text = say.text`
- [ ] `review_token=None`, `pending_actions=[]`, `hold_required=False`
- [ ] Emit `commit_log` event

Reject:
- [ ] Do not execute
- [ ] `dissonance = min(dissonance + K_REJECT, D_MAX)`
- [ ] Save to `rejected_actions` (cap)
- [ ] `final_text="WAIT"`
- [ ] Emit `commit_log` event

## 10) commit_log (One Line, No Story)
Fixed format:
- [ ] `[COMMIT] say:<0/1> rejected:<0/1> D:<before->after> hold:<auto|ask|block> reasons:<codes...>`

Example:
- [ ] `[COMMIT] say:0 rejected:1 D:0.12->0.19 hold:ask reasons:risk_long_text,keyword_memory`

## 11) Minimal Scope to Run First (Vertical Slice)
- [ ] MemoryCandidates can be empty.
- [ ] `pending_actions` only needs "say".
- [ ] Review Window must include token match + cancel.
- [ ] Enforce WAIT + `reason_codes` outputs (for DSPy).
