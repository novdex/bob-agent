"""ChromaDB vector store for memory search."""
from __future__ import annotations
import logging, os, threading
from typing import Any, Dict, List, Optional

log = logging.getLogger("mind_clone")
_client = None
_client_lock = threading.Lock()

def _get_client():
    global _client
    if _client is not None: return _client
    with _client_lock:
        if _client is not None: return _client
        import chromadb
        path = os.environ.get("CHROMA_PERSIST_DIR", os.path.expanduser("~/.mind-clone/chroma"))
        os.makedirs(path, exist_ok=True)
        _client = chromadb.PersistentClient(path=path)
        log.info("CHROMA_INIT path=%s", path)
        return _client

def _get_collection(owner_id: int):
    client = _get_client()
    return client.get_or_create_collection(name=f"owner_{owner_id}", metadata={"hnsw:space": "cosine"})

def store_memory(owner_id, memory_id, text, embedding, metadata=None):
    col = _get_collection(owner_id)
    meta = {k: v for k, v in (metadata or {}).items() if isinstance(v, (str, int, float, bool))}
    col.upsert(ids=[memory_id], embeddings=[embedding], documents=[text[:8000]], metadatas=[meta])

def store_memories_batch(owner_id, ids, texts, embeddings, metadatas=None):
    if not ids: return
    col = _get_collection(owner_id)
    safe_metas = [{k: v for k, v in m.items() if isinstance(v, (str, int, float, bool))} for m in (metadatas or [{}]*len(ids))]
    col.upsert(ids=ids, embeddings=embeddings, documents=[t[:8000] for t in texts], metadatas=safe_metas)

def search_memories(owner_id, query_embedding, top_k=5, where=None):
    col = _get_collection(owner_id)
    total = col.count()
    if total == 0: return []
    kwargs = {"query_embeddings": [query_embedding], "n_results": min(top_k, total), "include": ["documents", "metadatas", "distances"]}
    if where: kwargs["where"] = where
    try:
        results = col.query(**kwargs)
    except Exception as exc:
        log.warning("CHROMA_SEARCH_FAILED owner=%d: %s", owner_id, exc)
        return []
    memories = []
    if results and results["ids"] and results["ids"][0]:
        for i in range(len(results["ids"][0])):
            distance = results["distances"][0][i] if results["distances"] else 0
            memories.append({"id": results["ids"][0][i], "text": results["documents"][0][i] if results["documents"] else "", "similarity": 1.0 - distance, "metadata": results["metadatas"][0][i] if results["metadatas"] else {}})
    return memories

def delete_memory(owner_id, memory_id):
    try: _get_collection(owner_id).delete(ids=[memory_id])
    except: pass

def delete_memories_by_type(owner_id, memory_type):
    try: _get_collection(owner_id).delete(where={"memory_type": memory_type})
    except Exception as exc: log.warning("CHROMA_DELETE_BY_TYPE_FAILED: %s", exc)

def count_memories(owner_id):
    return _get_collection(owner_id).count()

def reset_owner(owner_id):
    try: _get_client().delete_collection(f"owner_{owner_id}")
    except: pass
