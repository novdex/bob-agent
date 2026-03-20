"""Run DB migrations for new columns added today."""
import sys
sys.path.insert(0, 'src')
import sqlalchemy as sa
from mind_clone.database.session import SessionLocal

db = SessionLocal()
conn = db.connection()

migrations = [
    "ALTER TABLE episodic_memories ADD COLUMN importance REAL NOT NULL DEFAULT 1.0",
    "ALTER TABLE episodic_memories ADD COLUMN recall_count INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE episodic_memories ADD COLUMN last_recalled_at DATETIME",
    "ALTER TABLE self_improvement_notes ADD COLUMN importance REAL NOT NULL DEFAULT 1.0",
    "ALTER TABLE self_improvement_notes ADD COLUMN recall_count INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE self_improvement_notes ADD COLUMN last_recalled_at DATETIME",
    """CREATE TABLE IF NOT EXISTS experiment_logs (
        id INTEGER PRIMARY KEY,
        owner_id INTEGER NOT NULL,
        hypothesis_title VARCHAR NOT NULL,
        target_file VARCHAR,
        score_before REAL NOT NULL DEFAULT 0.0,
        score_after REAL NOT NULL DEFAULT 0.0,
        improved BOOLEAN NOT NULL DEFAULT 0,
        committed BOOLEAN NOT NULL DEFAULT 0,
        reverted BOOLEAN NOT NULL DEFAULT 0,
        tests_passed BOOLEAN NOT NULL DEFAULT 0,
        error_msg TEXT,
        hypothesis_json TEXT NOT NULL DEFAULT '{}',
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )""",
    """CREATE TABLE IF NOT EXISTS memory_links (
        id INTEGER PRIMARY KEY,
        owner_id INTEGER NOT NULL,
        src_type VARCHAR NOT NULL,
        src_id INTEGER NOT NULL,
        tgt_type VARCHAR NOT NULL,
        tgt_id INTEGER NOT NULL,
        relation VARCHAR NOT NULL DEFAULT 'related',
        weight REAL NOT NULL DEFAULT 1.0,
        note TEXT,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )""",
]

for sql in migrations:
    try:
        conn.execute(sa.text(sql))
        print(f"OK: {sql[:70]}")
    except Exception as e:
        err = str(e).lower()
        if "duplicate column" in err or "already exists" in err:
            print(f"SKIP (already exists): {sql[:50]}")
        else:
            print(f"ERR: {str(e)[:100]}")

conn.commit()
db.close()
print("\nMigration complete.")
