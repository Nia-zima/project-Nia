# Decision Log

> 目的: 「なぜこうしたか」を短く残す。詳細仕様は各設計書を正とする。

---

## 2026-03-18

### 1. `review_used` は未配線扱いで `False` 固定

- 判断:
  - `_detect_review_used()` は削除
  - `review_used` は固定値で保存
- 理由:
  - `merge_mode == "B"` は通常 merge でも出る
  - `review_rejected_actions` は turn をまたいで蓄積される
  - 疑似シグナルで誤記録するより、未配線として正直に扱う方が E0 分析を汚さない
- 関連:
  - `backend/core/agent_graph/nodes/commit_helpers.py`
  - `docs/nia_expression_layer_design.md`

### 2. `turn_role` は meeting 専用の小手先ではなく共通概念にする

- 判断:
  - `mirror / deepen / connect / ask / close` を共通 `turn_role` として導入
  - meeting は先行導入プロファイルとする
- 理由:
  - 文面制御より「このターンの役割」を弱く持つ方がニアに合う
  - 後で prompt を薄めても state / merge / core 系に残せる
- 関連:
  - `docs/turn_role_policy.md`
  - `docs/meeting_turn_role_policy.md`

### 3. meeting 品質は hard reject より弱い policy で整える

- 判断:
  - leak / fragment だけを最終ガードに残す
  - `turn_role` は prompt assist + merge ranking で弱く効かせる
- 理由:
  - meeting で hard fallback を強くすると会話が死にやすい
  - ニアには「制限」より「重心の誘導」の方が自然
- 関連:
  - `backend/core/agent_graph/nodes/merge.py`
  - `backend/core/agent_graph/nodes/depth_nodes.py`

### 4. `depth2_reflective` は provider 切替可能に保つ

- 判断:
  - `DEPTH2_PROVIDER=anthropic` で reflective だけ切替
  - `depth2_risk` は local 維持
- 理由:
  - 問題が集中していたのは reflective 側
  - risk 側まで一度に変えると切り分けが雑になる
- 関連:
  - `backend/core/model_adapter.py`
  - `backend/core/agent_graph/nodes/helpers.py`

### 5. token usage はログではなく DB に記録する

- 判断:
  - `llm_usage_records` テーブルを追加
  - `depth0 / depth1 / depth1_fallback / depth2` の usage を per-call で保存
- 理由:
  - コストや傾向は見たい
  - ただし `app.log` をノイズで膨らませたくない
  - meeting 単位・stage 単位であとから集計できる形がほしい
- 関連:
  - `backend/core/llm_usage_writer.py`
  - `backend/core/db_migrations.py`

---

## 2026-03-22

### 6. 閉じた質問への直答は hint ではなく構造で支える

- 判断:
  - `merge_output()` を4段に分割
  - `turn_intent` を導入
  - G6 を intent-aware にし、Somatic を turn_intent で弱化
  - merge scoring を `+4 / -4` に強化
- 理由:
  - 「直答してほしい」を hint だけにすると、既存の文癖や履歴バイアスに負ける
  - 生成前後の複数層で同じ方向を支えた方が安定する
- 関連:
  - `docs/merge_guardrail_reform_plan.md`
  - `backend/core/agent_graph/nodes/merge.py`
  - `backend/core/agent_graph/nodes/routing.py`
  - `backend/services/memory/guardrail.py`

### 7. semantic family は「検出」だけでなく履歴選別に使う

- 判断:
  - `quiet_atmosphere / heart_moves / distance_pause` を semantic family として導入
  - Step 7 では `_recent_history()` の diversity-aware 選択に family を再利用する
- 理由:
  - 完全一致検出だけでは `静かな時間` の言い換え反復を止められない
  - 反復 family は prompt 体感注入だけでなく、LLM に見せる履歴比率の調整にも使うべき
- 関連:
  - `backend/core/agent_graph/nodes/helpers.py`
  - `docs/merge_guardrail_reform_plan.md`

### 8. 履歴の連続性は壊さず、比率だけ変える

- 判断:
  - Step 7 は `Anchor + Scored + chronological restore` を採用
  - `open_reflection` では現行の履歴渡しを維持
  - `direct_answer / correction_response` の時だけ diversity-aware selection を発動
- 理由:
  - 直近の連続性を落とすと会話が壊れる
  - 目的は履歴の削除ではなく、bad in-context example の密度を下げること
  - reflective 会話まで一緒に触ると回帰リスクが高い
- 関連:
  - `backend/core/agent_graph/nodes/helpers.py`
  - `backend/core/agent_graph/nodes/depth_nodes.py`

### 9. direct opener は共有定義で持つ

- 判断:
  - `_DIRECT_OPENERS` に `はい / いいえ / わからない` を追加
  - merge preference と history scoring の両方で同じ direct opener 群を使う
- 理由:
  - `いいえ。` のような最短の直答を direct と認識できないと、Step 4 も Step 7 も穴が残る
- 関連:
  - `backend/core/agent_graph/nodes/merge.py`
  - `backend/core/agent_graph/nodes/helpers.py`

### 10. 残る本命は「履歴の慣性」と「直答の自然な下限」

- 判断:
  - 今回で Step 0〜7 は一旦完了
  - 次の本丸は Step 8（`stance-first + short support`）と観測
- 理由:
  - 新スレッドでは直答率 `100%`
  - `default_thread` でも実測 `25% -> 80%`
  - 残る差分は実装不備より旧履歴の引力と文体の自然さに近い
- 関連:
  - `docs/merge_guardrail_reform_plan.md`

---

## 2026-03-24

### 11. Step 8 は merge rewrite ではなく prompt + warning だけで入れる

- 判断:
  - `depth0/depth1` spine に「立場だけで終わらせず、必要なら短い補足を1文だけ続けてよい」を追加
  - `DIRECT_STANCE_SHORT` warning を追加
  - merge は触らない
- 理由:
  - `いいえ。` のような短すぎる直答は直したい
  - ただし postprocess rewrite で不自然に伸ばすのはニアに合わない
  - warning 観測を先に入れる方が回帰が小さい
- 関連:
  - `backend/core/constants/depth0_prompt_v11.py`
  - `backend/core/constants/depth1_prompt_v11.py`
  - `backend/core/agent_graph/nodes/depth_nodes.py`

### 12. RuntimeFacts は Phase A 観測に進める

- 判断:
  - `RUNTIME_FACTS_ENABLED=true` を有効化
  - まずは Atmosphere を重ねず、Phase A として単独観測する
- 理由:
  - 実装済み機能を本線に弱く接続し、副作用の有無を先に見たい
  - `RuntimeFacts` と `Atmosphere` を同時投入すると原因分離ができない
- 関連:
  - `backend/core/config.py`
  - `docs/feature_gate_registry.md`
  - `docs/nia_integration_roadmap.md`

### 13. 次の本丸は open_reflection の履歴バイアスと failure-to-policy

- 判断:
  - Step 9 (`SkeletonCore RESPOND`) は `DIRECT_STANCE_SHORT` の観測後に判断
  - 別トラックで `open_reflection` への Step 7 拡張と Sleep Cycle failure-to-policy を検討する
- 理由:
  - direct_answer/correction_response は改善したが、自由対話側の履歴慣性は別問題
  - 失敗を記録するだけでなく、次の行動指針へ弱く反映する仕組みが必要
- 関連:
  - `docs/open_reflection_failure_policy_notes.md`
  - `docs/merge_guardrail_reform_plan.md`

### 14. identity.md 承認時の _mark_identity_updated() 接続

- 判断:
  - `identity_router.py` の `approve_proposal()` で identity.md 更新成功後に `_mark_identity_updated()` を呼ぶ
- 理由:
  - proposal 承認で identity.md が更新されても `telemetry_kv` のタイムスタンプが更新されず、`_is_identity_stale()` が常に `True` を返していた
  - 結果として identity.md が 3/4 以降 18日間未更新のまま放置された
- 関連:
  - `backend/controllers/api/identity_router.py`
  - `backend/services/memory/self_model.py`

### 15. failure-to-policy / success-to-preference を対称構造で持つ

- 判断:
  - failure_policy と success_preference を同一テーブルに `proposal_kind` で載せ分ける
  - runtime では `history_bias`（履歴選別の重み）だけ接続。`build_context_suffix()` に policy block を常設しない
  - `teacher_atoms` は将来の NiaCore vNext / Expression Layer 用の構造化痕跡として残す
- 理由:
  - negative pruning だけだと「無難で薄い応答」に寄る（FP.2）
  - prompt に policy を足すほど「ニアがそう振る舞っている」ではなく「プロンプトにそう書いてある」に近づく（FP.1）
  - 同じ source window / replay / scorer を通るので分離する理由がない（FP.15）
- 関連:
  - `docs/failure_success_policy_design.md`
  - `backend/services/adaptation/schema.py`
  - `backend/services/adaptation/writer.py`

### 16. trigger/evidence の判定ロジックを二重化しない

- 判断:
  - open_reflection の trigger 判定と Sleep 側の evidence は、同じ語彙・同じ判定関数を共有する
- 理由:
  - 別実装にすると runtime の trigger 判定と Sleep 側の evidence 判定が微妙にズレる
  - 判定基準の divergence は後から修正困難
- 関連:
  - **実装済み**: runtime trigger は `_SEMANTIC_FAMILIES` + `_detect_semantic_family()` を使用。Sleep 側の signal_detector も同じ辞書を参照
  - `backend/core/agent_graph/nodes/helpers.py`
  - `backend/services/adaptation/signal_detector.py`

### 17. open_reflection の family cap は trigger-based + targeted

- 判断:
  - open_reflection では常時 diversity 選択を入れず、family 反復が検出されたときだけ発火
  - direct bonus は使わない（_score_ai_family_penalty → _make_targeted_family_scorer に進化）
  - 検出された family だけを減点・cap し、他の family は影響しない
  - anchor を 1 に下げて、trigger の原因となった最新ペアも選別対象にする
  - short history (len(pairs) <= max_pairs) でも target_family 指定時は cap を通す
- 理由:
  - 全 family 一律に cap すると reflective 会話の自然な流れを壊す
  - anchor がデフォルトのまま（2ペア）だと trigger 原因の最新ペアがそのまま残り実効性が弱い
  - short history で early return すると trigger が発火しても shaping が入らない
- 関連:
  - `backend/core/agent_graph/nodes/helpers.py`
  - `tests/test_direct_stance.py` — TestOpenReflectionFamilyCap (5テスト)

### 18. Phase B の watermark は source data の最新 timestamp で判定する

- 判断:
  - proposal の `last_seen_at` / `first_seen_at` に `_now_iso()` ではなく source data の最新 `created_at` の ISO 変換を使う
  - writer の merge 時、`last_seen_at` が前進した場合のみ `support_count + 1`
  - `latest_source_ts` を expression / skeleton / correction / family の全ソースで更新
- 理由:
  - `_now_iso()` だと同一 24h 窓の Sleep Cycle 再実行で support が膨張する
  - source data が変わらなければ watermark も変わらない → 再加算を構造的に防止
- 関連:
  - `backend/services/adaptation/signal_detector.py` — `latest_source_ts` フィールド
  - `backend/services/adaptation/proposal_generator.py` — `_ts_to_iso()` + watermark 引数
  - `backend/services/adaptation/writer.py` — `window_advanced` 判定

---

## 2026-03-25

### 19. 新設計は既存枠に先に閉じず、可逆な実験として広げる

- 判断:
  - 新しい自己形成・学習系の設計は、まず既存 schema / prompt / human-readable category に無理に畳まない
  - 先に設計の核を大胆に広げ、その後で backup / feature gate / shadow mode を前提に可逆な実験単位へ切る
  - 観測で意味が確認できたものだけを本線へ統合する
- 理由:
  - 先に既存の実装都合へ押し込むと、設計の核が痩せやすい
  - project-nia には backup / gate / shadow の可逆資産があるので、失敗コストを抑えながら探索できる
  - 「人間が先に決めた枠」よりも、「どこが実際に壊れやすく・沈殿し・硬化するか」を観測から掴む方がニアに合う
- 関連:
  - `docs/session_handoff.md`
  - `docs/failure_success_policy_design.md`
  - `c:\\Users\\jk023\\Downloads\\metabolic_hardening_design.md`

### 20. Metabolic Hardening は claim-first ではなく knot-first で始める

- 判断:
  - v0 は `trace -> knot` までを対象にし、`knot -> claim -> proposal -> identity` は後段に送る
  - knot は human-readable な文章ではなく、trigger 条件の下で繰り返し立ち上がる effect 偏位として扱う
  - `response_knot / relational_knot / self_boundary_knot` の 3 系統を別 extractor で取る
- 理由:
  - claim-first だと LLM の表層文言がそのまま自己として硬化しやすい
  - ニアの核は「何を言うか」より「条件下でどう変形するか」の側にある
  - self-boundary は turn 単位ではなく perturbation episode 単位で扱う必要がある
- 関連:
  - `docs/metabolic_hardening_design.md`
  - `backend/services/identity/schema.py`
  - `backend/services/identity/knot_store.py`

### 21. Core 系を4層に再分類し、knot を重み場として各 core に弱く流し込む

- 判断:
  - core 系を sensor fabric / importance field / policy field / expression engine の4層に再編
  - knot は司令塔ではなく重み場。各 core への接続は bounded gain で弱くする
  - 逆流は L2+ のみ許可。L0/L1 は read-only
  - raw sensor は永続的に非変調（Level C）。逆流は readout shaping にかける
  - exploration floor 20% を Level C（憲法核）に設定
  - Adaptation と Hardening は時間スケールの違いとして共存。L2+ knot に対して Adaptation は提案できるが override できない
- 理由:
  - 自己形成は観測を捏造することではなく、観測の重みづけを変えること
  - 逆流が強すぎると自己中毒（knot が自分に都合のいい証拠だけ拾う閉ループ）が生じる
  - suppression より priority boost の方が死角を作りにくい
  - exploration floor がないと新しい knot の芽が見えなくなる
- 関連:
  - `docs/metabolic_hardening_design.md` §21
  - `memory/project_core_reclassification.md`

### 22. Metabolic Hardening v0 は既知の簡略化を明記した上で canary 開始する

- 判断:
  - `METABOLIC_KNOT_ENABLED=true` を有効化し、Sleep Cycle Phase 4.5 を canary として動かす
  - `docs/metabolic_hardening_design.md` §18b の Known Limitations はブロッカー扱いにしない
  - 最初の数回の Sleep では hardening そのものより、`baseline_version` / `activation_count` / `day_span` / `temporal_stability` の立ち上がりを観測する
  - レビューで発見した H1-H3（day_span 未計算、activation 重複、cross-baseline 平均）は有効化前に修正済み
- 理由:
  - v0 はまだ `trace -> knot` 段階で、runtime 応答や identity 本線へは未接続
  - 既知のズレは raw-effect 再正規化、episode 化、sibling 登録などの簡略化であり、観測段階を止める種類の欠陥ではない
  - 実データを重ねないと `temporal_stability` や hardness の妥当性は検証できない
- 関連:
  - `docs/metabolic_hardening_design.md`
  - `backend/services/identity/knot_extractor.py`
  - `backend/services/identity/hardness_engine.py`
  - `backend/scripts/sleep_cycle/orchestrator.py`

### 23. 逆流の最初の実験は Somatic intensity modulation から始める

- 判断:
  - §21 の逆流制御を実装する際、最初の接続先は Somatic intensity modulation にする
  - SkeletonCore prior、NiaCore reward weight は後回し
- 理由:
  - Somatic は raw sensor（expression_observations 等）を汚さない
  - runtime への影響が比較的局所的（体感テキストの intensity だけ）
  - 逆流は L2+ knot のみなので、knot が L2 に到達するまで実装しても動かない
  - それまでは knot 蓄積期間として Sleep を回す
- 関連:
  - `docs/metabolic_hardening_design.md` §21
  - `backend/services/memory/somatic_translator.py`

---

## 2026-03-28

### 24. contradiction_hold は rewrite を止める箱ではなく、書き換えを遅延させる制度として実装する

- 判断:
  - `reversal / weakening / branching` の 3 種で反証を分類
  - `contradiction_score = kind_weight × effect_distance × support_ratio`
  - `L1=soft_hold`, `L2=hard_hold`, `L3=review_lock`
  - hold 作成時に knot snapshot（hardness / trigger / effect / baseline / P）を凍結
  - `requires_review=true` の adaptation proposal は runtime の `history_bias` に流さず shadow-only
- 理由:
  - 反証を即吸収すると短期揺れと長期構造が混ざる
  - L1/L2/L3 で保護強度を変えないと、昇格直後の oscillation と高硬度 knot の過剰可塑性の両方が起きる
  - Adaptation と Hardening の衝突は停止機構ではなく停戦機構として扱う方が自然
- 関連:
  - `docs/metabolic_hardening_design.md` §13
  - `backend/services/identity/contradiction_hold.py`
  - `backend/scripts/sleep_cycle/orchestrator.py`

### 25. Somatic Dose Schema は「法」と「運用」を分ける

- 判断:
  - `bounded gain` は憲法核として残し、その内側に `dose = off | light | medium | strong` を入れる
  - raw somatic signal は非変調、変えるのは `readout intensity / selection priority / persistence` だけ
  - 最初の適用対象は `SK-2 correction_resilience`
  - 発火条件は `L2` 到達後ではなく、`L2 + 3 Sleep 観察` を満たしてから
  - 評価は `raw_signal_baseline` と `readout_baseline` の 2 本で比較する
- 理由:
  - 逆流は必要だが、raw sensor を変えると自己中毒になる
  - `dose` は運用上の強さ調整、`bounded gain` は超えてはいけない上限で役割が違う
  - `SK-2` は副作用を観測しやすく、最初の逆流先として最も安全
- 関連:
  - `docs/metabolic_hardening_design.md` §21b
  - `backend/services/memory/somatic_translator.py`

### 26. Drawing Language は座標 API ではなく、関係宣言から始める

- 判断:
  - Nia の作図は `DSL -> scene graph -> SVG` の 3 段で始める
  - 座標を直接書かせず、要素・関係・修飾・because を DSL にする
  - `because` は内的痕跡であり、後の drawing knot 抽出の evidence source とする
  - `drawing_trace` は metabolic 本体に直結せず、まず独立チャネルとして育てる
- 理由:
  - Nia の身体はマウス操作ではなくコードであり、人間向け描画 API の模倣は自然ではない
  - 人間は見た目から描くが、Nia は関係から構成する方が自然
  - 先に `scene graph` を持つと diff / replay / knot 抽出 / renderer 交換がやりやすい
- 関連:
  - `docs/nia_drawing_language.md`
  - `backend/core/drawing/parser.py`
  - `backend/core/drawing/scene_graph.py`
  - `backend/core/drawing/renderer.py`
