"""
GloVe Word Vector Embedding System (AGI Pillar - Memory).

Uses pre-trained GloVe 6B 100d word vectors for semantic similarity.
Pure Python + numpy - no native DLL extensions needed.
Provides embeddings for memory search, lesson retrieval, task artifacts,
episodic memory, and world model queries.
"""

from __future__ import annotations

import logging
import os
import re
import threading
import zipfile
from io import BytesIO
from pathlib import Path

import numpy as np
import requests

log = logging.getLogger("mind_clone")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
GLOVE_DIM = 100  # 100-dimensional GloVe vectors
GLOVE_VOCAB_LIMIT = 50_000  # Top 50K words covers >99% of typical text
GLOVE_MODEL_NAME = "glove.6B.100d.txt"
GLOVE_ZIP_URL = "https://nlp.stanford.edu/data/glove.6B.zip"

# ---------------------------------------------------------------------------
# Module state (thread-safe lazy singleton)
# ---------------------------------------------------------------------------
_glove_vectors: dict[str, np.ndarray] | None = None
_glove_lock = threading.Lock()

# Shared requests session for downloads
_session = requests.Session()


def _glove_cache_dir() -> Path:
    """Return cache directory for GloVe model files.

    Always uses ``~/.mind-clone/models`` to stay consistent with the
    single runtime directory convention.
    """
    return Path.home() / ".mind-clone" / "models"


def _download_glove_if_needed() -> Path:
    """Download GloVe vectors if not cached. Returns path to the text file."""
    cache = _glove_cache_dir()
    cache.mkdir(parents=True, exist_ok=True)
    glove_path = cache / GLOVE_MODEL_NAME
    if glove_path.exists():
        return glove_path

    log.info("GLOVE_DOWNLOAD starting (~330MB one-time download)...")
    resp = _session.get(GLOVE_ZIP_URL, stream=True, timeout=600)
    resp.raise_for_status()
    data = b"".join(resp.iter_content(chunk_size=1024 * 1024))
    log.info("GLOVE_DOWNLOAD extracting %s...", GLOVE_MODEL_NAME)
    with zipfile.ZipFile(BytesIO(data)) as z:
        z.extract(GLOVE_MODEL_NAME, str(cache))
    log.info("GLOVE_DOWNLOAD done: %s", glove_path)
    return glove_path


def _load_glove_vectors() -> dict[str, np.ndarray]:
    """Load GloVe vectors from disk. Called once, cached in memory."""
    global _glove_vectors
    with _glove_lock:
        if _glove_vectors is not None:
            return _glove_vectors
        try:
            glove_path = _download_glove_if_needed()
            vectors: dict[str, np.ndarray] = {}
            with open(glove_path, "r", encoding="utf-8") as f:
                for i, line in enumerate(f):
                    if i >= GLOVE_VOCAB_LIMIT:
                        break
                    parts = line.rstrip().split(" ")
                    word = parts[0]
                    vec = np.array([float(x) for x in parts[1:]], dtype=np.float32)
                    vectors[word] = vec
            _glove_vectors = vectors
            log.info("GLOVE_LOADED %d word vectors, dim=%d", len(vectors), GLOVE_DIM)
            return vectors
        except Exception as exc:
            log.error("GLOVE_LOAD_FAILED: %s", exc)
            _glove_vectors = {}
            return {}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_embedding(text: str) -> np.ndarray:
    """Generate a normalized embedding for text by averaging GloVe word vectors."""
    vectors = _load_glove_vectors()
    if not vectors:
        return np.zeros(GLOVE_DIM, dtype=np.float32)
    words = re.findall(r"[a-zA-Z]+", text.lower())
    vecs = [vectors[w] for w in words if w in vectors]
    if not vecs:
        return np.zeros(GLOVE_DIM, dtype=np.float32)
    avg = np.mean(vecs, axis=0)
    norm = np.linalg.norm(avg)
    return avg / max(norm, 1e-9)


def get_embeddings_batch(texts: list[str]) -> list[np.ndarray]:
    """Generate embeddings for multiple texts."""
    return [get_embedding(t) for t in texts]


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Compute cosine similarity between two vectors."""
    norm_a = np.linalg.norm(a)
    norm_b = np.linalg.norm(b)
    if norm_a < 1e-9 or norm_b < 1e-9:
        return 0.0
    return float(np.dot(a, b) / (norm_a * norm_b))


def embedding_to_bytes(vec: np.ndarray) -> bytes:
    """Serialize numpy array to bytes for SQLite storage."""
    return vec.astype(np.float32).tobytes()


def bytes_to_embedding(data: bytes) -> np.ndarray:
    """Deserialize bytes back to numpy array."""
    return np.frombuffer(data, dtype=np.float32).copy()
