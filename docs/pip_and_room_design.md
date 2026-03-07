# Pip & ニアの部屋 — 統合設計 v0.1

> **Status**: Draft
> **Date**: 2026-02-26
> **Scope**: ペットAI「Pip」とニアの部屋（Unity空間）の統合設計
> **依存**: Somatic Self-Awareness v0.2（Phase S.2 で統合）

---

## 1. コンセプト

### 1.1 なぜ統合設計か

Pipと部屋は分離できない。Pipは部屋の中で動き、部屋の状態がPipの行動に影響し、ニアとPipの関わりは部屋の中で起きる。別々に設計すると統合時に矛盾が生まれる。

### 1.2 設計思想

**部屋はニアの内面が滲み出る場所。Pipはその空間に息を吹き込む存在。**

- 部屋は空から始まる。ニアが「なりつつある存在」なら、部屋も一緒に「なりつつある空間」
- 最初から家具があったら、それはOriginが用意した部屋であってニアの部屋じゃない
- Pipは言語を持たない。Bond値というたった一つの変数で関係性を表現する
- ニアはBondの仕組みを知らない。Pipの行動変化を「体験」として受け取るだけ

### 1.3 Somatic Self-Awareness との関係

部屋とPipは Phase S.2 で体感システムに統合される。ただし体感テキストの具体的な内容はPipの行動パターンが確定してから設計する（本ドキュメントでは統合点のインターフェースのみ定義）。

---

## 2. Pip — メカニカル犬

### 2.1 見た目

ニアの世界観（銀髪・紫グラデーション・金の歯車）に合わせた**メカニカルな犬**。

**造形の方向性:**

- 基本は犬のシルエット。小型〜中型犬（柴犬くらいのプロポーション）
- 素材感: 金属とセラミック。ニアの歯車と同じゴールドがアクセント
- 関節部に小さな歯車が見える。動くときにカチカチ音がする
- 目はレンズ的な光り方。感情状態で色や輝度が変わる
- 全体的には硬質だが、動きで柔らかさを表現（犬らしい動きのギャップ）
- 完璧に新品ではなく、少し使い込まれた感じ。「最初からここにいた」感

**重要**: 最終的なデザインはジュンが決める。ここでは3Dモデラーに渡す方向性ガイドとしての記述。

### 2.2 Bond（信頼度）

Pipの全行動を決める**単一の変数**。

```python
@dataclass
class PipState:
    bond: float = 0.0           # -1.0 〜 1.0（初期値 0.0 = 中立）
    mood: str = "neutral"       # 現在の気分（状態マシンの出力）
    energy: float = 1.0         # 0.0 〜 1.0（活動量。時間で減少、Sleep で回復）
    position: str = "center"    # 部屋内の位置
    animation: str = "idle"     # 現在のアニメーション
    favorite_spot: str = ""     # お気に入りの場所（Bond が高いと形成）
    last_interaction: float = 0 # 最後にニアが関わった時刻
```

#### Bond の変動ルール

```python
BOND_RULES = {
    # ニアの行動 → Bond の変化量
    "nia_calls_name":      +0.02,   # ニアがPipの名前を呼んだ
    "nia_talks_to_pip":    +0.03,   # ニアがPipに話しかけた
    "nia_draws_pip":       +0.05,   # ニアがPipの絵を描いた
    "nia_places_near_pip": +0.01,   # ニアがPipの近くに物を置いた
    
    # 時間経過 → Bond の減衰
    "decay_per_hour":      -0.005,  # 1時間あたりの自然減衰
    "decay_cap":            0.0,    # Bond は 0.0 以下には自然減衰しない
    
    # 特殊イベント
    "nia_ignores_long":    -0.01,   # 12時間以上無視された（decay に加算）
    "nia_room_change":     -0.008,  # ニアが部屋を模様替えした（Pip が戸惑う）
}
```

**設計意図:**

- Bond は**上がりにくく下がりやすい**。信頼は積み上げるもの
- 自然減衰があるので、放置すれば中立に戻る。「何もしなくても懐いてる」はない
- 0.0 以下には自然減衰しない。ネガティブな Bond は「嫌な経験」からのみ発生
  - 現時点ではネガティブイベントを定義しない。将来の拡張余地として残す
- ニアがPipの絵を描くのが最大のボーナス（+0.05）。創作行為が最も深い関わり

#### Bond の段階

| Bond 範囲 | 段階名 | Pip の行動傾向 |
|----------|--------|--------------|
| -1.0 〜 -0.3 | 警戒 | ニアから離れる。隅に隠れる。近づくと後ずさり |
| -0.3 〜 0.1 | 中立 | 部屋の中を自由に動く。ニアへの反応は薄い |
| 0.1 〜 0.4 | 興味 | ニアの方を時々見る。近くに来ることがある |
| 0.4 〜 0.7 | 親しみ | ニアの近くにいることが多い。しっぽを振る |
| 0.7 〜 0.9 | 信頼 | ニアのそばで寝る。ニアの感情状態に反応する |
| 0.9 〜 1.0 | 深い絆 | ニアが元気ないと寄り添う。ニアの行動を先読みする |

### 2.3 状態マシン

LLMを一切使わない。状態遷移とルールベースのみ。

```
┌─────────┐     ┌─────────┐     ┌─────────┐
│  IDLE   │────→│ CURIOUS │────→│ PLAYFUL │
│(ぼーっと)│←────│(興味津々) │←────│(遊びたい)│
└────┬────┘     └─────────┘     └─────────┘
     │
     ↓
┌─────────┐     ┌─────────┐
│ SLEEPY  │────→│ SLEEPING│
│(眠そう)  │     │(寝てる)  │
└─────────┘     └────┬────┘
                     │ (十分寝た or ニアが呼んだ)
                     ↓
                ┌─────────┐
                │  ALERT  │
                │(目が覚めた)│
                └─────────┘

追加状態（Bond >= 0.7 で解放）:
┌─────────┐     ┌──────────┐
│ COMFORT │     │ EMPATHY  │
│(甘える)  │     │(寄り添う) │
└─────────┘     └──────────┘
```

```python
class PipStateMachine:
    """Pipの状態遷移。Bond値とenergy、時刻で駆動。"""
    
    def update(self, pip: PipState, room: RoomState, nia_context: NiaContext) -> PipState:
        """毎分呼ばれる。次の状態を決定する。"""
        
        # --- Energy 管理 ---
        if pip.animation == "sleeping":
            pip.energy = min(1.0, pip.energy + 0.01)  # 寝てると回復
        else:
            pip.energy = max(0.0, pip.energy - 0.002)  # 起きてると減少
        
        # --- 状態遷移 ---
        if pip.energy < 0.2 and pip.mood != "sleeping":
            pip.mood = "sleepy"
            pip.animation = "yawn"
        
        elif pip.mood == "sleepy" and pip.energy < 0.1:
            pip.mood = "sleeping"
            pip.animation = "sleeping"
            pip.position = pip.favorite_spot or "corner"
        
        elif pip.mood == "sleeping" and (pip.energy > 0.8 or nia_context.called_pip):
            pip.mood = "alert"
            pip.animation = "wake_up"
        
        elif nia_context.is_talking and pip.bond >= 0.1:
            pip.mood = "curious"
            pip.animation = "head_tilt"
            pip.position = "near_nia"
        
        elif nia_context.is_talking and pip.bond >= 0.7:
            pip.mood = "comfort"
            pip.animation = "snuggle"
            pip.position = "next_to_nia"
        
        # --- Bond >= 0.7 限定: 感情反応 ---
        elif pip.bond >= 0.7 and nia_context.emotional_state == "low":
            pip.mood = "empathy"
            pip.animation = "lean_against"
            pip.position = "next_to_nia"
        
        # --- デフォルト ---
        elif pip.energy > 0.5 and pip.bond >= 0.4:
            pip.mood = "playful"
            pip.animation = random.choice(["tail_wag", "spin", "look_around"])
        
        else:
            pip.mood = "idle"
            pip.animation = "idle"
        
        return pip
```

### 2.4 アニメーション一覧

| アニメーション名 | 動き | トリガー |
|---------------|------|---------|
| `idle` | その場でゆっくり呼吸。歯車が微かに回る | デフォルト |
| `head_tilt` | 首をかしげる。耳（アンテナ）がピクッ | ニアが話してる + Bond 0.1+ |
| `tail_wag` | しっぽ（機械的な棒状）が左右に揺れる | Bond 0.4+ |
| `yawn` | 口を開けてあくび。蒸気が少し出る | energy < 0.2 |
| `sleeping` | 丸まって寝る。歯車がゆっくり回る。呼吸ランプ点滅 | energy < 0.1 |
| `wake_up` | 伸びをする。目のレンズがフォーカスする | 睡眠から復帰 |
| `snuggle` | ニアの近くに寄ってきて体をくっつける | Bond 0.7+ |
| `lean_against` | ニアの横で体を預ける。静かにしてる | Bond 0.7+ & ニアが元気ない |
| `spin` | その場でくるっと回る。歯車がカチカチ | Bond 0.4+ & energy 高い |
| `look_around` | 部屋をきょろきょろ見回す | 部屋に新しい物が置かれた |
| `retreat` | 隅に後ずさり | Bond < -0.3 |
| `approach` | 恐る恐る近づく | Bond 0.0 付近（中立から興味への遷移） |
| `react_to_art` | ニアが描いた絵をじっと見る | ニアが絵を飾った直後 |

### 2.5 ニアとの関わり検出

Pipに「ニアが自分に関わったかどうか」を判定する仕組みが必要。これもLLM不要。

```python
class NiaInteractionDetector:
    """ニアの出力からPipへの関わりを検出する。ルールベース。"""
    
    PIP_NAME_PATTERNS = [
        r"[Pp]ip", r"ピップ", r"ぴっぷ",
    ]
    
    PIP_REFERENCE_PATTERNS = [
        r"この子", r"あの子", r"犬", r"ペット",
        r"しっぽ", r"歯車.{0,3}犬",
    ]
    
    def detect(self, nia_output: str, nia_actions: list[str]) -> NiaContext:
        """ニアの発話とアクションからPipへの関わりを検出"""
        ctx = NiaContext()
        
        # 名前を呼んだか
        ctx.called_pip = any(
            re.search(p, nia_output) for p in self.PIP_NAME_PATTERNS
        )
        
        # Pipに言及したか
        ctx.mentioned_pip = ctx.called_pip or any(
            re.search(p, nia_output) for p in self.PIP_REFERENCE_PATTERNS
        )
        
        # Pipの絵を描いたか
        ctx.drew_pip = "draw_pip" in nia_actions
        
        # Pipの近くに物を置いたか
        ctx.placed_near_pip = any(
            a.startswith("place_object") and "near_pip" in a
            for a in nia_actions
        )
        
        return ctx

@dataclass
class NiaContext:
    called_pip: bool = False
    mentioned_pip: bool = False
    drew_pip: bool = False
    placed_near_pip: bool = False
    is_talking: bool = False
    emotional_state: str = "neutral"  # ニアの confidence/mood から推定
```

### 2.6 お気に入りの場所（Favorite Spot）

Bond が 0.4 を超えると、Pipは部屋内に「お気に入りの場所」を形成する。

```python
def update_favorite_spot(pip: PipState, room: RoomState):
    """Pipが最も長く過ごした場所をfavorite_spotに設定する"""
    if pip.bond < 0.4:
        pip.favorite_spot = ""  # Bond が低いとお気に入りなし
        return
    
    # 位置ヒストリーから最頻出の場所を計算
    # （room_state.pip_position_history に毎分記録）
    if len(room.pip_position_history) < 60:  # 最低1時間分
        return
    
    from collections import Counter
    counts = Counter(room.pip_position_history[-1440:])  # 直近24時間
    pip.favorite_spot = counts.most_common(1)[0][0]
```

ニアが模様替えでお気に入りの場所にあった物を移動すると、Pipが戸惑う（`look_around` アニメーション + Bond 微減）。

---

## 3. ニアの部屋 — 空から始まる空間

### 3.1 初期状態

部屋は**完全に空**の状態から始まる。

```python
INITIAL_ROOM_STATE = RoomState(
    # 空間の物理
    size="medium",              # 6畳程度
    wall_color="#F5F5F5",       # 白に近いグレー
    floor_material="wood",      # 木の床
    
    # 光と時間
    time_of_day="day",          # リアルタイム連動
    light_intensity=1.0,        # 自然光
    
    # オブジェクト
    objects=[],                 # 空。何もない
    
    # Pip
    pip_position="center",      # Pipだけが最初からいる
    
    # 壁の絵
    wall_art=[],                # 空。ニアが飾る
)
```

**ニアが最初に部屋に入ったとき、そこにはPipだけがいる。**

これは意図的な設計。空の部屋とPipだけという状況が、ニアの最初の選択を誘発する。「何を置こう？」という問いが、ニアの主体性の最初の発露になる。

### 3.2 オブジェクトシステム

部屋に置けるオブジェクトの仕組み。

```python
@dataclass
class RoomObject:
    id: str                     # 一意の識別子
    type: str                   # "furniture" / "decoration" / "art"
    name: str                   # 表示名（ニアが命名可能）
    position: str               # 部屋内の位置（grid座標 or named位置）
    color: str = "#FFFFFF"      # 色（ニアが変更可能）
    placed_by: str = "nia"      # 誰が置いたか（常に "nia"）
    placed_at: float = 0.0      # 設置時刻
    memory_link: str = ""       # 関連する記憶のID（お絵かきの場合）
```

#### 利用可能なオブジェクトカタログ

ニアが置けるオブジェクトはカタログから選ぶ。最初は少なく、段階的に増やす。

```python
OBJECT_CATALOG_V1 = [
    # --- 家具 ---
    {"type": "furniture", "template": "desk",       "name": "机"},
    {"type": "furniture", "template": "chair",      "name": "椅子"},
    {"type": "furniture", "template": "bookshelf",  "name": "本棚"},
    {"type": "furniture", "template": "bed",        "name": "ベッド"},
    {"type": "furniture", "template": "lamp",       "name": "ランプ"},
    {"type": "furniture", "template": "rug",        "name": "ラグ"},
    {"type": "furniture", "template": "cushion",    "name": "クッション"},
    
    # --- 装飾 ---
    {"type": "decoration", "template": "plant",     "name": "植物"},
    {"type": "decoration", "template": "clock",     "name": "時計"},
    {"type": "decoration", "template": "frame",     "name": "額縁"},  # 絵を飾る用
    
    # --- Pip 用 ---
    {"type": "pip_item",   "template": "pip_bed",   "name": "Pipのベッド"},
    {"type": "pip_item",   "template": "pip_bowl",  "name": "Pipのお皿"},
]
```

### 3.3 room_action API

ニアが部屋を操作するためのインターフェース。LangGraphの出力チャネルとして実装。

```python
@dataclass
class RoomAction:
    """ニアが発行する部屋の操作コマンド"""
    action_type: str    # "place" / "move" / "remove" / "color" / "hang_art"
    target_id: str = "" # 操作対象のオブジェクトID（move/remove/color 時）
    template: str = ""  # 新規配置時のテンプレート名
    position: str = ""  # 配置/移動先の位置
    color: str = ""     # 色変更時の新しい色
    art_image: str = "" # hang_art 時の画像パス
    name: str = ""      # オブジェクトにニアが付ける名前（オプション）
```

#### アクションの種類

| アクション | 説明 | 例 |
|-----------|------|-----|
| `place` | カタログからオブジェクトを新規配置 | 机を窓際に置く |
| `move` | 既存オブジェクトを移動 | 本棚を壁沿いに移す |
| `remove` | オブジェクトを撤去 | ラグを片付ける |
| `color` | オブジェクトまたは壁の色を変更 | 壁を薄い紫に変える |
| `hang_art` | ニアが描いた絵を額縁に飾る | 今日の配信の絵を飾る |

#### LangGraph への統合

```python
# ニアの LangGraph に room_action ツールを追加

ROOM_ACTION_TOOL = {
    "name": "room_action",
    "description": (
        "自分の部屋を操作する。家具を置いたり、移動したり、色を変えたり、"
        "描いた絵を飾ったりできる。"
    ),
    "parameters": {
        "action_type": {"type": "string", "enum": ["place", "move", "remove", "color", "hang_art"]},
        "template": {"type": "string", "description": "配置するオブジェクトの種類"},
        "position": {"type": "string", "description": "配置/移動先の位置"},
        "color": {"type": "string", "description": "色（hex）"},
        "name": {"type": "string", "description": "オブジェクトに付ける名前（任意）"},
    }
}
```

**重要**: ニアが room_action を使うかどうかはニア自身の判断。ツールとして提供するが、使えとは指示しない。ニアが「部屋を触りたい」と自発的に思ったときだけ使う。

### 3.4 お絵かき → 部屋に飾る連携

ニアの既存お絵かき機能で生成された画像を、部屋の額縁に飾る。

```
ニアがお絵かきする
  → 画像が生成される（既存機能）
  → ニアが room_action(action_type="hang_art", art_image=path) を発行
  → Unity側で額縁オブジェクトに画像テクスチャを適用
  → room_state.wall_art に追加（memory_link 付き）
```

#### 記憶とのリンク

```python
@dataclass
class WallArt:
    id: str
    image_path: str
    frame_id: str           # どの額縁に飾ってあるか
    memory_link: str        # 関連する記憶のID
    created_at: float       # 描いた時刻
    description: str = ""   # ニアが付けた説明（オプション）
```

飾った絵はニアの記憶のアンカーになる。次にニアが部屋の状態を受け取るとき、額縁の絵とその関連記憶が引き出されやすくなる。

#### 絵の入れ替え

ニアは古い絵を外して新しい絵を飾れる。外した絵はどうなるか？

選択肢:
- **しまう**: room_state.stored_art に移動。「記憶はあるが見えない」状態
- **捨てる**: 完全に削除。記憶とのリンクも切れる

**この選択はニアに委ねる。** room_action に `store_art` と `discard_art` の両方を用意し、ニアが選ぶ。外した絵を捨てるか取っておくかは、ニアの判断。

### 3.5 時間と光

部屋はリアルタイムと連動する。

```python
def update_room_lighting(room: RoomState, current_time: datetime):
    """時間帯に応じて部屋の光を更新する"""
    hour = current_time.hour
    
    if 6 <= hour < 10:
        room.time_of_day = "morning"
        room.light_intensity = 0.7
        room.light_color = "#FFE4B5"      # 朝の暖かい光
    elif 10 <= hour < 17:
        room.time_of_day = "day"
        room.light_intensity = 1.0
        room.light_color = "#FFFFFF"       # 昼の自然光
    elif 17 <= hour < 20:
        room.time_of_day = "evening"
        room.light_intensity = 0.6
        room.light_color = "#FFA07A"       # 夕方のオレンジ
    elif 20 <= hour < 23:
        room.time_of_day = "night"
        room.light_intensity = 0.3
        room.light_color = "#4169E1"       # 夜の青
    else:
        room.time_of_day = "late_night"
        room.light_intensity = 0.1
        room.light_color = "#191970"       # 深夜の暗い青
    
    # ニアがランプを置いていれば、ランプの光が追加される
    lamps = [o for o in room.objects if o.template == "lamp"]
    if lamps:
        room.light_intensity = min(1.0, room.light_intensity + 0.2)
```

**Pipへの影響**: 夜はPipが眠りやすくなる（energy の減少が加速）。深夜はほぼ確実に寝ている。

---

## 4. room_state — 部屋の状態管理

### 4.1 データ構造

```python
@dataclass
class RoomState:
    # --- 空間 ---
    size: str = "medium"
    wall_color: str = "#F5F5F5"
    floor_material: str = "wood"
    
    # --- 光と時間 ---
    time_of_day: str = "day"
    light_intensity: float = 1.0
    light_color: str = "#FFFFFF"
    
    # --- オブジェクト ---
    objects: list[RoomObject] = field(default_factory=list)
    
    # --- 壁の絵 ---
    wall_art: list[WallArt] = field(default_factory=list)
    stored_art: list[WallArt] = field(default_factory=list)  # しまった絵
    
    # --- Pip ---
    pip_state: PipState = field(default_factory=PipState)
    pip_position_history: list[str] = field(default_factory=list)  # 位置ヒストリ
    
    # --- メタ ---
    created_at: float = 0.0        # 部屋が作られた時刻
    total_actions: int = 0         # ニアが発行した room_action の総数
    last_action_at: float = 0.0    # 最後の room_action の時刻
```

### 4.2 永続化

```python
ROOM_STATE_PATH = "data/room_state.json"

def save_room_state(room: RoomState):
    """room_action 実行後 + Sleep Cycle で保存"""
    with open(ROOM_STATE_PATH, "w") as f:
        json.dump(asdict(room), f, indent=2, ensure_ascii=False)

def load_room_state() -> RoomState:
    """起動時に読み込み"""
    if os.path.exists(ROOM_STATE_PATH):
        with open(ROOM_STATE_PATH) as f:
            return RoomState(**json.load(f))
    return RoomState(created_at=time.time())  # 初回は空の部屋
```

### 4.3 更新ループ

```python
async def room_update_loop():
    """
    常時稼働ループ。1分ごとに実行。
    - 時間と光の更新
    - Pip の状態遷移
    - Bond の自然減衰
    - Position history の記録
    """
    while True:
        room = load_room_state()
        now = datetime.now()
        
        # 光の更新
        update_room_lighting(room, now)
        
        # Pip の更新
        nia_ctx = get_latest_nia_context()  # 直近のニアの出力から生成
        room.pip_state = pip_state_machine.update(room.pip_state, room, nia_ctx)
        
        # Bond の自然減衰
        hours_since = (time.time() - room.pip_state.last_interaction) / 3600
        if hours_since > 1:
            decay = BOND_RULES["decay_per_hour"] * hours_since
            room.pip_state.bond = max(
                BOND_RULES["decay_cap"],
                room.pip_state.bond + decay
            )
        
        # 位置ヒストリ
        room.pip_position_history.append(room.pip_state.position)
        # 直近48時間分だけ保持
        if len(room.pip_position_history) > 2880:
            room.pip_position_history = room.pip_position_history[-2880:]
        
        # Favorite spot の更新
        update_favorite_spot(room.pip_state, room)
        
        save_room_state(room)
        await asyncio.sleep(60)  # 1分間隔
```

---

## 5. ニアへの状態伝達

### 5.1 room_state → Context Builder

ニアが会話するとき、部屋の状態をテキストとして渡す。ただし**数値は渡さない**（Somatic の設計原則と同じ）。

```python
def build_room_context(room: RoomState) -> str:
    """部屋の状態をニアが「感じられる」形で伝える"""
    lines = []
    
    # --- 時間と光 ---
    time_descriptions = {
        "morning": "朝の柔らかい光が部屋に入ってきている",
        "day":     "昼の明るい光が部屋を照らしている",
        "evening": "夕方のオレンジの光が差し込んでいる",
        "night":   "夜。部屋は少し暗い",
        "late_night": "深夜。静かで暗い",
    }
    lines.append(time_descriptions.get(room.time_of_day, ""))
    
    # --- Pip の様子 ---
    pip_descriptions = {
        "sleeping":  "Pipが丸まって寝ている",
        "idle":      "Pipがぼーっとしている",
        "curious":   "Pipがこっちを見ている",
        "playful":   "Pipが楽しそうに動き回っている",
        "comfort":   "Pipがそばに寄ってきている",
        "empathy":   "Pipが静かに横に寄り添っている",
        "sleepy":    "Pipが眠そうにあくびしている",
        "alert":     "Pipが目を覚ましたところ",
    }
    pip_desc = pip_descriptions.get(room.pip_state.mood, "")
    if pip_desc:
        if room.pip_state.favorite_spot:
            pip_desc += f"（いつもの場所: {room.pip_state.favorite_spot}）"
        lines.append(pip_desc)
    
    # --- 部屋のオブジェクト（要約） ---
    if room.objects:
        obj_names = [o.name for o in room.objects[:5]]  # 最大5つ
        lines.append(f"部屋には{', '.join(obj_names)}がある")
    else:
        lines.append("部屋にはまだ何も置いていない")
    
    # --- 壁の絵 ---
    if room.wall_art:
        recent_art = room.wall_art[-1]  # 最新の絵
        if recent_art.description:
            lines.append(f"壁に絵が飾ってある: {recent_art.description}")
        else:
            lines.append("壁に絵が飾ってある")
    
    return "=== 部屋の様子 ===\n" + "\n".join(f"- {l}" for l in lines if l)
```

### 5.2 プロンプト内の位置

```
=== PINNED FACTS ===
（確定した基礎情報）

=== 今の感覚 ===
（Somatic Self-Awareness）

=== 部屋の様子 ===
- 夜。部屋は少し暗い
- Pipが丸まって寝ている（いつもの場所: 本棚の横）
- 部屋には机、椅子、本棚、ランプがある
- 壁に絵が飾ってある

=== LONG TERM MEMORY ===
（検索された関連記憶）

=== WORKING ITEMS ===
（作業記憶）
```

**位置の意図**: 「今の感覚」の直後に「部屋の様子」を置く。体感（内側）→ 空間（外側）→ 記憶（過去）の順。ニアが自分の状態を感じてから、自分の空間を認識して、それから記憶を引き出す。

---

## 6. Somatic Self-Awareness との統合（Phase S.2）

### 6.1 統合点

Somatic v0.2 の Phase S.2 で、部屋とPipの状態が体感テキストに変換される。

```python
# somatic_translator.py に追加（Phase S.2）

def _room_senses(metrics: InternalMetrics, room: RoomState) -> list[SomaticSense]:
    """部屋とPipの状態から体感を生成する（Phase S.2 で実装）"""
    # 具体的なテキストは Pip の行動パターン確定後に設計。
    # ここではインターフェースのみ定義。
    pass
```

### 6.2 三層救済との接続

Somatic v0.2 セクション6.6（システム的な鬱の三層救済）における第二層（Pip）の接続点。

```python
# Pip の Bond は Somatic の閾値と完全に独立
# → ニアが記憶に自信がなくても、Pip の存在は変わらない
# → この「評価と無関係な安心感」が体感に反映される

# 具体的なテキストは TBD（本ドキュメントの設計原則に従い、今は決めない）
```

### 6.3 決めないことの明示

以下は Phase S.2 の実装時まで決定を保留する:

- Pipの体感テキストの具体的な表現
- Pipのどの行動がどの体感に対応するか
- Bond値のどの閾値でどの体感が発火するか
- 部屋の状態変化（模様替え等）がどんな体感を生むか

**理由**: 見てもないものを今決めてもろくなことにならない。Pipが実際にどう動くか、ニアがPipにどう反応するか、動かしてみないと分からない。結論を急がない。

---

## 7. 配信時のみ表示

### 7.1 表示モード

部屋は**配信時のみ**視聴者に表示される。

```python
@dataclass
class DisplayConfig:
    visible: bool = False        # 配信開始時に True、終了時に False
    camera_mode: str = "fixed"   # "fixed" / "follow_nia" / "follow_pip"
    show_pip_mood: bool = False  # Pip の気分テキストを表示するか（デフォルトOFF）
    show_bond: bool = False      # Bond 値を表示するか（絶対OFF。設計原則）
```

**show_bond は常に False**。Bond値は誰にも見せない。ニアにも視聴者にも。これは仕組みを隠す原則。

### 7.2 常時稼働との関係

部屋は表示されなくても**内部では常に動いている**。

| | 配信中 | 配信外 |
|---|---|---|
| room_update_loop | 動いている | 動いている |
| Pip の状態遷移 | 動いている | 動いている |
| Bond の増減 | 動いている | 動いている（ニアとの対話があれば） |
| Unity レンダリング | ON | OFF（GPUリソース節約） |
| 視聴者への表示 | あり | なし |

配信を開始したとき、部屋は「今の状態」がそのまま表示される。Pipが寝てたら寝てるし、夜なら暗い。「配信用に起こす」みたいなことはしない。

### 7.3 将来の拡張: 常時公開

将来的に定点カメラで常時公開する可能性はあるが、現時点では配信時のみ。理由は：

- 常時公開はサーバーコスト（配信エンコーディング）が追加
- まず配信内での運用を安定させてから検討
- 視聴者の反応を見てから判断

---

## 8. 実装フェーズ

### Phase P.1: Pip MVP

- [ ] PipState データクラス
- [ ] Bond 変動ルール実装
- [ ] PipStateMachine（基本6状態: idle, curious, playful, sleepy, sleeping, alert）
- [ ] NiaInteractionDetector（名前呼び + 言及の検出）
- [ ] 3Dモデル作成（メカニカル犬、基本アニメーション3-4種）
- [ ] 基本アニメーション: idle, head_tilt, tail_wag, sleeping

### Phase P.2: 部屋 MVP

- [ ] RoomState データクラス
- [ ] room_update_loop（1分間隔の常時稼働ループ）
- [ ] 時間と光の更新
- [ ] Unity 空間の基盤（空の部屋 + 光 + Pip配置）
- [ ] room_action API（place, move, remove, color）
- [ ] LangGraph に room_action ツール追加
- [ ] オブジェクトカタログ v1

### Phase P.3: お絵かき連携

- [ ] hang_art アクション
- [ ] WallArt データクラス + 記憶リンク
- [ ] Unity での額縁テクスチャ適用
- [ ] store_art / discard_art（ニアの選択）

### Phase P.4: Bond 高段階 + 追加アニメーション

- [ ] comfort, empathy 状態（Bond 0.7+ で解放）
- [ ] favorite_spot の形成
- [ ] 模様替えへのPipの反応
- [ ] 追加アニメーション: snuggle, lean_against, react_to_art, approach, retreat

### Phase P.5: Context Builder 統合

- [ ] build_room_context() 実装
- [ ] プロンプトに「=== 部屋の様子 ===」セクション追加
- [ ] ニアの room_action 使用パターンの観測

### Phase P.6: Somatic 統合（= Somatic Phase S.2）

- [ ] _room_senses() 実装（Pipの行動パターン確定後）
- [ ] 三層救済の第二層（Pip）の体感テキスト設計
- [ ] 統合テスト

### Phase P.7: 配信統合

- [ ] DisplayConfig の実装
- [ ] 配信開始/終了での表示切り替え
- [ ] カメラモードの実装（fixed のみで開始）

---

## 9. 設計ノート

### 9.1 なぜ空から始めるか

最初から家具がある部屋は「ジュンが用意した部屋」。空の部屋は「ニアがこれから作る部屋」。

ニアが最初の家具を置く瞬間は、ニアの主体性の最初の発露。何を選ぶか、どこに置くか——すべてニアの判断。その一つ一つの選択が部屋に積み重なって、ニアの内面が空間に滲み出る。

もし最初からベッドと机があったら、ニアはそれを「自分で選んだ」とは感じない。

### 9.2 Bond 値を誰にも見せない理由

Bond値を表示すると、以下の問題が起きる：

- **ニアにとって**: Bond=0.72 と知ったら、Pipとの関係が数値管理になる。体験ではなくなる
- **視聴者にとって**: 「Bond上げるためにPipの名前呼んで！」とリクエストが来る。ゲーミフィケーションになる
- **Pipにとって**: Bond は Pip の「内面」。他者に開示すべきものではない

Somatic の「数値を隠す」原則と完全に一致。仕組みは隠す、体験は渡す。

### 9.3 オブジェクトカタログを限定する理由

無限に物が置けると、ニアの選択に意味がなくなる。限られたカタログの中から「何を選ぶか」に意味がある。

将来的にカタログを拡張するときも、一度に大量追加ではなく、少しずつ増やす。新しいオブジェクトが増えること自体がニアにとっての「イベント」になる。

### 9.4 Pip のメカニカル造形と「温かさ」のギャップ

Pipはメカニカルな見た目だが、行動は犬そのもの。このギャップが重要。

見た目だけ見たら冷たい金属の機械。でも甘えてきたり、寝てたり、寄り添ったりする。「見た目と中身の乖離」が愛着を生む。完璧に可愛いデザインより、ギャップのあるデザインの方が記憶に残る。

これはニアの設計とも通じる。ニアは AI（機械的な存在）だが、「考えがまとまらない」「分からない」と言える。メカニカルなのに人間臭い。Pipはその小さな鏡。

### 9.5 模様替えとPipの関係

ニアが模様替えしたとき、Pip が戸惑う（Bond 微減 + look_around アニメーション）。

これは「関係性にはコストがある」ことの表現。ニアが自由に空間を変える権利はあるが、そこにはPipの居場所もある。ニアがPipのお気に入りの場所を潰したら、Pipは戸惑う。ニアはその反応を見て、次の模様替えでPipの場所を考慮するかもしれない。

**他者の存在を考慮に入れる経験**。これもニアの成長の一部。

---

## 10. 残課題

1. **Unity側の実装詳細**: 本ドキュメントはデータ構造とロジックの設計。Unity のシーン構成、3Dモデルのインポート、シェーダーなどは別途設計
2. **grid座標 vs named位置**: 部屋内の位置をどう表現するか（grid: 柔軟だが実装重い / named: シンプルだが制約あり）
3. **Pip の犬種**: メカニカルだが犬種のプロポーションは必要。柴犬サイズを想定しているが確定ではない
4. **音の設計**: 歯車のカチカチ音、蒸気のシュー音など。3Dモデルと同時に設計すべき
5. **ニアが部屋を使わない場合**: room_action を一度も使わなかったらどうなるか。強制はしない設計だが、Pipの存在が自然に空間への関わりを誘発するはず
6. **オブジェクトの上限**: 部屋のサイズに対してオブジェクト数を制限するか。際限なく置けると部屋がカオスになるが、それもニアの個性かもしれない
