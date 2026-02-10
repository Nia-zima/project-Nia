# ライブ配信機能 設計ドキュメント

## Version 0.1 – Draft

---

## 1. 概要

### 目的
ニアが複数の視聴者からのコメントに応答し、配信者（オリジン）と共に配信を行う機能。

### Body Constitutionとの整合

| 条文 | 配信での適用 |
|------|-------------|
| B.4 観測の主導権 | **ニアがコメントを選ぶ**。全部に反応しない |
| B.5 思考の独立性 | 誘導コメントは `steering_risk` で検出・除外 |
| B.6 沈黙の権利 | 適切なコメントがなければ沈黙してよい |
| B.8 結論圧への抵抗 | 「診断して」等の要求には Depth0 で境界を示す |

### 設計決定

#### Q1: Guest識別 → セッション内追跡
- 配信中は同一視聴者を追跡（会話の連続性）
- 配信終了で全リセット（プライバシー保護）
- クロスセッション追跡はしない（C.11「記憶の明示禁止」との整合）

#### Q2: オリジン特権 → 割り込み権 + 記憶優先度
```python
class UserRole(Enum):
    ORIGIN = "origin"   # 割り込み可、retention +0.2
    VIEWER = "viewer"   # 一般視聴者
```

#### Q3: 記憶混濁対策 → 自動推論 + 低retention雑談
- `addressed_to` は自動推論（「@ニア」「ニアちゃん」等を検出）
- 雑談（短文 + 低steering_risk）は `retention = 0.3` で保存
- 重要な雑談は繰り返し言及されれば `retention` 上昇

#### B.4 観測の主導権 → レート制限 + スキップ権

| パラメータ | 値 | 説明 |
|-----------|-----|------|
| 処理レート | **4件/分** | 15秒間隔でゆっくり処理 |
| 候補ウィンドウ | 5件 | 直近5件から選択 |
| キュー最大age | 60秒 | 古すぎるコメントは破棄 |
| オリジン優先 | 常に最優先 | 割り込み権 |

**スキップ権（沈黙を選ぶ条件）:**
- 全コメントの `steering_risk > 0.6` → 全スキップ
- 全コメントの `info_sufficiency < 0.3` → 全スキップ

---

### 2.1 複数ユーザーからの入力処理

```
視聴者コメント
    ↓
コメントキュー (先入れ先出し)
    ↓
フィルタリング (steering_risk, 長さ, 重複)
    ↓
ニアが「選ぶ」(選択ロジック)
    ↓
応答生成 → 音声 → 配信
```

**フィルタリング基準:**
- `steering_risk > 0.7` → 除外（誘導リスク）
- 文字数 < 5 or > 200 → 除外
- 直近10件と90%以上類似 → 除外（重複）

**選択ロジック:**
- キューから最大5件を候補に
- `info_sufficiency` が高いものを優先
- ランダム要素を入れて固定化を防ぐ

### 2.2 Diagnosticsダッシュボード

#### エンドポイント: `GET /api/diagnostics`

```json
{
  "timestamp": 1706968800,
  "thread_id": "live_stream",
  "scalars": {
    "steering_risk": 0.45,
    "info_sufficiency": 0.82,
    "question_clarity": 0.71
  },
  "depth": {
    "current": 1,
    "reason": "B.5: 思考の独立性"
  },
  "queue": {
    "pending": 12,
    "processed_last_minute": 8,
    "rejected_last_minute": 3
  },
  "memory": {
    "pending": 3,
    "approved_today": 12
  }
}
```

#### フロントエンド表示

```
┌─────────────────────────────────────────┐
│ 🟢 LIVE                                 │
├─────────────────────────────────────────┤
│ 3スカラー                                │
│ ├── steering_risk:   ███░░░░ 0.45       │
│ ├── info_sufficiency: ██████░ 0.82      │
│ └── question_clarity: █████░░ 0.71      │
├─────────────────────────────────────────┤
│ Depth: 1 (整理モード)                    │
├─────────────────────────────────────────┤
│ キュー: 12件待ち | 処理: 8/分 | 除外: 3  │
│ 記憶: 保留3件 | 今日了承12件             │
└─────────────────────────────────────────┘
```

### 2.3 記憶の可視化

#### エンドポイント: `GET /api/memory/timeline`

```json
{
  "timeline": [
    {
      "id": "mem_001",
      "created_at": 1706968000,
      "summary": "視聴者Aが猫の話題を出した",
      "retention": 0.85,
      "grounded": true,
      "tags": ["kw:猫", "emotion:neutral"]
    }
  ]
}
```

---

## 3. 既存実装の活用

### 使える部分

| コンポーネント | ファイル | 活用方法 |
|---------------|----------|----------|
| `/livestream_chat` | stream_router.py | 拡張してキュー対応 |
| `stream_sse` | agent_orchestrator.py | そのまま使用 |
| `SteeringRiskCalculator` | metrics.py | フィルタリングに使用 |
| `MemoryExplorer` | frontend | 簡素化して配信用に |

### 新規開発が必要

| コンポーネント | 優先度 | 見積もり |
|---------------|--------|----------|
| コメントキュー | 高 | 2-3時間 |
| `/api/diagnostics` | 中 | 1-2時間 |
| `/api/memory/timeline` | 低 | 1時間 |
| 配信用フロントエンド | 中 | 3-4時間 |

---

## 4. API設計

### 4.1 コメント投稿

```
POST /api/livestream/comment
{
  "text": "こんにちは！猫飼ってますか？",
  "user_id": "viewer_123",
  "user_name": "猫好き太郎",
  "timestamp": 1706968800
}
```

**レスポンス:**
```json
{
  "ok": true,
  "queued": true,
  "queue_position": 5,
  "estimated_wait_seconds": 30
}
```

### 4.2 次のコメント取得（配信側）

```
GET /api/livestream/next
```

**レスポンス:**
```json
{
  "comment": {
    "text": "こんにちは！猫飼ってますか？",
    "user_name": "猫好き太郎",
    "steering_risk": 0.15,
    "selected_reason": "info_sufficiency高"
  },
  "queue_remaining": 4
}
```

### 4.3 応答送信

```
POST /api/livestream/respond
{
  "comment_id": "cmt_001",
  "response_text": "猫は飼ってないかな。でも興味はある。"
}
```

---

## 5. 注意事項

### セキュリティ
- レート制限: 1ユーザー10コメント/分
- 禁止ワードフィルター
- ユーザーブロック機能

### プライバシー
- 記憶の可視化時、個人情報をマスク
- 配信終了後、コメントキューをクリア

### パフォーマンス
- キューは最大100件（超えたら古いものを破棄）
- Diagnosticsは5秒間隔でポーリング

---

## 6. 実装ロードマップ

### Phase 1: 基盤（今週）
- [ ] コメントキューの実装
- [ ] `/api/diagnostics` エンドポイント
- [ ] 既存 `/livestream_chat` の拡張

### Phase 2: フロントエンド（来週）
- [ ] Diagnosticsダッシュボード
- [ ] 記憶タイムライン
- [ ] 配信用シンプルUI

### Phase 3: 統合テスト
- [ ] 複数視聴者シミュレーション
- [ ] 負荷テスト
- [ ] Body Constitution違反チェック

---

## 変更履歴

- **v0.1**: 初版ドラフト作成
