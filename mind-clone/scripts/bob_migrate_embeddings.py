#!/usr/bin/env python3
"""Migrate memory embeddings from GloVe to sentence-transformers + ChromaDB."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

def migrate_owner(owner_id):
    from mind_clone.database.session import SessionLocal
    from mind_clone.database.models import MemoryVector, EpisodicMemory
    from mind_clone.agent.vectors import get_embedding, embedding_to_bytes
    from mind_clone.services.memory.chroma_store import store_memories_batch
    db = SessionLocal()
    counts = {"memory_vectors": 0, "episodic": 0}
    try:
        rows = db.query(MemoryVector).filter(MemoryVector.owner_id == owner_id).all()
        ids, texts, embs, metas = [], [], [], []
        for r in rows:
            t = r.text_preview or ""
            if not t.strip(): continue
            v = get_embedding(t)
            r.embedding = embedding_to_bytes(v)
            ids.append(f"{r.memory_type}_{r.id}")
            texts.append(t); embs.append(v.tolist())
            metas.append({"memory_type": r.memory_type or "", "ref_id": int(r.ref_id or 0)})
            counts["memory_vectors"] += 1
        db.commit()
        if ids: store_memories_batch(owner_id, ids, texts, embs, metas)
        eps = db.query(EpisodicMemory).filter(EpisodicMemory.owner_id == owner_id).limit(500).all()
        eids, etexts, eembs, emetas = [], [], [], []
        for e in eps:
            t = e.situation or ""
            if not t.strip(): continue
            v = get_embedding(t)
            eids.append(f"episode_{e.id}"); etexts.append(t); eembs.append(v.tolist())
            emetas.append({"memory_type": "episodic", "ref_id": int(e.id), "outcome": e.outcome or "unknown"})
            counts["episodic"] += 1
        if eids: store_memories_batch(owner_id, eids, etexts, eembs, emetas)
    finally: db.close()
    return counts

if __name__ == "__main__":
    from mind_clone.agent.vectors import get_embedding
    print("Loading model..."); get_embedding("warmup"); print("Done.")
    from mind_clone.database.session import SessionLocal
    from mind_clone.database.models import MemoryVector
    db = SessionLocal()
    owner_ids = [r[0] for r in db.query(MemoryVector.owner_id).distinct().all()]
    db.close()
    if not owner_ids: print("No memories to migrate."); sys.exit(0)
    for oid in owner_ids:
        print(f"Owner {oid}: ", end=""); print(migrate_owner(oid))
    print("Migration complete.")
