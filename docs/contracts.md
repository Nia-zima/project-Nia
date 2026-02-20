# State-Transition Contracts（状態遷移契約）

> 単純化して守るフェーズ — 10 個の不変条件テスト

## 概要

LangGraph グラフの状態遷移で守られるべき不変条件を 10 契約として定義し、
`tests/test_state_contracts.py` で自動検証する。

テスト実行:
```bash
python -m pytest tests/test_state_contracts.py -v
```

---

## 契約一覧

| # | 契約名 | 不変条件 | テストクラス |
|---|--------|----------|-------------|
| 1 | WAIT 透過 | `draft=="WAIT"` + depth空 → `final_text="WAIT"`, `hold_required=False`, `review_token=None` | `TestContract1_WaitPassthrough` |
| 2 | Hold 開始 | Hold トリガー → `final_text="WAIT"`, `review_token` 設定, `pending_actions` に say≥1 | `TestContract2_HoldStart` |
| 3 | Hold 取消 | 新入力 → 旧 Hold キャンセル、旧トークンで commit 不可 | `TestContract3_HoldCancel` |
| 4 | トークン一致必須 | approve/reject は token 一致時のみ有効、不一致 = 空 dict | `TestContract4_TokenMatch` |
| 5 | Commit 原子性 | approve → テキスト確定 + state クリア、reject → WAIT + rejected_actions 記録 | `TestContract5_CommitAtomicity` |
| 6 | final_result 一意 | 1 ストリームで final_result は最大 1 回 | `TestContract6_FinalResultUniqueness` |
| 7 | SSE ペイロード互換 | hold_request / hold_cancelled / final_result の必須キーが揃う | `TestContract7_SSEPayloadCompat` |
| 8 | Depth 優先順位 | dissonance≥0.65 → depth1 強制（最高優先）、depth2 → depth1+dissonance_on | `TestContract8_DepthPriority` |
| 9 | ターン初期化 | 毎ターン draft / depth1_text / depth2_text = "" にリセット | `TestContract9_TurnInit` |
| 10 | 記憶書き込み境界 | WAIT/Hold 時は S5 が記憶を保存しない | `TestContract10_MemoryWriteBoundary` |

---

## ソースファイル対応

| 契約 | 主要ソース |
|------|-----------|
| 1 | `backend/core/agent_graph/nodes/merge.py` L174-240 |
| 2 | `backend/core/agent_graph/review_window.py` `set_review_token()` |
| 3 | `backend/core/agent_graph/review_window.py` `cancel_review_on_new_input()` |
| 4 | `backend/core/agent_graph/review_window.py` `apply_review_decision()` |
| 5 | `backend/core/agent_graph/review_window.py` `apply_review_decision()` |
| 6 | `backend/core/agent_stream.py` L159 `final_result_emitted` flag |
| 7 | `backend/core/agent_graph/review_window.py` `build_hold_request_event()`, `build_hold_cancelled_event()` |
| 8 | `backend/core/agent_graph/nodes/routing.py` `_resolve_depth_decision()` |
| 9 | `backend/core/agent_stream.py` L183-190 inputs dict |
| 10 | `backend/core/agent_graph/nodes/actions.py` `s5_commit()` L202-208 |

---

## 定数

| 定数 | 値 | 定義場所 |
|------|----|----------|
| `D_LOW` | 0.30 | `review_window.py` |
| `D_MAX` | 0.95 | `review_window.py` |
| `K_HOLD` | 0.03 | `review_window.py` |
| `K_REJECT` | 0.07 | `review_window.py` |
| `MAX_PENDING` | 10 | `review_window.py` |

---

## SSE イベントスキーマ

### hold_request
```json
{
  "type": "event",
  "name": "hold_request",
  "payload": {
    "review_token": "<hex>",
    "hold_kind": "speech_preview",
    "preview_text": "<発話プレビュー>",
    "reason_codes": ["risk_long_reply", ...],
    "pending_actions": [{"kind": "say", "text": "...", "risk": "med"}]
  }
}
```

### hold_cancelled
```json
{
  "type": "event",
  "name": "hold_cancelled",
  "payload": {
    "review_token": "<hex>",
    "reason": "new_user_input"
  }
}
```

### final_result
```json
{
  "type": "event",
  "name": "final_result",
  "payload": {
    "final_text": "<確定テキスト>",
    "merge_mode": "B",
    "is_wait": false
  }
}
```

---

## Depth 優先順位チェーン

`_resolve_depth_decision()` のオーバーライド適用順（昇順、後勝ち）:

1. **Confidence ベース** — `DepthAction` から `need_depth1` / `dissonance_on` を決定
2. **User request** — `reason_codes` に `"user_request"` → `need_depth1=True`
3. **Depth2** — `need_depth2=True` → `need_depth1=True`, `dissonance_on=True`
4. **High dissonance** — `dissonance >= 0.65` → `need_depth1=True`, `dissonance_on=True` **(最高優先)**
