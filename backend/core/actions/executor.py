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
            "read_file": self._handle_read_file,
            "write_file": self._handle_write_file,
            "get_system_info": self._handle_get_system_info,
            "log_observation": self._handle_log_observation,
            # Minecraft game actions
            "mc_chat": self._handle_mc_action,
            "mc_move": self._handle_mc_action,
            "mc_mine": self._handle_mc_action,
            "mc_place": self._handle_mc_action,
            "mc_craft": self._handle_mc_action,
            "mc_attack": self._handle_mc_action,
            # Twitter (X)
            "post_tweet": self._handle_post_tweet,
            # Drawing Language
            "render_drawing": self._handle_render_drawing,
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
        """感情表示更新（フロントエンドへの通知はSSE経由で配信）"""
        emotion = payload.get("emotion", "neutral")
        intensity = payload.get("intensity", 0.5)
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


    async def _handle_post_tweet(self, payload: Dict[str, Any]) -> Any:
        """ツイート投稿"""
        from backend.services.x_post_service import x_post_service
        text = payload.get("tweet_text", "")
        if not text:
            raise ValueError("tweet_text is required")
        thread_id = str(payload.get("thread_id") or "default_thread")
        pending_id = payload.get("_pending_id")
        result = await x_post_service.publish_approved_text(
            thread_id=thread_id,
            text=text,
            source="phase5_action",
            turn_id=str(payload.get("turn_id") or "") or None,
            message_id=str(payload.get("message_id") or "") or None,
            stream_id=str(payload.get("stream_id") or "") or None,
            source_ref=str(pending_id) if pending_id else None,
            actor="user",
            metadata={
                "action_payload": {
                    key: value
                    for key, value in payload.items()
                    if key not in {"tweet_text"}
                },
            },
        )
        if not result.get("success"):
            raise RuntimeError(f"Tweet failed: {result.get('error')}")
        return {
            "posted": True,
            "tweet_id": result.get("tweet_id"),
            "tweet_text": result.get("tweet_text"),
            "char_count": len(result.get("tweet_text") or ""),
            "proposal_id": (result.get("proposal") or {}).get("proposal_id"),
        }

    async def _handle_render_drawing(self, payload: Dict[str, Any]) -> Any:
        """ドローイング生成: draw DSL → SVG + trace 保存"""
        from backend.core.drawing.runtime import render_and_store_drawing
        return await render_and_store_drawing(payload)

    async def _handle_mc_action(self, payload: Dict[str, Any]) -> Any:
        """Minecraft ゲームアクション共通ハンドラ"""
        from backend.services.minecraft import minecraft_client
        if not minecraft_client:
            return {"error": "Minecraft not connected"}
        action = payload.get("_action_id", "chat")
        # mc_ prefix を除去して Mineflayer アクション名に変換
        mc_action = action.replace("mc_", "") if action.startswith("mc_") else action
        action_map = {
            "chat": "chat",
            "move": "move_to",
            "mine": "mine_block",
            "place": "place_block",
            "craft": "craft",
            "attack": "attack",
        }
        mf_action = action_map.get(mc_action, mc_action)
        params = {k: v for k, v in payload.items() if k != "_action_id"}
        return await minecraft_client.execute_action(mf_action, params)


# グローバルインスタンス
action_executor = ActionExecutor()
