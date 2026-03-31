# Session Handoff

> 目的: 次のセッションが「今どこで止まっているか」だけを最短で掴むためのメモ。
> 更新日: 2026-03-31

---

## 関連入口

- `README.md`:
  リポジトリ全体の概要と機能面の入口
- `ABOUT_NIA.md`:
  ニアの思想・存在像の説明
- `docs/nia_core_summary.md`:
  core 系の詳細まとめ
- `docs/assistant_context.md`:
  別 AI / 新規セッション向けの復元入口

---

## 現在の停止位置

- **Phase 1 closed**
  - SK-2 `correction_resilience`: score `0.658`, L2 到達見込み ~2日（day_span=5/7）
  - `contradiction_hold` live 統合済みだが発火 0 回（正常 — hold 条件を満たすイベントが未発生）
  - RuntimeFacts Phase A: ブロッカーなし完了
- **Phase 2 started: Skeleton Realizer C.0 shadow**
  - 実装完了（40テスト通過）
  - `SKELETON_GUIDANCE_SHADOW_ENABLED=true` で稼働開始
  - 最初の 3 shadow レコード観測済み:
    - `ask` mode の adherence = low
    - `reflect` mode の adherence = high（composite 1.0）
  - 最初の非対称性: ask < reflect
  - まだ観測フェーズ。データ蓄積中
- **モデル**: `qwen/qwen3.5-9b` 確定
- **Drawing intent path**:
  - `DRAWING_INTENT_ONLY=true` で **intent YAML live success を 1 回確認**
  - 2-pass normalize + `upper_center` alias + `cool_fading` 正式追加で、malformed intent の通過率が改善
  - raw draw 漏れ / legacy reject replay / historical draw mimic は修正済み
- **統合順序の正本**: `docs/nia_integration_roadmap.md`

---

## 直近の事実

- Phase 1（Metabolic Hardening Phase 4.6 + RuntimeFacts Phase A + contradiction_hold）を閉じた
- Skeleton Realizer C.0 shadow を実装し、shadow 記録を開始した
- 最初の観測結果: ask mode は adherence が低い、reflect mode は高い
- まだ数レコードなので分布判断は早い。depth/focus/turn_role 別の分布を見る必要がある
- Drawing intent path は live で 1 回成功した。残る主論点は truncation 系の安定化
- `METABOLIC_KNOT_ENABLED=true`、`ADAPTATION_RECORD_ENABLED=true`、`SKELETON_GUIDANCE_SHADOW_ENABLED=true` 有効

---

## 次の一手

1. **C.0 shadow データ蓄積** — ask/low の分布を depth/focus/turn_role 別に確認する
2. **SK-2 の L2 到達を確認** — ~2日後に L2 判定の見込み
3. **adherence パターン分析** — ask mode の低 adherence が構造的か文脈依存かを見極める
4. **knot→training candidate** — 設計書完了済み、C.0 shadow のデータが十分になったら実装
5. Drawing は canonicalizer 観測継続
6. Drawing/Skeleton cleanup を忘れない:
   - `last_drawing_ts:{thread_id}` の作用範囲を短くする（10分は広すぎる。one-shot / short TTL を再設計）
   - Skeleton adherence 集計から `timeout_fallback` 系 turn を除外できるように origin 記録を追加する

## 作業原則

- 新しい自己形成系の設計は、最初から既存 schema や人間が先に決めた分類へ無理に閉じない
- まず大胆に設計を広げる
- 次に backup / feature gate / shadow mode を前提に、可逆な実験単位へ切る
- 最後に、観測で意味が確認できたものだけ本線へ統合する

---

## すぐ見るファイル

- `docs/nia_integration_roadmap.md` — 統合順序の正本
- `docs/skeleton_realizer_design.md` — Skeleton Realizer 設計書
- `docs/knot_to_niacore.md` — knot→NiaCore 学習信号設計書
- `docs/metabolic_hardening_design.md` — knot-first 設計書と Step 0 結果
- `backend/services/identity/schema.py` — MetabolicKnot 系 Pydantic schema
- `backend/services/identity/knot_store.py` — 7テーブル DDL + CRUD + `summarize_knot`
- `backend/services/identity/hardness_engine.py` — type 別 signal / protection / hardness
- `backend/services/identity/contradiction_hold.py` — hold detection / review / resolution
- `backend/services/adaptation/` — schema, writer, reader, signal_detector, proposal_generator
- `backend/core/drawing/` — dual ingress adapter / parser / scene graph / renderer / trace
- `docs/nia_drawing_language.md` — Drawing Language 正本
- `docs/failure_success_policy_design.md` — adaptation 設計書
- `docs/decision_log.md`

---

## すぐ使う確認コマンド

```powershell
.\.venv\Scripts\python -m backend.scripts.report_gate_status
```

```powershell
rg -n "SKELETON_GUIDANCE_SHADOW|adherence|mode_adherence" logs/app.log
```

```powershell
rg -n "KNOT_EXTRACT|KNOT_DISTILL|baseline=|changed hardness" logs/app.log
```

---

## 非 issue

- VoiceVox 未起動時の `Connection Failed` は本文生成経路の失敗ではない
- `review_used=False` 固定は暫定ではなく、現時点では意図した未配線扱い
- trace_match 系は runtime scorer では意図的に無効化（Phase E 用に schema のみ保持）
- Drawing Language はまだ独立チャネルで、core runtime / metabolic extractor には未接続
- `contradiction_hold` の発火 0 回は正常（hold 条件を満たすイベントがまだない）
