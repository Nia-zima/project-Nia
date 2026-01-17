from langchain_core.tools import tool
import os
import asyncio
import base64
import io
import datetime

from backend.core.logger import logger

# --- Vision Dependencies ---
try:
    import pyautogui
except ImportError:
    pyautogui = None

try:
    from langchain_ollama import ChatOllama
except ImportError:
    ChatOllama = None

from langchain_core.messages import HumanMessage


# ---------------------------------------------------------
# 1) MEMORY (ACTIVE)
# ---------------------------------------------------------
@tool
def save_memory(content: str) -> str:
    """ユーザーの重要な情報を記憶します（長期記憶C層へ）。"""
    try:
        from backend.services.memory_manager import memory_manager

        # Toolは同期文脈で呼ばれがちなので、状況に応じて実行
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        coro = memory_manager.register_thought(
            text=content,
            confidence=0.8,
            source="manual_save"
        )

        if loop and loop.is_running():
            asyncio.create_task(coro)
        else:
            asyncio.run(coro)

        logger.info(f"Tool: save_memory - {content[:30]}...")
        return f"記憶に刻みました: {content}"

    except Exception as e:
        logger.error("Tool Error: save_memory", exc_info=True)
        return f"保存エラー: {e}"


@tool
def search_memory(query: str) -> str:
    """過去の記憶を「言葉の意味」で検索します。"""
    try:
        from backend.services.memory_manager import memory_manager

        # memory_manager.recall_memories(query, limit=...) が正
        results = asyncio.run(memory_manager.recall_memories(query=query, limit=5))

        if not results:
            return "関連する記憶は見つかりませんでした。"

        formatted = []
        for r in results:
            text = (r.get("content") or "").strip()
            conf = r.get("confidence_tag", "mid")
            if text:
                formatted.append(f"・{text} (確信度: {conf})")

        return "【過去の記憶より】\n" + "\n".join(formatted) if formatted else "関連する記憶は見つかりませんでした。"

    except Exception as e:
        logger.error("Tool Error: search_memory", exc_info=True)
        return f"検索エラー: {e}"


@tool
def save_episode(summary: str, category: str = "general", details: str = "") -> str:
    """重要な出来事をエピソードとして保存します（C層DBのepisodesテーブル想定）。"""
    try:
        from backend.services.memory_manager import memory_manager

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        coro = memory_manager.add_episode(
            summary=summary,
            category=category,
            details=details,
        )

        if loop and loop.is_running():
            asyncio.create_task(coro)
        else:
            asyncio.run(coro)

        return f"エピソードを記憶しました: {summary}"

    except Exception as e:
        logger.error("Tool Error: save_episode", exc_info=True)
        return f"エピソードの保存に失敗しました: {e}"


# ---------------------------------------------------------
# 2) SCREEN VISION (OPTIONAL / LOCAL)
# ---------------------------------------------------------
@tool
def see_screen(query: str) -> str:
    """現在のデスクトップ画面を撮影し、内容について回答します（ローカルのみ）。"""
    try:
        if not pyautogui or not ChatOllama:
            return "画面認識機能がセットアップされていません。"

        logger.info(f"Tool: see_screen - {query}")
        screenshot = pyautogui.screenshot()

        # JPEGに変換してBase64化
        img_buffer = io.BytesIO()
        screenshot = screenshot.convert("RGB")
        screenshot.save(img_buffer, format="JPEG", quality=75)
        img_base64 = base64.b64encode(img_buffer.getvalue()).decode("utf-8")

        # 画像対応モデル（Ollama/Qwen-VL等）を想定
        llm = ChatOllama(
            model=os.getenv("VISION_MODEL", "qwen2.5-vl"),
            temperature=0.2
        )

        msg = HumanMessage(content=[
            {"type": "text", "text": query},
            {"type": "image_url", "image_url": f"data:image/jpeg;base64,{img_base64}"}
        ])

        res = llm.invoke([msg])
        return res.content if hasattr(res, "content") else str(res)

    except Exception as e:
        logger.error("Tool Error: see_screen", exc_info=True)
        return f"画面認識中にエラーが発生しました: {e}"


# ---------------------------------------------------------
# 🔧 EXPORTED TOOLS LIST (LOBOTOMY)
# ---------------------------------------------------------
# web_search は “物理的に存在しない” 状態にする
tools = [
    save_memory,
    search_memory,
    save_episode,
    see_screen,
]
