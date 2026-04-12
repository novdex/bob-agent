"""
Sentence Embedding System (AGI Pillar - Memory).

Uses sentence-transformers (all-MiniLM-L6-v2) for semantic similarity.
Generates 384-dimensional embeddings that understand full sentences.
Runs locally, no API key needed.
"""

from __future__ import annotations

import logging
import threading
from typing import List

import numpy as np

log = logging.getLogger("mind_clone")

EMBEDDING_DIM = 384
EMBEDDING_MODEL_NAME = "all-MiniLM-L6-v2"
GLOVE_DIM = EMBEDDING_DIM  # backward compat alias

_model = None
_model_lock = threading.Lock()


def _ensure_model():
    global _model
    if _model is not None:
        return _model
    with _model_lock:
        if _model is not None:
            return _model
        try:
            from sentence_transformers import SentenceTransformer
            _model = SentenceTransformer(EMBEDDING_MODEL_NAME, local_files_only=True)
            log.info("EMBEDDING_MODEL_LOADED model=%s dim=%d", EMBEDDING_MODEL_NAME, EMBEDDING_DIM)
            return _model
        except Exception as exc:
            log.error("EMBEDDING_MODEL_LOAD_FAILED: %s", exc)
            return None


def get_embedding(text: str) -> np.ndarray:
    if not text or not text.strip():
        return np.zeros(EMBEDDING_DIM, dtype=np.float32)
    model = _ensure_model()
    if model is None:
        return np.zeros(EMBEDDING_DIM, dtype=np.float32)
    vec = model.encode(text, normalize_embeddings=True, show_progress_bar=False)
    return vec.astype(np.float32)


def get_embeddings_batch(texts: List[str]) -> List[np.ndarray]:
    if not texts:
        return []
    model = _ensure_model()
    if model is None:
        return [np.zeros(EMBEDDING_DIM, dtype=np.float32) for _ in texts]
    vecs = model.encode(texts, normalize_embeddings=True, batch_size=32, show_progress_bar=False)
    return [v.astype(np.float32) for v in vecs]


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    norm_a = np.linalg.norm(a)
    norm_b = np.linalg.norm(b)
    if norm_a < 1e-9 or norm_b < 1e-9:
        return 0.0
    return float(np.dot(a, b) / (norm_a * norm_b))


def embedding_to_bytes(vec: np.ndarray) -> bytes:
    return vec.astype(np.float32).tobytes()


def bytes_to_embedding(data: bytes) -> np.ndarray:
    return np.frombuffer(data, dtype=np.float32).copy()
