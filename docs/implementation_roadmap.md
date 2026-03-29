# 実装ロードマップ — Somatic / Pip / Room

> **Date**: 2026-03-03 (updated)
> **基盤設計**: `nia_design_philosophy.md`, `somatic_self_awareness_design.md`, `pip_and_room_design.md`
> **前提**: Memory v2 (Phase A〜G), Retrieval M.1〜M.3, Metacognition N.0〜N.5 稼働中

---

## 全体依存関係

```
S.1a (体感コア) ✅  →  S.1b (フィードバック) ✅  →  S.1.5 (適応閾値) ✅
                                                          ↓
P.1 (Pip状態マシン) ✅ → P.2 (部屋) ✅ → P.4 (Bond深化) ✅ → S.2 (体感+Pip統合)
                          ↓                              ↓
                      P.3 (お絵かき)                   P.5 (Context Builder) ✅
                                                       ↓
Unity: U.1〜U.6（バックエンドと並行）              P.7 (配信)
```

---

## 実装順序

| # | Phase | 状態 | 依存 | 備考 |
|---|-------|------|------|------|
| 1 | **S.1a** 体感コア | ✅ 完了 | M.1 | 2026-02-27 実装 |
| 2 | **S.1b** フィードバック + 矛盾検出 | ✅ 完了 | S.1a | 2026-02-27 実装 |
| 3 | **S.1.5** 適応的閾値 | ✅ 完了 | S.1b + 20サンプル | 2026-03-03 実装 |
| 4 | **P.1** Pip バックエンド MVP | ✅ 完了 | なし | 2026-02-27 実装 |
| 5 | **P.2** 部屋バックエンド MVP | ✅ 完了 | P.1 | 2026-02-27 実装 |
| 6 | **P.4** Bond 深化 | ✅ 完了 | P.1 稼働後 | 2026-03-03 実装 |
| 7 | **P.3** お絵かき統合 | 未着手 | P.2 | |
| 8 | **P.5** Context Builder 統合 | ✅ 完了 | P.2 | 2026-03-03 実装 |
| 9 | **S.2** 体感 + Pip/Room 統合 | 未着手 | S.1.5 + P.4 | |
| 10 | **P.7** 配信 | 未着手 | P.5 + U.6 | |

---

## Phase S.1a: 体感コア ✅

**完了: 2026-02-27** — retrieval 結果をニアが「体感」として受け取る。LLM呼び出し0回、<5ms。

### 作成ファイル
- `backend/services/memory/somatic_translator.py` — InternalMetrics → SomaticSense 変換
- `backend/services/memory/somatic_calibration.py` — 閾値管理（S.1a では読み込みのみ）
- `tests/test_somatic_translator.py` — 18テスト
- `tests/test_context_builder_somatic.py` — 8テスト

### 修正ファイル
- `backend/services/memory/retrieval.py` — `retrieve_with_scores()` 追加
- `backend/services/memory/context_builder.py` — `_build_self_sense()` + `=== 今の感覚 ===` セクション
- `backend/core/agent_graph/nodes/routing.py` — `_collect_somatic_senses()` + depth_selector 統合
- `backend/core/agent_graph/state.py` — `somatic_senses` フィールド
- `backend/core/config.py` — `SOMATIC_ENABLED=True`, `SOMATIC_FEEDBACK_ENABLED=False`, `SOMATIC_ADAPTIVE_ENABLED=False`

### データフロー
```
depth_selector → retrieve_with_scores() → InternalMetrics 収集
    → translate() → list[SomaticSense]
    → build_memory_context(somatic_senses=...) → _build_self_sense()
    → format_memory_sections() で「=== 今の感覚 ===」注入 → LLM
```

### テスト結果
1058 passed, 8 skipped（S.1a 26件含む）

---

## Phase S.1b: フィードバック + 矛盾検出 ✅

**完了: 2026-02-27** — 体感が正しかったかどうかを記録。ユーザー訂正と自己矛盾を検出。

### 作成ファイル
- `backend/services/memory/somatic_feedback.py` — SomaticOutcome, detect_correction, detect_self_dissonance, record_outcome, get_recent_accuracy, has_recent_contradiction
- `tests/test_somatic_feedback.py` — 24テスト

### 修正ファイル
- `backend/core/db.py` — `somatic_log` テーブル追加
- `backend/core/agent_graph/nodes/actions.py` — `_record_somatic_feedback()` 追加、s5_commit に統合（`SOMATIC_FEEDBACK_ENABLED` ゲート）
- `backend/core/agent_graph/nodes/routing.py` — `_collect_somatic_senses()` で v0.2 フィールドを somatic_log から読み込み

### データフロー
```
s5_commit → somatic_senses + user_text + final_text
    → detect_correction(user_text) — ユーザー訂正検出
    → detect_self_dissonance(sense, response) — 自己矛盾検出
    → record_outcomes_batch() → somatic_log テーブル
次ターンの depth_selector:
    → get_recent_accuracy() / has_recent_contradiction()
    → InternalMetrics v0.2 フィールド設定
    → translate() で不一致感覚テキスト生成
```

### 有効化
- `SOMATIC_FEEDBACK_ENABLED=True` で有効化（デフォルト False）

---

## Phase S.1.5: 適応的閾値 ✅

**完了: 2026-03-03** — 体感の閾値がニアの経験から学習。Sleep で回帰（ホメオスタシス）。

### 修正ファイル

**`backend/services/memory/somatic_calibration.py`**
- `update(accuracy, sample_count, user_correction) -> bool` メソッド追加
  - accuracy < 0.5 → 閾値UP (+0.02、慎重に）
  - accuracy > 0.8 → 閾値DOWN (-0.02、大胆に）
  - ユーザー訂正 → ショック (+0.04)
  - 最低5サンプル必要
  - bounds: high(0.60-0.90), medium(0.35-0.70), low(0.10-0.35)
- `regress(step=0.01)` メソッド追加
  - 各閾値を初期値に向かって step 分戻す
  - learning(0.02) > regression(0.01) → 経験が時間に勝つ

**`backend/scripts/sleep_cycle/orchestrator.py`**
- `_update_somatic_calibration()` 追加（self-model 生成後、semantic confirm 前）
- somatic_log から当日 accuracy を算出 → `cal.update()` → `cal.regress()` → `save_calibration()`
- `SOMATIC_ADAPTIVE_ENABLED` ゲート

### 作成ファイル
- `tests/test_somatic_calibration.py` — 16テスト（update 10件 + regress 6件）

### テスト結果
1274 passed, 9 skipped（S.1.5 16件含む）

### 有効化
- `SOMATIC_ADAPTIVE_ENABLED=True` で有効化（デフォルト False）
- `SOMATIC_FEEDBACK_ENABLED=True` でデータ蓄積が先に必要

---

## Phase P.1: Pip バックエンド MVP ✅

**完了: 2026-02-27** — Pip の状態マシンが動作し、Bond が変化する。Unity なしで純 Python テスト可能。

### 作成ファイル
- `backend/services/pip/pip_state.py` — PipState, NiaContext, BOND_RULES, apply_interaction_bond, apply_time_decay
- `backend/services/pip/state_machine.py` — PipStateMachine（6基本状態 + 2高Bond状態）
- `backend/services/pip/interaction_detector.py` — NiaInteractionDetector（regex パターンマッチ）
- `tests/test_pip_state_machine.py` — 49テスト（Bond, 状態遷移, InteractionDetector, 統合テスト）

### 修正ファイル
- `backend/core/agent_graph/nodes/actions.py` — `_update_pip_interaction()` 追加、s5_commit に統合（`PIP_ENABLED` ゲート）
- `backend/core/config.py` — `PIP_ENABLED=False`

### データフロー
```
s5_commit → nia_response + action_results
    → interaction_detector.detect() → NiaContext
    → apply_interaction_bond(pip, ctx) → Bond 更新
    → telemetry_kv['pip_state'] に JSON 保存
```

### テスト結果
1131 passed, 8 skipped（S.1b 24件 + P.1 49件 含む）

### 有効化
- `PIP_ENABLED=True` で有効化（デフォルト False）

---

## Phase P.2: 部屋バックエンド MVP ✅

**完了: 2026-02-27** — 部屋の状態管理、時間連動照明、Pip の1分間隔更新ループ。

### 作成ファイル
- `backend/services/room/room_state.py` — RoomState, RoomObject, WallArt, OBJECT_CATALOG_V1（12品目）, compute_lighting, apply_lamp_bonus, load/save
- `backend/services/room/room_action.py` — RoomAction, execute_room_action（place/move/remove/color/hang_art）, MAX_OBJECTS=20
- `backend/services/room/update_loop.py` — room_update_loop（60秒間隔 asyncio）, run_single_update, _update_favorite_spot
- `backend/controllers/api/room_router.py` — GET /api/room/state, POST /api/room/action, GET /api/room/catalog
- `tests/test_room.py` — 48テスト（RoomState, Catalog, Lighting, Persistence, Actions, UpdateLoop, FavoriteSpot, Router API）

### 修正ファイル
- `backend/server.py` — room_router 登録 + room_update_loop を lifespan で起動（`ROOM_UPDATE_ENABLED` ゲート）
- `backend/core/config.py` — `ROOM_UPDATE_ENABLED=False`

### データフロー
```
room_update_loop (60秒間隔):
    → compute_lighting(hour) → time_of_day, light_intensity, light_color
    → apply_lamp_bonus(room) → ランプ存在で +0.2
    → PipStateMachine.update() → mood, animation, position
    → apply_time_decay() → Bond 減衰
    → pip_position_history 記録（48h保持）
    → _update_favorite_spot() → Bond≥0.4 + 60件で形成

REST API:
    → POST /api/room/action → execute_room_action() → save_room_state()
    → GET /api/room/state → load_room_state() → JSON
```

### テスト結果
1179 passed, 8 skipped（P.2 48件含む）

### 有効化
- `ROOM_UPDATE_ENABLED=True` で更新ループ有効化（デフォルト False）
- REST API は常に利用可能

---

## Phase P.4: Bond 深化 ✅

**完了: 2026-03-03** — Bond 同期修正、感情推論、NiaContext 永続化、部屋変更リアクション。

### 発見した重大バグ: Bond State Desync
- `_update_pip_interaction()` (s5_commit) → `telemetry_kv['pip_state']` に bond を書く
- `update_loop` → `room_state.json` の `pip_state` を読む
- **完全に分離しており、bond 変化が update_loop に伝わっていなかった**
- COMFORT/EMPATHY（bond≥0.7）、favorite_spot（bond≥0.4）が永久に発動しない状態だった

### 修正ファイル

**`backend/services/pip/pip_state.py`**
- `dict_to_pip()` / `pip_to_dict()` を public 関数として追加（update_loop と room_action から共用）

**`backend/services/room/update_loop.py`**
- `_sync_bond_from_telemetry(pip)` — telemetry_kv から最新 bond を読み反映
- `_load_last_nia_context() -> NiaContext | None` — 5分以内の NiaContext を読み込み
- private `_dict_to_pip` / `_pip_to_dict` → public 版に置換

**`backend/core/agent_graph/nodes/actions.py`**
- `_infer_emotional_state(state) -> str` — dissonance/低confidence/somatic矛盾 → "low"、それ以外 → "neutral"
- `_update_pip_interaction` の `emotional_state="neutral"` → `_infer_emotional_state(state)` に置換
- NiaContext を `telemetry_kv['last_nia_context']` に毎ターン保存

**`backend/services/room/room_action.py`**
- `_apply_pip_reaction(room, action)` 追加
  - move/remove → bond -= 0.008 + animation = "look_around"
  - hang_art → animation = "react_to_art"

**`backend/core/config.py`**
- `SOMATIC_FEEDBACK_ENABLED` デフォルトを True に変更（データ蓄積開始）

### テスト追加
- `tests/test_pip_state_machine.py` — 12テスト追加（dict変換3 + 感情推論5 + 部屋リアクション4）

---

## Phase P.3: お絵かき統合

**未着手** — hang_art アクション、WallArt 永続化、Unity テクスチャ連携

---

## Phase P.5: Context Builder 統合 ✅

**完了: 2026-03-03** — 部屋の状態をルールベースでテキスト化し、LLM コンテキストに注入。LLM 呼び出し 0 回。

### 作成ファイル
- `backend/services/room/room_context.py` — `build_room_context() -> str`
  - 時間帯テキスト（朝/昼/夕/夜/深夜）
  - Pip の状態テキスト（mood に基づく、**bond 値は絶対に出さない**）
  - オブジェクト名の列挙
  - 壁の絵の有無
  - お気に入りスポット（あれば）
  - 出力: `=== 部屋の様子 ===\n- 朝の光が...\n- Pipは...`
- `tests/test_room_context.py` — 10テスト

### 修正ファイル
**`backend/core/agent_graph/nodes/helpers.py`** — `build_context_suffix()`
- TONE_ANCHOR の直後、somatic の直前に部屋コンテキストを挿入
- 条件: `memory_mode != "pinned_only"` AND `ROOM_UPDATE_ENABLED`
- 順序: 外部知覚（部屋）→ 内部感覚（somatic）

### 設計原則
- somatic_translator と同じパターン: ルールベース、LLM 呼び出しなし
- 「仕組みは隠す。体験は渡す。」— Bond 値は絶対に出力に含まない

### テスト結果
1274 passed, 9 skipped（P.5 10件含む）

---

## Phase S.2: 体感 + Pip/Room 統合

**目的**: Pip の存在と部屋の状態が体感として注入。三層レスキュー Layer 2。

- `somatic_translator.py` に `_room_senses(metrics, room) -> list[SomaticSense]` 追加
- Pip の無条件の存在 → 記憶精度と無関係な安心感テキスト
- 具体テキストは P.1〜P.4 の挙動観察後に設計（設計ドキュメントの方針通り）

---

## Unity 並行トラック

バックエンド API（REST + WebSocket）が先行。Unity はインターフェース仕様確定後に着手可能。

| Phase | 内容 | 並行時期 |
|-------|------|---------|
| U.1 | 空の部屋シーン（6畳、時間連動照明、URP） | P.2 と同時 |
| U.2 | Pip 3Dモデル + アニメーション（機械犬、金歯車、レンズ目） | P.1〜P.4 と同時 |
| U.3 | WebSocket ブリッジ（`/ws/room`、状態push、差分送信） | P.2 と同時 |
| U.4 | オブジェクトシステム（Prefab × カタログ、動的配置） | P.2 完了後 |
| U.5 | 絵テクスチャ（フレームへの動的テクスチャ適用） | P.3 と同時 |
| U.6 | カメラ + 配信表示（DisplayConfig、OBS連携） | P.7 と同時 |

### WebSocket プロトコル (`backend/controllers/ws_room.py`)

```json
// Server → Unity
{"type": "room_state", "data": { ...RoomState... }}
{"type": "pip_update", "data": {"mood": "curious", "animation": "head_tilt", "position": "near_nia"}}
{"type": "lighting_update", "data": {"time_of_day": "night", "intensity": 0.3}}
```

### Unity 設計上の注意
- Pip: 機械犬（金/銀/セラミック）、柴犬プロポーション、関節に歯車
- 13 アニメーション: idle, head_tilt, tail_wag, yawn, sleeping, wake_up, snuggle, lean_against, spin, look_around, retreat, approach, react_to_art
- **Bond 値は Unity 側にも渡すが表示は絶対にしない**（行動のみで表現）

---

## 検証方法

```bash
# S.1a（完了済み）
pytest tests/test_somatic_translator.py tests/test_context_builder_somatic.py -v

# S.1b（完了済み）
pytest tests/test_somatic_feedback.py -v

# S.1.5（完了済み）
pytest tests/test_somatic_calibration.py -v

# P.1（完了済み）
pytest tests/test_pip_state_machine.py -v

# P.2（完了済み）
pytest tests/test_room.py -v

# P.4（完了済み — P.1テストに統合）
pytest tests/test_pip_state_machine.py -v

# P.5（完了済み）
pytest tests/test_room_context.py -v

# 全体回帰
ruff check backend/ && pytest tests/ -v
```
