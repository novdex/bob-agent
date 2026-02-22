import sqlite3
conn = sqlite3.connect(r'C:\Users\mader\.mind-clone\mind_clone.db')
cursor = conn.cursor()

# Check for pending approvals
cursor.execute('SELECT COUNT(*) FROM approval_requests WHERE status = ?', ('pending',))
pending = cursor.fetchone()[0]
print(f"Pending approvals: {pending}")

# Check recent usage ledger for LLM calls
cursor.execute('SELECT event_type, model_name, status, estimated_cost_usd, created_at FROM usage_ledger ORDER BY id DESC LIMIT 10')
print("\nRecent Usage:")
for row in cursor.fetchall():
    print(f"  {row[0]} | {row[1]} | {row[2]} | ${row[3]} | {row[4]}")

# Check for any errors in conversation
cursor.execute('SELECT role, substr(content, 1, 100), created_at FROM conversation_messages WHERE role = ? ORDER BY id DESC LIMIT 3', ('assistant',))
print("\nRecent Assistant Messages:")
for row in cursor.fetchall():
    if row[1]:
        print(f"  [{row[2]}] {row[1]}...")
    else:
        print(f"  [{row[2]}] (empty)")

conn.close()
