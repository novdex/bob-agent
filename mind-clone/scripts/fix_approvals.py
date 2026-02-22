import sqlite3
from datetime import datetime

conn = sqlite3.connect(r'C:\Users\mader\.mind-clone\mind_clone.db')
cursor = conn.cursor()

print("BEFORE: Checking pending approvals...")
cursor.execute('SELECT COUNT(*) FROM approval_requests WHERE status = ?', ('pending',))
count = cursor.fetchone()[0]
print(f"  Pending approvals: {count}")

if count > 0:
    print("\nClearing all pending approvals...")
    cursor.execute('''
        UPDATE approval_requests 
        SET status = ?, decided_at = ?, decision_reason = ?
        WHERE status = ?
    ''', ('approved', datetime.now().isoformat(), 'Bulk approval by user', 'pending'))
    conn.commit()
    
    cursor.execute('SELECT COUNT(*) FROM approval_requests WHERE status = ?', ('pending',))
    new_count = cursor.fetchone()[0]
    print(f"\nAFTER: Pending approvals: {new_count}")
    print(f"  ✅ Cleared {count} pending approvals")
else:
    print("  No pending approvals to clear")

conn.close()
print("\nStep 1 Complete!")
