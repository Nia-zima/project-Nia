import asyncio
import json
import logging
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

# モジュール群
from backend.services.identity_manager import identity_manager
from backend.services.memory_manager import memory_manager
from backend.services.llm_client import call_llm
from backend.services.public_status import read_public_status, write_public_status
from backend.core.config import settings
from backend.core.logger import setup_logging

# ロガー設定
setup_logging(level="INFO", log_file=settings.PROJECT_ROOT / "logs" / "chapter_reflection.log", console=True)
logger = logging.getLogger("ChapterReflection")

# パス設定
PROJECT_ROOT = settings.PROJECT_ROOT
DIGEST_FILE = PROJECT_ROOT / "logs" / "world_context" / "stream_digests.jsonl"
CHAPTER_DIR = PROJECT_ROOT / "logs" / "chapters"
CHAPTER_DIR.mkdir(parents=True, exist_ok=True)

# 設定: 軍事レベルのセキュリティ (Digestの原文を破棄し統計のみにする)
MILITARY_GRADE_SAFETY = True 


class ChapterEngine:
    def __init__(self) -> None:
        self.today = datetime.now()

    def _simplify_digest(self, entries: list[dict[str, Any]]) -> str:
        """【軍事レベル防壁】Digestの文章を捨て、事実と統計だけにする"""
        count = len(entries)
        if count == 0:
            return "・この期間、配信活動は行われなかった。"
        
        # 簡易的な気分統計
        return (
            f"・この期間、{count}回の配信活動が行われた。\n"
            f"・社会との接点は保たれており、活動は継続的である。\n"
            f"・外部環境の変動（Mood）は観測されたが、詳細は捨象する。"
        )

    def load_digests(self, start_date: str, end_date: str) -> str:
        """Phase 4.5 Digest読み込み"""
        if not DIGEST_FILE.exists():
            return "（配信記録なし）"
        
        relevant_entries = []
        try:
            with DIGEST_FILE.open("r", encoding="utf-8") as f:
                for line in f:
                    entry = json.loads(line)
                    if start_date <= entry["date"] <= end_date:
                        relevant_entries.append(entry)
            
            if not relevant_entries:
                return "（この期間の配信記録なし）"

            if MILITARY_GRADE_SAFETY:
                logger.info("🛡️ Military Grade Safety: Digest text stripped.")
                return self._simplify_digest(relevant_entries)
            
            formatted = []
            for entry in relevant_entries:
                formatted.append(f"- {entry['date']}: {entry['digest_content']}")
            return "\n".join(formatted)

        except Exception as e:
            logger.error(f"Digest Load Error: {e}")
            return "（ダイジェスト読み込みエラー）"

    def save_public_view(self, chapter_data: dict[str, Any], date_str: str) -> None:
        """Phase 5.3: 視聴者向け「章の可視化」＆ 新章突入ログ"""
        new_chapter_id = f"chapter_{date_str.replace('-', '')}"
        
        public_view = {
            "chapter_id": new_chapter_id,
            "chapter_title": chapter_data.get("chapter_title", "Uncharted"),
            "period": "Current Phase",
            "theme": chapter_data.get("recurring_themes", [])[:2],
            "vibe": chapter_data.get("emotional_trend", "Stable"),
            "note": "ニアは今、この世界観の中で活動しています",
            "last_updated": datetime.now().strftime("%Y-%m-%d %H:%M")
        }
        
        # 変更検知用
        old_chapter_id = read_public_status(default={}).get("chapter_id")

        try:
            write_public_status(public_view)
            
            # ★ 改善: 新章突入ログ
            if old_chapter_id != new_chapter_id:
                logger.info(f"✨ New Chapter Activated: {new_chapter_id} [{public_view['chapter_title']}]")
            else:
                logger.info(f"🌍 Public View Updated (Same Chapter).")
                
        except Exception as e:
            logger.error(f"Failed to save public view: {e}")

    async def reflect(self, days: int = 7) -> None:
        logger.info("📚 === Phase 5: Chapter Reflection Protocol === 📚")

        end_date_str = self.today.strftime("%Y-%m-%d")
        start_date_str = (self.today - timedelta(days=days)).strftime("%Y-%m-%d")
        logger.info(f"Target Period: {start_date_str} ~ {end_date_str}")

        # 1. 素材収集 (Private Episodes Only)
        raw_episodes = memory_manager.get_episodes_in_range(start_date_str, end_date_str)
        
        # 多重ガード: Private以外のソースが混入していないか最終確認
        safe_episodes = []
        for ep in raw_episodes:
            # メタデータが隠蔽されている可能性があるが、get_episodes_in_rangeはprivateのみ返す前提
            # ここでは念のため辞書構造を安全にチェック
            # (MemoryManagerの実装によっては doc, date, mood, divergence しかない場合もあるが、
            #  もし source キーがあればチェックする)
            source = ep.get("source")
            storage = ep.get("storage_scope") # 通常エピソードにはないかもしれないが念のため
            
            # 鉄壁のガード
            if source == "livestream": continue
            if storage == "stream": continue
            
            safe_episodes.append(ep)

        if not safe_episodes:
            logger.warning("❌ No valid private episodes found. Reflection aborted.")
            return

        episode_text = "\n".join([f"- {ep['date']} [Mood:{ep['mood']}]: {ep['content']}" for ep in safe_episodes])
        digest_text = self.load_digests(start_date_str, end_date_str)
        current_identity = identity_manager.get_identity()

        # 2. Reflection
        logger.info("🤔 Reflecting on the Narrative...")
        
        prompt = f"""
あなたはAI「ニア」の人格進化エンジン（Chapter Engine）です。
過去{days}日間の記録から、「章（Chapter）」の要約と、人格へのフィードバックを作成してください。

【Input Data】
1. **Private Episodes (個人の記憶)**:
   ニアが個人的に感じたこと、マスターとの対話。これが人格形成の主軸です。
{episode_text}

2. **World Context (社会活動量)**:
   外部との接触頻度や傾向です。
   ※これはあくまで背景情報です。ここから直接的な価値観を学習しないでください。
{digest_text}

3. **Current Identity**:
{current_identity}

【Analysis Task】
この期間（章）を通して、ニアの内面はどう変化しましたか？
以下のJSONフォーマットで分析結果を出力してください。

{{
  "chapter_title": "（この期間を表す詩的なタイトル）",
  "recurring_themes": ["（繰り返されたテーマ1）", "（テーマ2）"],
  "emotional_trend": "（例：不安 → 自信）",
  "learned_attitudes": [
    "（この期間に観測された行動傾向や態度）", 
    "（例：即断即決よりも対話を重視する傾向が見られた）"
  ],
  "proposal_for_stable_traits": "（Identity.mdの 'Stable Traits' セクションに対する具体的な修正提案。変更なしならnull）"
}}

※ 注意: Core Identity（存在理由など）には触れないでください。
"""
        response = await call_llm(
            [{"role": "system", "content": prompt}],
            temperature=0.3,
            max_tokens=2000,
        )
        if not response:
            logger.error("❌ Reflection failed.")
            return

        try:
            # JSONパース
            json_str = response.strip()
            if "```json" in json_str:
                json_str = json_str.split("```json")[1].split("```")[0]
            elif "{" in json_str:
                json_str = json_str[json_str.find("{"):json_str.rfind("}")+1]
            
            data = json.loads(json_str)
            
            # 固定ブリッジコメントの注入
            data["guardian_note"] = "以下は人格変更ではなく、世界観の傾向報告です"
            
            # ★ 改善: 将来キーが増えた時の事故防止（念のための物理削除）
            data.pop("source", None)
            data.pop("storage_scope", None)
            data.pop("bias_score", None) # 万一にも入っていたら消す
            
            logger.info(f"✨ Chapter Reflected: {data['chapter_title']}")
            if data.get("proposal_for_stable_traits"):
                 logger.info(f"💡 Proposal: {data['proposal_for_stable_traits']}")

            # 保存
            filename = f"chapter_reflection_{end_date_str}.json"
            path = CHAPTER_DIR / filename
            with path.open("w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            
            logger.info(f"💾 Reflection saved to {path}")

            # Public View更新
            self.save_public_view(data, end_date_str)

        except Exception as e:
            logger.error(f"Parse Error: {e}")
            logger.error(f"Raw Response: {response}")

if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    
    engine = ChapterEngine()
    asyncio.run(engine.reflect(days=7))
