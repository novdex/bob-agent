import sqlite3
conn = sqlite3.connect(r'C:\Users\mader\.mind-clone\mind_clone.db')
cursor = conn.cursor()

# Check pending approvals
cursor.execute('PRAGMA table_info(approval_requests)')
print("Approval Requests Schema:")
for col in cursor.fetchall():
    print(f"  {col[1]}: {col[2]}")

cursor.execute('SELECT id, tool_name, status, created_at FROM approval_requests WHERE status = ? ORDER BY id DESC', ('pending',))
print("\nPENDING APPROVALS:")
for row in cursor.fetchall():
    print(f"  ID: {row[0]} | Tool: {row[1]} | Status: {row[2]} | Created: {row[3]}")

# Check for errors
cursor.execute('SELECT model_name, status, tool_name, estimated_cost_usd, created_at FROM usage_ledger WHERE status = ? ORDER BY id DESC LIMIT 5', ('error',))
print("\nRECENT ERRORS:")
for row in cursor.fetchall():
    print(f"  {row[0]} | {row[1]} | {row[2]} | ${row[3]} | {row[4]}")

conn.close()
