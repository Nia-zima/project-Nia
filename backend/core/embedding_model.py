"""
Shared embedding model singleton for semantic similarity calculations.

Uses sentence-transformers (paraphrase-multilingual-MiniLM-L12-v2) for
multilingual support. Lazy-loaded on first use.
"""
from __future__ import annotations

import logging
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)

_MODEL_NAME = "paraphrase-multilingual-MiniLM-L12-v2"
_model: Optional[object] = None
_load_failed = False


def _patch_torch_distributed():
    """ROCm builds may lack torch.distributed.is_initialized; patch if needed."""
    try:
        import torch
        if not hasattr(torch.distributed, "is_initialized"):
            torch.distributed.is_initialized = lambda: False
        if not hasattr(torch.distributed, "get_rank"):
            torch.distributed.get_rank = lambda: 0
    except Exception:
        pass


def _get_model():
    global _model, _load_failed
    if _model is not None:
        return _model
    if _load_failed:
        return None
    try:
        _patch_torch_distributed()
        from sentence_transformers import SentenceTransformer
        _model = SentenceTransformer(_MODEL_NAME)
        logger.info("[EmbeddingModel] loaded %s", _MODEL_NAME)
        return _model
    except Exception:
        _load_failed = True
        logger.warning("[EmbeddingModel] failed to load %s", _MODEL_NAME, exc_info=True)
        return None


def encode(texts: list[str]) -> Optional[np.ndarray]:
    """Encode texts into embeddings. Returns (N, D) array or None on failure."""
    model = _get_model()
    if model is None:
        return None
    try:
        return model.encode(texts, normalize_embeddings=True)
    except Exception:
        logger.warning("[EmbeddingModel] encode failed", exc_info=True)
        return None


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Cosine similarity between two 1-D vectors (assumed normalized)."""
    dot = float(np.dot(a, b))
    return max(0.0, min(1.0, dot))


def semantic_similarity(text_a: str, text_b: str) -> Optional[float]:
    """Compute semantic similarity between two texts. Returns None on failure."""
    vecs = encode([text_a, text_b])
    if vecs is None:
        return None
    return cosine_similarity(vecs[0], vecs[1])
