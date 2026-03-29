# Review Style — project-nia

## 基本形式

レビューではできるだけ次の形に寄せる:

- 指摘: {何が問題か}
- 修正案: {どう直すか}

## 優先度

- **High**: 実行時破綻 / データ汚染 / 制御経路の誤り
- **Medium**: 設計差分 / 契約のズレ / 観測汚染
- **Low**: docs ずれ / テスト不足 / 改善提案

## project-nia で優先して見ること

1. 不可侵ルール違反
2. observation と control の混線
3. turn-local / cross-turn の寿命破綻
4. guard / merge / prompt の責務境界
5. 未配線なのに `False` として扱っていないか

## 補足

- findings を先に出す
- サマリは短く
- 必要なら testing gap を明記する
