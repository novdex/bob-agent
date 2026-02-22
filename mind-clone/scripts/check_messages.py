import sqlite3
conn = sqlite3.connect(r'C:\Users\mader\.mind-clone\mind_clone.db')
cursor = conn.cursor()
cursor.execute('SELECT role, substr(content, 1, 50), created_at FROM conversation_messages ORDER BY id DESC LIMIT 5')
for row in cursor.fetchall():
    print(f"{row[0]}: {row[1]}... [{row[2]}]")
conn.close()
