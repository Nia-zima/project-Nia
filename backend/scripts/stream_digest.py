import asyncio
import logging
import sys

from backend.core.config import settings
from backend.core.logger import setup_logging

# モジュール
from backend.services.llm_client import call_llm
from backend.services.memory_manager import memory_manager
from backend.services.vector_store import vector_store

# ロガー設定
setup_logging(level="INFO", log_file=settings.PROJECT_ROOT / "logs" / "stream_digest.log", console=True)
logger = logging.getLogger("StreamDigest")

async def digest_streams(days: int = 7) -> None:
    """
    直近の配信記憶(livestream)を収集し、
    「具体的な単語」を排除した「雰囲気」だけのダイジェストを作成してPrivate保存する。
    """
    logger.info("🎬 === Stream Memory Digest Protocol (%s days) === 🎬", days)
    
    # 1. 配信記憶の収集 (VectorStoreの機能を使うか、直接DBを叩く)
    # ここでは簡易的に VectorStore の private コレクションメソッドを流用しつつ ChromaDB のフィルタ機能を使う想定
    # ※ 厳密には Stream Memory は別の Collection (col_stream) にある
    
    if not vector_store or not vector_store.is_active:
        logger.error("VectorStore not initialized.")
        return

    try:
        # 過去N日
        # ChromaDBのmetadataフィルタで source="livestream" を全部取るのは重いが、
        # Stream Memoryは TTL で消える運命なので、全件取得しても量は (TTL期間分しか) ないはず。
        
        results = vector_store.col_stream.get(
            where={"source": "livestream"},
            include=["documents", "metadatas"]
        )
        
        if not results["documents"]:
            logger.info("No stream memories found to digest.")
            return

        # テキスト結合
        full_text = "\n".join(results["documents"])
        logger.info(f"Collected {len(results['documents'])} stream comments/memories.")

        # 2. 消毒ダイジェスト生成
        prompt = f"""
あなたはAI配信者の「活動記録係」です。
以下は最近の配信内での会話ログ（視聴者のコメントやAIの反応）です。

【ログ】
{full_text[:10000]}  # トークン溢れ防止のためカット

【タスク】
この期間の配信の「傾向」や「雰囲気」だけを抽出して要約してください。
ただし、**「語彙感染」を防ぐため、以下のルールを厳守してください。**

【厳守ルール】
1. **具体的な固有名詞、視聴者の名前、特定の単語（スラング等）は一切使用しないこと。**
2. 「議論が盛り上がった」「温かい雰囲気だった」といった**抽象的な表現**のみを使うこと。
3. 以下のテンプレートに従って出力すること。

【出力テンプレート】
--------------------------------------------------
【今週の配信傾向】
- (雰囲気の要約1)
- (雰囲気の要約2)
- (統計的な傾向: 例「質問が多かった」など)

[Overall Mood]
(Neutral / Excited / Calm / Chaotic のいずれか)
--------------------------------------------------
"""
        logger.info("Generating safe digest...")
        digest = await call_llm([{"role": "system", "content": prompt}], temperature=0.2)
        
        if digest and "【今週の配信傾向】" in digest:
            logger.info(f"✅ Safe Digest Generated:\n{digest}")
            
            # 3. Private Memory への昇華
            # これで「配信の記憶」は消えても「配信をしたという事実と雰囲気」は一生残る
            await memory_manager.add_episode(
                summary=digest,
                category="stream_digest",
                details="Emotion: neutral\nDetailed logs are purged due to TTL."
            )
            logger.info("💾 Saved to Private Episode (Permanent).")
            
        else:
            logger.warning("⚠️ Digest generation failed or format invalid.")

    except Exception as e:
        logger.error(f"Digest Error: {e}")

if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(digest_streams(days=7))
