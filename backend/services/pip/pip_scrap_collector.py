"""
Pip Scrap Collector (Phase B)
Extracts orphaned emotions and fragmented dialogues from conversations
and stores them as Pip Scraps. Connects reflection to the store without
polluting the main reflection engine.
"""

from backend.core.logger import logger
from backend.services.pip.pip_scrap_store import pip_scrap_store

class PipScrapCollector:
    def process_scrap_candidates(self, thread_id: str, candidates: list[dict]):
        """
        Process a list of candidates identified during reflection.
        A candidate dict expects: {"type": str, "content": str}
        Only "orphaned_emotion" and "fragmented_dialogue" are collected for now.
        """
        if not candidates:
            return

        valid_types = {"orphaned_emotion", "fragmented_dialogue"}
        added_count = 0

        for cand in candidates:
            scrap_type = cand.get("type")
            content = cand.get("content")
            
            if scrap_type in valid_types and content:
                # Store the scrap
                try:
                    pip_scrap_store.add_scrap(thread_id, scrap_type, content)
                    added_count += 1
                except Exception as e:
                    logger.warning(f"[ScrapCollector] Failed to save candidate {scrap_type}: {e}")

        if added_count > 0:
            logger.info(f"[ScrapCollector] Collected {added_count} new scraps from thread {thread_id}")
            self._update_room_visuals(added_count)
            
    def _update_room_visuals(self, added_count: int):
        """Update the global RoomState pip_scrap_count so Unity can see it scale up."""
        from backend.services.room.room_state import load_room_state, save_room_state
        try:
            room = load_room_state()
            room.pip_state["scrap_count"] = room.pip_state.get("scrap_count", 0) + added_count
            save_room_state(room)
        except Exception as e:
            logger.warning(f"[ScrapCollector] Failed to update room_state for scraps: {e}")

pip_scrap_collector = PipScrapCollector()
