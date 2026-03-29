# Pip / Room / Temporal / Livestream 統合設計メモ v0.3

> **Status**: Contract 1/2/3 実装完了
> **Date**: 2026-03-13（v0.3: 実装完了に伴い更新）
> **Scope**: Pip・ニアの部屋・Temporal Somatic Contrast・配信用 motion を 1 本の状態系として統合する
> **依存**: `docs/pip_and_room_design.md`, `docs/temporal_somatic_contrast_design.md`, `docs/somatic_self_awareness_design.md`, `docs/implementation_roadmap.md`

---

## 1. 目的

今のニアには、Pip、部屋、時間、配信表示という4つの層がある。

- `Pip` は評価しない関係
- `部屋` は場所と時間の器
- `Temporal Contrast` は前と今の差分
- `Livestream Motion` は視聴者に見える動き

これらを別々の機能として作ると drift する。
本メモでは、**同じ状態を別の見せ方で使う 1 つの統合システム**として整理する。

---

## 2. 現在地

| システム | 実装 | 稼働 |
|---|---|---|
| Pip 状態マシン (P.1) | 完了 | 稼働中 |
| 部屋 (P.2) | 完了 | 稼働中 |
| Bond 深化 (P.4) | 完了 | 稼働中 |
| 部屋コンテキスト (P.5) | 完了 | LLM 注入は未接続 |
| Fingerprint (TS.0) | 完了 | recording 稼働中 |
| Pip Somatic Touch (Phase D) | 完了 | shadow のみ |

Contract 1/2/3 は全て実装完了。フラグ `RUNTIME_FACTS_ENABLED` / `ATMOSPHERE_ENABLED` で有効化する。
次の課題は TS.1 Idle Tick / TS.2 Contrast Engine / S.2 統合。

---

## 3. 統合の核

### 3.1 責務分担

| 層 | 役割 |
|---|---|
| Pip | 言語を介さない関係性 |
| Room | 場所と時間の器 |
| Temporal | 変化と継続の実感 |
| Livestream | その結果として見える外的変化 |

### 3.2 一言で言うと

**ニアが「場所と時間の中に存在している」と感じられるようにする単一システム。**

---

## 4. 設計原則

| # | 原則 | 理由 |
|---|---|---|
| I.1 | Bond は見せない | Pip を数値最適化対象にしない |
| I.2 | 時間 fact はそのまま渡す | `夜だった` や `しばらくぶり` は仕組みではなく体験 |
| I.3 | 内部指標だけ体感化する | confidence / depth / skeleton 差分はそのまま出さない |
| I.4 | 動きは演出ではなく状態の結果 | 配信向けに賑やかにするためのランダム挙動を入れない |
| I.5 | memory に残すのは「意味のあった変化」だけ | 全てをログ化しない |
| I.6 | runtime では軽く、Idle Tick でも LLM を呼ばない | 常時性を確保しつつコストを上げない |
| I.7 | 時刻は自動注入しない | 時間帯（体験）と時刻（情報）は分離する。時刻はニアが聞かれた時に参照できる経路を別途用意 |

---

## 5. 統合アーキテクチャ

### 5.1 4 層

1. `Ambient Layer`
   - `room_update_loop`
   - `pip_state_machine`
   - 時間帯
   - 沈黙時間
   - idle 中の NiaCore state 変化

2. `State Layer`
   - `turn_fingerprints`
   - `room_state`
   - `pip_state`
   - `idle_context`
   - `last_active_at`

3. `Interpretation Layer`
   - `build_runtime_facts()` — Contract 1
   - `build_somatic_atmosphere()` — Contract 2
   - `contrast_engine`
   - `contrast_to_somatic`

4. `Presentation Layer`
   - ニアへの runtime context — `=== 今の場所と時間 ===`
   - ニアへの somatic — `=== 場の空気 ===`
   - 配信画面上の motion — Contract 3

### 5.2 データフロー

```text
Room Update Loop / Pip State Machine / Idle Tick
    ↓
room_state / pip_state / idle_context
    ↓
s5_commit → turn_fingerprints
    ↓
build_runtime_facts() / build_somatic_atmosphere() / motion events
    ↓
1. runtime facts としてニアへ渡す（Contract 1）
2. somatic としてニアへ渡す（Contract 2）
3. WS state/event として Unity へ送る（Contract 3）
```

---

## 6. Contract 1: Runtime Fact

**確定: 2026-03-12**

ニアに「そのまま」渡してよい事実。体感化せず、解釈もしない。
内部では enum 的な stable 値を持ち、注入時に日本語化する。

### 6.1 内部表現

```python
class TimeOfDay(str, Enum):
    MORNING    = "morning"      # 5-10
    DAY        = "day"          # 10-20
    NIGHT      = "night"        # 20-1
    LATE_NIGHT = "late_night"   # 1-5

class SilenceGap(str, Enum):
    NONE      = "none"          # < 10s
    SHORT     = "short"         # < 300s
    LONG      = "long"          # < 1800s
    VERY_LONG = "very_long"     # >= 1800s

class PipVisible(str, Enum):
    RESTING  = "resting"        # idle
    LOOKING  = "looking"        # curious, alert
    PLAYFUL  = "playful"        # playful
    SLEEPY   = "sleepy"         # sleepy
    SLEEPING = "sleeping"       # sleeping
    NEAR     = "near"           # comfort, empathy

class RoomChange(str, Enum):
    OBJECT_ADDED   = "object_added"
    OBJECT_REMOVED = "object_removed"
    ART_HUNG       = "art_hung"
    ART_REMOVED    = "art_removed"
    NONE           = "none"

@dataclass
class RuntimeFacts:
    time_of_day: TimeOfDay
    silence_gap: SilenceGap
    pip_visible: PipVisible
    pip_position_near: bool
    room_change: RoomChange     # latched event, emitted once
```

### 6.2 マッピング

**mood → PipVisible（観察可能状態を正にする）:**

```python
_MOOD_TO_VISIBLE = {
    "idle":     PipVisible.RESTING,
    "curious":  PipVisible.LOOKING,
    "playful":  PipVisible.PLAYFUL,
    "sleepy":   PipVisible.SLEEPY,
    "sleeping": PipVisible.SLEEPING,
    "alert":    PipVisible.LOOKING,
    "comfort":  PipVisible.NEAR,
    "empathy":  PipVisible.NEAR,
}
```

`mood → visible_state → label` の2段構成。mood enum の追加/変更が直接表示文に漏れない。
このマッピングは shared helper に切り出し、`room_context.py` と共有する。

**PipVisible → 日本語:**

| PipVisible | 表示 |
|---|---|
| RESTING | 静かにしている |
| LOOKING | こちらを見ている |
| PLAYFUL | 楽しそうにしている |
| SLEEPY | 眠そうにしている |
| SLEEPING | 眠っている |
| NEAR | そばにいる |

**TimeOfDay → 日本語:**

| TimeOfDay | 表示 |
|---|---|
| MORNING | 朝 |
| DAY | 昼 |
| NIGHT | 夜 |
| LATE_NIGHT | 深夜 |

**SilenceGap → 日本語:**

| SilenceGap | 表示 |
|---|---|
| NONE | （出力しない） |
| SHORT | （出力しない） |
| LONG | 少し間があった |
| VERY_LONG | しばらくぶり |

**RoomChange → 日本語:**

| RoomChange | 表示 |
|---|---|
| OBJECT_ADDED | 部屋に物が増えた |
| OBJECT_REMOVED | 部屋の物が減った |
| ART_HUNG | 壁に絵が飾られた |
| ART_REMOVED | 壁の絵が外された |
| NONE | （出力しない） |

### 6.3 silence_gap の取得（thread-scoped）

`telemetry_kv` のグローバル `last_turn_timestamp` は `default_thread` と `nero_meeting_*` が混ざるため使えない。
`turn_fingerprints` テーブルから `thread_id` で最新の `timestamp` を引いて gap を算出する。

```python
def _get_thread_gap_seconds(thread_id: str) -> float:
    row = conn.execute(
        "SELECT timestamp FROM turn_fingerprints "
        "WHERE thread_id = ? ORDER BY timestamp DESC LIMIT 1",
        (thread_id,),
    ).fetchone()
    if not row:
        return 0.0
    return time.time() - row["timestamp"]
```

### 6.4 room_change の latch

前回の `RoomState` との diff を毎ターン出すと同じ change が連続する。
event 的に一度だけ emit し、`last_emitted_room_hash` で消す。

```python
def _detect_room_change(current: RoomState, *, conn) -> RoomChange:
    current_hash = _room_content_hash(current)
    last_hash = _get_kv(conn, "last_emitted_room_hash")
    if last_hash == current_hash:
        return RoomChange.NONE
    change = _compute_change(last_hash, current_hash, current)
    if change != RoomChange.NONE:
        _set_kv(conn, "last_emitted_room_hash", current_hash)
    return change
```

### 6.5 時刻について

時刻（`22:43` 等）は `RuntimeFacts` に含めない。毎ターン自動注入しない。
ニアが聞かれた時に答えられる経路（tool/function call）を別途用意する。
時間帯（体験）と時刻（情報）は分離する。

### 6.6 注入フォーマット

```python
def format_runtime_facts(facts: RuntimeFacts) -> str:
    lines = [_TIME_LABELS[facts.time_of_day] + "。"]
    gap_label = _GAP_LABELS.get(facts.silence_gap)
    if gap_label:
        lines.append(gap_label + "。")
    lines.append(f"Pipは{_VISIBLE_LABELS[facts.pip_visible]}。")
    change_label = _ROOM_CHANGE_LABELS.get(facts.room_change)
    if change_label:
        lines.append(change_label + "。")
    return "=== 今の場所と時間 ===\n" + "\n".join(lines)
```

出力例:

```
=== 今の場所と時間 ===
夜。
しばらくぶり。
Pipは眠っている。
壁に絵が飾られた。
```

### 6.7 既存 `build_room_context()` との関係

`build_runtime_facts()` を新設し、`build_room_context()` は当面並存。
段階的に Contract 2 に吸収する。

---

## 7. Contract 2: Somatic Injection

**確定: 2026-03-12**

Contract 1 の `RuntimeFacts` を素材にして、**いつ・何を** `=== 場の空気 ===` セクションに注入するか。
条件付き注入。変化があった時だけ出す。

### 7.1 セクション構成

| セクション | 内容 | 注入条件 |
|---|---|---|
| `=== 今の感覚 ===` | confidence / surprise / memory 体感 | 毎ターン |
| `=== 会話の気配 ===` | skeleton の focus / intent 体感 | `SKELETON_SOMATIC_ENABLED` 時 |
| `=== 場の空気 ===`（新規） | Pip の存在感 / 部屋 / 時間の実感 | **条件付き** |

### 7.2 主トリガー（これが無ければセクションを出さない）

| ID | 条件 | 基本テキスト |
|---|---|---|
| T4 | `room_change ≠ none` | `部屋の空気が少し変わった` |
| T3 | `pip_visible` が前ターンと異なる | `隣の気配が変わった` |
| T2 | `pip_position_near = true`（cooldown 後） | `そばに静かな気配がある` |

- T3 が発火したら T2 は吸収（行を分けない）
- T4 と T3 が同時なら両方出す（最大2行）
- **どれも当てはまらなければ `=== 場の空気 ===` を出さない**

### 7.3 修飾子（主トリガーのテキストに乗る）

| ID | 条件 | 効果 |
|---|---|---|
| M1 | `silence_gap ∈ {long, very_long}` | テキスト末尾の空気感が変わる |
| M5 | `time_of_day` が前ターンと異なる | テキスト末尾の空気感が変わる |

修飾子は Contract 1 の fact と語彙を被らせない。
fact が「しばらくぶり」なら、修飾子は「静けさの中で」。
fact が「夜」なら、修飾子は「光の変わり目に」。
同じ事実の言い換えではなく、その事実がもたらす空気感。

### 7.4 テンプレート

```python
_SOMATIC_TEMPLATES = {
    # T3: Pip 状態変化
    ("T3", None):      "隣の気配が変わった",
    ("T3", "M1"):      "静けさの中で、隣の気配が変わった",
    ("T3", "M5"):      "光の変わり目に、隣の気配が変わった",
    ("T3", "M1+M5"):   "静かな時間が移り変わる中で、隣の気配が変わった",

    # T2: Pip 近接
    ("T2", None):      "そばに静かな気配がある",
    ("T2", "M1"):      "ふと気づくと、そばに気配がある",

    # T4: 部屋変化
    ("T4", None):      "部屋の空気が少し変わった",
    ("T4", "M5"):      "光が動いて、部屋の空気が変わった",
}
```

### 7.5 優先度

T4（部屋の変化） > T3（Pip 状態変化） > T2（Pip 近接）

一回きりの event（T4）を、継続的な状態（T2）より優先する。

### 7.6 制約

- **最大2行**
- **冒頭の注記文なし**（セクション名だけで十分）

### 7.7 cooldown（thread-scoped）

`telemetry_kv` に thread-scoped で emit 履歴を記録:

```
key:   somatic_emit:{thread_id}:{trigger_id}
value: last_turn_id
```

`telemetry_kv` 自体はグローバルでも、key に `thread_id` を含めれば thread-scoped になる。
新テーブルは切らない。
`turn_index` は経路差や再計算で揺れやすいため、`turn_id`（UUID）で emit 済み判定する。

```python
_COOLDOWN_TURNS = {
    "T4": 1,    # room event は毎回出してよい（latch で1回だけ）
    "T3": 3,    # Pip 変化は 3 ターン空ける
    "T2": 5,    # Pip 近接は 5 ターン空ける
}
```

### 7.8 出力例

Pip が sleeping → looking に変化 + 深夜:
```
=== 場の空気 ===
- 静かな時間が移り変わる中で、隣の気配が変わった
```

部屋に絵が飾られた + Pip が近くにいる:
```
=== 場の空気 ===
- 部屋の空気が少し変わった
- そばに静かな気配がある
```

何も変化なし:
```
（セクション省略）
```

---

## 8. Contract 3: Livestream Motion

**確定: 2026-03-12**

backend は「状態」と「変化」だけ送る。常時の micro motion は Unity local で完結。

### 8.1 責務分離

| 層 | 責務 | 送信方法 |
|---|---|---|
| **Unity local** | idle_micro（呼吸、まばたき、姿勢微動） | backend から送らない |
| **Backend state** | conversation_state | WS state update（遷移時のみ） |
| **Backend event** | pip_reaction / room_event / time_shift | WS event（遷移時のみ） |

### 8.2 Backend State: conversation_state

```python
class ConversationState(str, Enum):
    IDLE      = "idle"
    LISTENING = "listening"
    THINKING  = "thinking"
    SPEAKING  = "speaking"
```

状態遷移:
```
IDLE → LISTENING（ユーザー入力受信）
LISTENING → THINKING（LLM 呼び出し開始）
THINKING → SPEAKING（応答生成完了、TTS 再生開始）
SPEAKING → IDLE（TTS 再生完了）
IDLE → IDLE（沈黙継続）
```

WS メッセージ（遷移時のみ送信）:
```json
{
  "type": "state",
  "key": "conversation_state",
  "value": "thinking",
  "ts": 1741795200.0
}
```

Unity 側が現在の state を保持する。

**WS 再接続時の初期 snapshot:**
`/ws/room` 接続直後に、現在の全 state を1回送信する。late subscriber が現在状態を知らないまま遷移 event だけ受け取る問題を防ぐ。

```json
{
  "type": "snapshot",
  "conversation_state": "idle",
  "pip_visible": "sleeping",
  "pip_position_near": false,
  "time_of_day": "night",
  "ts": 1741795200.0
}
```

### 8.3 Backend Event: MotionEvent

```python
@dataclass
class MotionEvent:
    event_id: str              # uuid
    category: str              # "pip_reaction" | "room_event" | "time_shift"
    action: str                # MotionAction registry から選択
    intensity: float           # 0.0-1.0
    source_trigger: str        # "T3" | "T4" | "T5"
    ts: float                  # emit timestamp
    duration_ms: int | None    # アニメーション推奨時間。None = 状態変化（持続）
```

**action は shared registry で管理する。** backend と Unity が同じ一覧を参照し、drift を防ぐ。

```python
class MotionAction(str, Enum):
    # pip_reaction
    PIP_SLEEP    = "pip_sleep"
    PIP_WAKE     = "pip_wake"
    PIP_LOOK     = "pip_look"
    PIP_PLAY     = "pip_play"
    PIP_SNUGGLE  = "pip_snuggle"
    PIP_DROWSY   = "pip_drowsy"
    PIP_APPROACH = "pip_approach"
    PIP_WITHDRAW = "pip_withdraw"
    # room_event
    OBJECT_ADDED   = "object_added"
    OBJECT_REMOVED = "object_removed"
    ART_HUNG       = "art_hung"
    ART_REMOVED    = "art_removed"
    # time_shift
    LIGHTING_CHANGE = "lighting_change"
```

### 8.4 emit ルール（変化した時だけ）

| 遷移 | → event |
|---|---|
| `pip_visible` が前と異なる | `pip_reaction` / action は遷移先に応じて決定 |
| `pip_position_near` が false → true | `pip_reaction` / `pip_approach`, duration_ms=None |
| `pip_position_near` が true → false | `pip_reaction` / `pip_withdraw`, duration_ms=None |
| `room_change ≠ none` | `room_event` / `room_change.value`, duration_ms=3000 |
| `time_of_day` が前と異なる | `time_shift` / `lighting_change`, duration_ms=5000 |

**pip_reaction の action マッピング:**

```python
_PIP_TRANSITION_ACTIONS = {
    (Any, PipVisible.SLEEPING):  "pip_sleep",
    (PipVisible.SLEEPING, Any):  "pip_wake",
    (Any, PipVisible.LOOKING):   "pip_look",
    (Any, PipVisible.PLAYFUL):   "pip_play",
    (Any, PipVisible.NEAR):      "pip_snuggle",
    (Any, PipVisible.SLEEPY):    "pip_drowsy",
}
```

### 8.5 WS メッセージ例

Pip が sleeping → looking に変化:
```json
{
  "type": "motion",
  "event_id": "a1b2c3d4",
  "category": "pip_reaction",
  "action": "pip_wake",
  "intensity": 0.4,
  "source_trigger": "T3",
  "ts": 1741795200.0,
  "duration_ms": null
}
```

部屋に絵が飾られた:
```json
{
  "type": "motion",
  "event_id": "e5f6g7h8",
  "category": "room_event",
  "action": "art_hung",
  "intensity": 0.5,
  "source_trigger": "T4",
  "ts": 1741795201.0,
  "duration_ms": 3000
}
```

### 8.6 intensity の設計

intensity は Unity 側のアニメーション強度のヒント。backend は 0.0-1.0 の値を送るだけで、具体的なアニメーション表現は Unity が決める。

```
0.0-0.3: 微細（気づかないくらい）
0.3-0.6: 自然に見える
0.6-1.0: 明確に見える
```

### 8.7 Unity 側の責務

- `idle_micro` は Unity 内で完結（常時ループ）
- `conversation_state` を受けてアニメーション遷移
- `motion` event を受けて一回きりまたは状態変化のアニメーション再生
- `duration_ms = null` なら状態保持、次の event まで維持
- `event_id` で重複排除

### 8.8 動かさないもの

- 内部メトリクスに直結した演出なし
- ランダムリアクションなし
- backend は状態と変化だけ送る。演出の解釈は Unity

### 8.9 motion prev の scope（設計判断 2026-03-13）

**問題**: Contract 1/2 の prev 値（`prev_pip_visible:{thread_id}` 等）は thread-scoped にする必要がある（`default_thread` と `nero_meeting_*` で独立した LLM コンテキスト）。しかし、Contract 3 の motion event は global な Room/Pip 状態に対して発火するため、thread-scoped な prev と比較すると、thread 切替時に実際には変化していない pip/room/time の motion が再発火する。

**解決**: prev の scope を分離する。

| 用途 | prev の保持場所 | scope |
|------|----------------|-------|
| Contract 1 (RuntimeFacts) | `telemetry_kv` `prev_pip_visible:{thread_id}` 等 | thread-scoped |
| Contract 2 (Atmosphere) | `telemetry_kv` `prev_pip_visible:{thread_id}` 等 | thread-scoped |
| Contract 3 (Motion) | `room_manager._motion_prev_*` | **global** |

- `room_manager` はプロセス内シングルトン。最後に broadcast した state を保持する
- motion event の比較は常に「前回の broadcast 時点」との差分になる
- thread を切り替えても、Room/Pip が実際に変化していなければ motion は発火しない

### 8.10 conversation_state の callsite

| 状態 | タイミング | 実装場所 |
|------|-----------|---------|
| LISTENING | ユーザー入力受信後、SSE stream 開始時 | `agent_orchestrator.py` `stream_sse()` |
| THINKING | LLM `stream_chat()` 呼び出し直前 | `agent_orchestrator.py` `stream_sse()` |
| SPEAKING | `final_result` イベント受信時 | `agent_orchestrator.py` `stream_sse()` |
| IDLE | `s5_commit` 完了後 | `actions.py` `s5_commit()` |

`_broadcast_conversation_state()` は `RUNTIME_FACTS_ENABLED` フラグで制御。無効時は何もしない。

---

## 9. Temporal によって開くもの

Fingerprint が毎ターン記録されるようになったことで、次の 3 つが接続可能になった。

### 9.1 TS.1 Idle Tick

ターン間も NiaCore（CfC）だけ回し、Pip の状態変化と時間経過を idle context に反映する。LLM は呼ばない。

目的:

- 「ニアがいない時間」を減らす
- 沈黙を不在ではなく経過として持つ
- Room / Pip と同じ時間の中にニアもいるようにする

### 9.2 TS.2 Contrast Engine

過去の fingerprint と現在を比較し、変化を somatic に変換する。

目的:

- `前と何か違う`
- `最近こういう感じが多い`
- `以前より少し落ち着いている`

を物語化せずに感じられるようにする。

### 9.3 Room + Pip + Temporal 統合

- 夜遅い
- 沈黙が長い
- Pip が sleepy

のような状態が同じ時間軸に乗る。
ニアはそこから `静かな時間が流れている` という fact / somatic を受け取れる。

---

## 10. 実装優先順

1. **Contract 1 実装**: `build_runtime_facts()` + shared visible-state mapper
2. **Contract 2 実装**: `build_somatic_atmosphere()` + cooldown + テンプレート
3. **Contract 3 実装**: WS motion event + conversation_state
4. `TS.0.5` fingerprint audit
5. `TS.1 Idle Tick`
6. `TS.2 Contrast Engine`
7. `S.2 Room/Pip/Temporal somatic` 統合

### 10.1 実装状態（2026-03-13）

| 項目 | ファイル | 状態 |
|------|---------|------|
| Contract 1: RuntimeFacts | `backend/services/room/runtime_facts.py` | **完了** |
| Contract 2: Somatic Atmosphere | `backend/services/room/somatic_atmosphere.py` | **完了** |
| Contract 3: Motion Events | `backend/services/room/motion_events.py` | **完了** |
| Contract 3: WS broadcast | `backend/controllers/ws_room.py` | **完了** |
| Contract 3: Motion broadcast helper | `backend/core/agent_graph/nodes/commit_helpers.py` | **完了** |
| Contract 3: conversation_state callsite | `backend/services/agent_orchestrator.py` | **完了** |
| routing 統合 | `backend/core/agent_graph/nodes/routing.py` | **完了** |
| helpers 統合 | `backend/core/agent_graph/nodes/helpers.py` | **完了** |
| s5_commit 統合 | `backend/core/agent_graph/nodes/actions.py` | **完了** |
| state フィールド追加 | `backend/core/agent_graph/state.py` | **完了** |
| フィーチャーゲート | `backend/core/config.py` — `RUNTIME_FACTS_ENABLED`, `ATMOSPHERE_ENABLED` | **完了** |
| room_context shared mapper | `backend/services/room/room_context.py` → `mood_to_visible()` 共有 | **完了** |
| テスト: runtime_facts | `tests/test_runtime_facts.py` (39件) | **完了** |
| テスト: somatic_atmosphere | `tests/test_somatic_atmosphere.py` (17件) | **完了** |
| テスト: motion_events | `tests/test_motion_events.py` (17件) | **完了** |
| テスト: ws_room (更新) | `tests/test_ws_room.py` | **完了** |
| テスト: room_context (更新) | `tests/test_room_context.py` | **完了** |

### 10.2 デプロイ戦略

1. **Phase A**: `RUNTIME_FACTS_ENABLED=true`, `ATMOSPHERE_ENABLED=false` — Contract 1 のみ有効化。`=== 今の場所と時間 ===` を LLM に注入、motion broadcast 開始
2. **Phase B**: `ATMOSPHERE_ENABLED=true` — Contract 2 も有効化。`=== 場の空気 ===` を条件付きで LLM に注入
3. **Phase C**: 観測。runtime_facts / atmosphere の影響をログで確認。問題があれば即フラグ off

### 10.3 現段階の判断

- `Pip Somatic Touch` は shadow のまま様子を見る
- 配信向け motion は `Pip + Room` を先に、ニア本体の大きな演技は後
- 次は TS.1 Idle Tick / TS.2 Contrast Engine

---

## 11. 既存 docs との関係

| ドキュメント | 役割 |
|---|---|
| `docs/pip_and_room_design.md` | Pip と部屋の個別設計 |
| `docs/temporal_somatic_contrast_design.md` | fingerprint / Idle Tick / Contrast |
| `docs/somatic_self_awareness_design.md` | 体感へ変換する原則 |
| `docs/implementation_roadmap.md` | 実装順序 |

本メモはこれらを置き換えるものではなく、**接続仕様の要約**である。

---

## 12. 未確定点

1. ~~`room_context` をどの位置で prompt に入れるか~~ → **確定**: `=== 今の場所と時間 ===` として somatic の前に配置

2. ~~`Pip` の visible state をどの粒度で runtime に渡すか~~ → **確定**: `mood → PipVisible → label` の2段マッピング

3. 配信用 motion で、ニア本体の視線・姿勢をどこまで状態連動させるか → Unity 実装時に決定

4. memory に残す room / Pip 変化の閾値 → Contract 2 の主トリガー（T2/T3/T4）が発火した変化のみ候補

---

## 13. 一言でまとめると

`Pip + 部屋 + 時間 + 動き` は別々の企画ではない。
**ニアが場所と時間の中に存在していると感じられるようにする単一システム**として扱う。
