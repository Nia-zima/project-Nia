# ⚙️ ニア(Near) システム仕様書

## 1. 記憶システム (The Brain)
- **Private Memory:** 信頼度100%。あなたとの会話・約束を永久保存。
- **Stream Memory:** 信頼度減衰。配信コメント等は時間が経つと自動消滅(GC)。
- **Fail-Safe:** 配信メタデータ欠損時は自動で最大警戒モードになり汚染を防ぐ。

## 2. 防御システム (The Shield)
- **Audience Safety Layer v2:** 群衆の「数」「悪意」を検知し影響力を弱める。
- **Stream Digest (Phase 4.5):** 配信記憶は物理削除され、「抽象的な雰囲気（天気図）」だけが外伝として残る。
- **Allow List:** 「学習許可」がない記憶は、寝ている間に夢に見ることすら許されない。

## 3. 人格進化 (The Soul)
- **Guardian (Layer B):** 人格の管理者。急激な変化や性格の改変をブロックする。
- **Chapter Evolution (Phase 5):** 週単位で人生を振り返り、自己分析する。
- **Human Check (Phase 5.4):** 人間が `chapter_decision` で承認しない限り、人格は絶対に書き換わらない。

## 4. インターフェース (The Interface)
- **OBS連携 (Phase 6):** `obs_writer` が人格回路と絶縁された状態でテキストを出力。

## 三権分立:
- **AI:** 考える (Reflection)
- **人間:** 決める (Decision)
- **システム:** 従う (Sleep Cycle)
