"""Vector search for Minecraft skills using shared embedding model."""
from __future__ import annotations

import logging
from typing import Optional

import numpy as np

from backend.core import embedding_model
from backend.services.minecraft.skill_library import SkillLibrary

logger = logging.getLogger(__name__)


class SkillRetrieval:
    """Embeds skill descriptions and retrieves by semantic similarity."""

    def __init__(self, library: SkillLibrary):
        self._library = library
        self._cache: dict[str, np.ndarray] = {}
        self._dirty = True

    def invalidate(self) -> None:
        """Mark cache as dirty (call after skill save/delete)."""
        self._dirty = True

    def _rebuild_cache(self) -> None:
        """Rebuild embedding cache from all skills."""
        skills = self._library.list_all()
        if not skills:
            self._cache = {}
            self._dirty = False
            return

        texts = [s["description"] for s in skills]
        embeddings = embedding_model.encode(texts)
        if embeddings is None:
            logger.warning("[SkillRetrieval] Embedding encode failed")
            self._cache = {}
            self._dirty = False
            return

        self._cache = {}
        for i, skill in enumerate(skills):
            self._cache[skill["name"]] = embeddings[i]

        self._dirty = False
        logger.info("[SkillRetrieval] Cache rebuilt (%d skills)", len(self._cache))

    def search(self, query: str, top_k: int = 5, min_score: float = 0.3) -> list[dict]:
        """
        Search skills by semantic similarity to query.

        Returns list of {name, description, score, success_rate, ...}.
        """
        if self._dirty:
            self._rebuild_cache()

        if not self._cache:
            return []

        query_vec = embedding_model.encode([query])
        if query_vec is None:
            return []
        query_vec = query_vec[0]

        # Score against all cached skills
        scored = []
        for name, skill_vec in self._cache.items():
            score = float(np.dot(query_vec, skill_vec))
            if score >= min_score:
                scored.append((name, score))

        scored.sort(key=lambda x: x[1], reverse=True)
        scored = scored[:top_k]

        # Enrich with metadata
        results = []
        all_skills = {s["name"]: s for s in self._library.list_all()}
        for name, score in scored:
            skill = all_skills.get(name, {})
            results.append({
                "name": name,
                "description": skill.get("description", ""),
                "score": round(score, 3),
                "success_rate": skill.get("success_rate", 0.0),
                "total_uses": skill.get("total_uses", 0),
            })

        return results

    def find_exact(self, name: str) -> Optional[dict]:
        """Check if a skill exists by exact name."""
        return self._library.get(name)
