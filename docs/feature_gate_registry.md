# Feature Gate Registry

> **目的:** 全 feature gate の現在値・段階・卒業条件・rollback 条件・未配線項目を一箇所で管理する。
> **更新タイミング:** gate の stage 変更時、新規 gate 追加時、卒業条件の達成/変更時。

---

## Gate 一覧

### NiaCore v1（Liquid Neural Network）

| Gate | Default | 現在値 | Stage | 関連テーブル |
|------|---------|--------|-------|-------------|
| `NIACORE_EXPERIENCE_ENABLED` | `false` | `true` | **record-only** | `niacore_experience` |
| `NIACORE_SHADOW_ENABLED` | `false` | `true` | **shadow** | `niacore_experience` (shadow_result) |
| `NIACORE_TRAINING_ENABLED` | `false` | `false` | off | `niacore_experience` (reward 計算) |

**依存関係:** TRAINING → SHADOW → EXPERIENCE（逆方向で依存）

**卒業条件（TRAINING 有効化）:**
- Shadow 期間 ≥ 30 日（開始: 2026-03-06 → 最短 2026-04-05）
- 蓄積ターン ≥ 500
- ルールベース一致率 ≥ 85%
- 逸脱後成功率 ≥ 60%（`outcome_known=true` のみ）
- 全 Depth 選択率 ≥ 5%（Mode Collapse 検出）

**Rollback 条件:** `health.py` の L0/L1/L2 レベル（6指標×3ウィンドウ）
**設計書:** `docs/niacore_lnn_design.md` §5.2

---

### NiaCore vNext（多ヘッド拡張）

| Gate | Default | 現在値 | Stage | 関連テーブル |
|------|---------|--------|-------|-------------|
| `NIACORE_VNEXT_SHADOW_ENABLED` | `false` | `true` | **shadow** | `niacore_vnext_shadow` |

**依存関係:** `NIACORE_EXPERIENCE_ENABLED=true`（soft: `SKELETON_RECORD_ENABLED` 推奨）

**卒業条件（Phase N1 移行）:**
- Phase N0 データ蓄積（attention_target / recommended_action 分布の安定）
- StateVectorV2 の feature_availability が十分な配線率

**Rollback 条件:** fire-and-forget のため、off にするだけで影響なし
**設計書:** `docs/niacore_vnext_design.md`

---

### SkeletonCore（会話骨格）

| Gate | Default | 現在値 | Stage | 関連テーブル |
|------|---------|--------|-------|-------------|
| `SKELETON_RECORD_ENABLED` | `false` | `true` | **record-only** | `conversation_skeletons` |
| `SKELETON_SOMATIC_ENABLED` | `false` | `false` | off | 同上（読み取り → LLM 注入） |

**依存関係:** SOMATIC → RECORD

**卒業条件（SOMATIC 有効化）:**
- Record-Only で ~500 ターン蓄積
- ラベル分布の安定確認

**Rollback 条件:**
- 迎合傾向の増加
- Depth0 の立ち止まり品質低下

**設計書:** `docs/skeletoncore_design.md` §9

---

### Memory Governance

| Gate | Default | 現在値 | Stage | 関連テーブル |
|------|---------|--------|-------|-------------|
| `GOVERNANCE_OBSERVE_ENABLED` | `false` | `true` | **record-only** | `governance_events` |
| `GOVERNANCE_CANDIDATE_ENABLED` | `false` | `true` | **canary** | `raw_promotion_candidates` |
| `GOVERNANCE_EVIDENCE_ENABLED` | `false` | `true` | **canary** | `memory_evidence` |

**依存関係:** EVIDENCE → CANDIDATE → OBSERVE（逆方向で依存）

**卒業条件（Phase B 移行）:**
- H1-H6 ルールが自然会話で安定的に発火
- candidate 品質の確認
- evidence 蓄積の分布が妥当

**Rollback 条件:** 全 gate off で記録停止。既存データは残る
**設計書:** `docs/governance_phase_a_status_2026-03-11.md`

---

### Temporal Somatic Contrast

| Gate | Default | 現在値 | Stage | 関連テーブル |
|------|---------|--------|-------|-------------|
| `FINGERPRINT_RECORD_ENABLED` | `false` | `true` | **record-only** | `turn_fingerprints` |

**卒業条件（TS.1 Contrast Engine 移行）:**
- 500+ fingerprint 蓄積

**設計書:** `docs/temporal_somatic_contrast_design.md`

---

### Expression Layer

| Gate | Default | 現在値 | Stage | 関連テーブル |
|------|---------|--------|-------|-------------|
| `EXPRESSION_RECORD_ENABLED` | `false` | `true` | **record-only** | `expression_observations` |

**卒業条件（E0.5 パターン分析 移行）:**
- E0 データ蓄積（fingerprint との共起分析に十分な量）
- 特徴量分布の安定

**設計書:** `docs/nia_expression_layer_design.md`

---

### Metabolic Hardening

| Gate | Default | 現在値 | Stage | 関連テーブル |
|------|---------|--------|-------|-------------|
| `METABOLIC_KNOT_ENABLED` | `false` | `true` | **canary** | `metabolic_knots`, `knot_activations`, `knot_baselines`, `knot_signal_history`, `perturbation_episodes`, `knot_relations` |

**依存関係:** `EXPRESSION_RECORD_ENABLED=true`, `SKELETON_RECORD_ENABLED=true`, `NIACORE_EXPERIENCE_ENABLED=true`

**卒業条件（Step 4 以降へ進む条件）:**
- 2-3 回の Sleep で `baseline_version` が自然に更新される
- `activation_count` が重複実行で膨張しない
- `day_span` / `temporal_stability` が自然に立ち上がる
- 意図しない L1 昇格や hardness 発振が起きない
- `docs/metabolic_hardening_design.md` §18b の Known Limitations を把握した上で観測が継続できる

**Rollback 条件:** `METABOLIC_KNOT_ENABLED=false` で Phase 4.5 停止。既存データは残る  
**設計書:** `docs/metabolic_hardening_design.md`

---

### Pip / Room / Contract 1-3

| Gate | Default | 現在値 | Stage | 関連ストア |
|------|---------|--------|-------|-----------|
| `PIP_ENABLED` | `false` | 未設定 | **complete** | `telemetry_kv`（pip_bond, pip_state 等） |
| `ROOM_UPDATE_ENABLED` | `false` | 未設定 | **complete** | `data/room_state.json`, `telemetry_kv` |
| `RUNTIME_FACTS_ENABLED` | `false` | `true` | **live**（Phase A 観測中） | LLM context 注入のみ |
| `ATMOSPHERE_ENABLED` | `false` | `false` | off (Phase B 候補) | LLM context 注入のみ |

**依存関係:** ATMOSPHERE → RUNTIME_FACTS（Phase A 観測後に Phase B）

**次段条件（Phase A 観測完了 / Phase B 判定）:**
- RuntimeFacts 導入で説明臭さや過剰即答化が増えない
- WAIT や立ち止まり品質を壊さない
- Atmosphere を重ねてもよいだけの安定観測が取れる

**設計書:** `docs/pip_room_temporal_livestream_integration.md`

---

### 常時有効（デフォルト on）

| Gate | Default | カテゴリ |
|------|---------|---------|
| `AWARENESS_CORE_ENABLED` | `true` | メタ認知 N.0 |
| `METACOG_ENABLED` | `true` | メタ認知 N.1 |
| `CONTRADICTION_SCAN_ENABLED` | `true` | メタ認知 N.2 |
| `SELF_MODEL_ENABLED` | `true` | メタ認知 N.3 |
| `STATE_TRIGGER_ENABLED` | `true` | メタ認知 N.4 |
| `SELF_NARRATIVE_ENABLED` | `true` | メタ認知 N.5 |
| `SOMATIC_ENABLED` | `true` | 体感 S.1a/S.1b |
| `SOMATIC_FEEDBACK_ENABLED` | `true` | 体感 S.1b |
| `RETRIEVAL_ENABLED` | `true` | 記憶 M.1-M.3 |
| `RETRIEVAL_LOG_ENABLED` | `true` | 観測 |
| `IDLE_DETECTION_ENABLED` | `true` | 振り返り R.1 |
| `ORCHESTRATOR_S5_ENABLED` | `true` | S5 Commit |
| `SAFETY_GATE_ENABLED` | `true` | 安全 |
| `GUARDRAIL_V2_ENABLED` | `true` | 安全 v2 |

これらは「止めると基本機能が壊れる」ものなので、緊急停止以外で off にしない。

---

### その他

| Gate | Default | 現在値 | 用途 |
|------|---------|--------|------|
| `SOMATIC_ADAPTIVE_ENABLED` | `false` | 未設定 | 適応的閾値（S.1.5 拡張） |
| `EXTERNAL_DATA_ENABLED` | `false` | `true` | 外部検索 |
| `LEGACY_MEMORY_READ_ONLY` | `false` | `true` | 旧記憶互換 |
| `LEGACY_MEMORY_TABLES_ENABLED` | `false` | `false` | 旧テーブル |
| `DSPY_MODE` | `"disabled"` | 未設定 | DSPy（無効） |
| `EXPERIMENT_MODE` | `false` | 未設定 | 実験モード |

---

## Stage 定義

| Stage | 意味 | 実行パスへの影響 |
|-------|------|----------------|
| **off** | 無効。コードは存在するが一切実行されない | なし |
| **record-only** | DB に記録するが、制御フローに影響しない | なし（fire-and-forget） |
| **shadow** | ルールベースと並行推論し、結果を記録。制御は変えない | なし |
| **canary** | 本番データで動作するが、結果は参考値。段階的に信頼を積む | なし |
| **live** | 本番稼働。制御フローに影響する | あり |
| **complete** | 実装完了・安定稼働。gate 自体が不要になりつつある | あり |

---

## 次の有効化候補（優先順）

1. **SKELETON_SOMATIC_ENABLED** — Record-Only 観測後（~500 ターン）
2. **ATMOSPHERE_ENABLED** — RuntimeFacts Phase A 観測後
3. **NIACORE_TRAINING_ENABLED** — Shadow 30 日後（~2026-04-05）
