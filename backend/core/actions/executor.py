# backend/core/actions/executor.py

from typing import Any, Dict, Optional
from backend.core.actions.types import Action
from backend.core.logger import logger


class ActionExecutor:
    """アクション実行器"""

    async def execute(self, action: Action) -> Dict[str, Any]:
        """
        アクションを実行

        Args:
            action: 実行するアクション

        Returns:
            実行結果
        """
        try:
            logger.info(f"🔧 Executing action: {action.id}")

            # アクションIDに基づいて実行
            handler = self._get_handler(action.id)
            if handler is None:
                return {
                    "status": "error",
                    "message": f"Unknown action: {action.id}",
                }

            result = await handler(action.payload)

            logger.info(f"✅ Action completed: {action.id}")
            return {
                "status": "success",
                "result": result,
            }

        except Exception as e:
            logger.error(f"❌ Action failed: {action.id} - {e}", exc_info=True)
            return {
                "status": "error",
                "message": str(e),
            }

    def _get_handler(self, action_id: str):
        """アクションハンドラーを取得"""
        handlers = {
            "search_memory": self._handle_search_memory,
            "save_memory": self._handle_save_memory,
            "save_episode": self._handle_save_episode,
            "update_obs_text": self._handle_update_obs_text,
            "update_emotion_display": self._handle_update_emotion_display,
            "see_screen": self._handle_see_screen,
            "web_search": self._handle_web_search,
            "read_file": self._handle_read_file,
            "write_file": self._handle_write_file,
            "text_to_speech": self._handle_text_to_speech,
            "get_system_info": self._handle_get_system_info,
            "send_notification": self._handle_send_notification,
            "log_observation": self._handle_log_observation,
        }
        return handlers.get(action_id)

    # ハンドラー実装
    async def _handle_search_memory(self, payload: Dict[str, Any]) -> Any:
        """記憶検索"""
        from backend.services.memory_manager import memory_manager
        query = payload.get("query", "")
        results = await memory_manager.recall_memories(query=query, limit=5)
        return {"results": results, "count": len(results)}

    async def _handle_save_memory(self, payload: Dict[str, Any]) -> Any:
        """記憶保存"""
        from backend.services.memory_manager import memory_manager
        content = payload.get("content", "")
        confidence = payload.get("confidence", 0.8)
        await memory_manager.register_thought(
            text=content,
            confidence=confidence,
            source="manual_save"
        )
        return {"saved": True, "content": content}

    async def _handle_save_episode(self, payload: Dict[str, Any]) -> Any:
        """エピソード保存"""
        from backend.services.memory_manager import memory_manager
        summary = payload.get("summary", "")
        category = payload.get("category", "general")
        details = payload.get("details", "")
        await memory_manager.add_episode(
            summary=summary,
            category=category,
            details=details
        )
        return {"saved": True, "summary": summary}

    async def _handle_update_obs_text(self, payload: Dict[str, Any]) -> Any:
        """OBS表示更新"""
        from backend.services.public_status import update_public_status
        update_public_status(payload, allowed_keys={"note"})
        return {"updated": True, "text": payload.get("note", "")}

    async def _handle_update_emotion_display(self, payload: Dict[str, Any]) -> Any:
        """感情表示更新"""
        emotion = payload.get("emotion", "neutral")
        intensity = payload.get("intensity", 0.5)
        # TODO: 実際の感情表示システムと連携
        logger.info(f"Emotion display updated: {emotion} (intensity={intensity})")
        return {"updated": True, "emotion": emotion, "intensity": intensity}

    async def _handle_see_screen(self, payload: Dict[str, Any]) -> Any:
        """画面認識"""
        query = payload.get("query", "画面に何が表示されていますか？")

        try:
            import pyautogui
            import base64
            import io
            from backend.core.config import settings

            screenshot = pyautogui.screenshot()

            # JPEGに変換してBase64化
            img_buffer = io.BytesIO()
            screenshot = screenshot.convert("RGB")
            screenshot.save(img_buffer, format="JPEG", quality=75)
            img_base64 = base64.b64encode(img_buffer.getvalue()).decode("utf-8")

            provider = getattr(settings, "VISION_PROVIDER", "ollama").lower()
            if provider in ("openai", "lmstudio"):
                from backend.services.vision_client import analyze_image
                data_url = f"data:image/jpeg;base64,{img_base64}"
                content = await analyze_image(data_url, prompt=query)
                return {"result": content, "query": query}

            # 画像対応モデル (Ollama)
            from langchain_ollama import ChatOllama
            from langchain_core.messages import HumanMessage
            llm = ChatOllama(
                model=settings.VISION_MODEL,
                temperature=0.2
            )

            msg = HumanMessage(content=[
                {"type": "text", "text": query},
                {"type": "image_url", "image_url": f"data:image/jpeg;base64,{img_base64}"}
            ])

            res = llm.invoke([msg])
            content = res.content if hasattr(res, "content") else str(res)

            return {"result": content, "query": query}

        except ImportError:
            return {"error": "画面認識機能がセットアップされていません"}
        except Exception as e:
            logger.error(f"Screen capture failed: {e}")
            return {"error": str(e)}

    async def _handle_web_search(self, payload: Dict[str, Any]) -> Any:
        """Web検索"""
        query = payload.get("query", "")
        # TODO: 実際のWeb検索APIと連携
        logger.info(f"Web search: {query}")
        return {
            "query": query,
            "results": [],
            "message": "Web検索機能は未実装です",
        }

    async def _handle_read_file(self, payload: Dict[str, Any]) -> Any:
        """ファイル読み取り"""
        import os
        file_path = payload.get("file_path", "")

        if not file_path:
            raise ValueError("file_path is required")

        if not os.path.exists(file_path):
            raise FileNotFoundError(f"File not found: {file_path}")

        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()

        return {
            "content": content,
            "file_path": file_path,
            "size": len(content),
        }

    async def _handle_write_file(self, payload: Dict[str, Any]) -> Any:
        """ファイル書き込み"""
        file_path = payload.get("file_path", "")
        content = payload.get("content", "")

        if not file_path:
            raise ValueError("file_path is required")

        with open(file_path, "w", encoding="utf-8") as f:
            f.write(content)

        return {
            "written": True,
            "file_path": file_path,
            "size": len(content),
        }

    async def _handle_text_to_speech(self, payload: Dict[str, Any]) -> Any:
        """音声合成"""
        text = payload.get("text", "")
        # TODO: VOICEVOX連携の実装
        logger.info(f"TTS request: {text[:50]}...")
        return {
            "synthesized": False,
            "text": text,
            "message": "音声合成機能は未実装です",
        }

    async def _handle_get_system_info(self, payload: Dict[str, Any]) -> Any:
        """システム情報取得"""
        import platform
        import psutil

        return {
            "system": platform.system(),
            "release": platform.release(),
            "machine": platform.machine(),
            "processor": platform.processor(),
            "cpu_count": psutil.cpu_count(),
            "memory_total": psutil.virtual_memory().total,
            "memory_available": psutil.virtual_memory().available,
        }

    async def _handle_send_notification(self, payload: Dict[str, Any]) -> Any:
        """通知送信"""
        title = payload.get("title", "")
        message = payload.get("message", "")

        # TODO: デスクトップ通知の実装
        logger.info(f"Notification: {title} - {message}")
        return {
            "sent": False,
            "title": title,
            "message": message,
            "note": "通知機能は未実装です",
        }

    async def _handle_log_observation(self, payload: Dict[str, Any]) -> Any:
        """観察ログ記録"""
        observation = payload.get("observation", "")
        category = payload.get("category", "general")

        logger.info(f"📝 Observation [{category}]: {observation}")
        return {
            "logged": True,
            "observation": observation,
            "category": category,
        }


# グローバルインスタンス
action_executor = ActionExecutor()
