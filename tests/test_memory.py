from backend.long_term_memory import add_memory, query_memory
import sqlite3

output = []
output.append("--- Testing Memory ---")

# 1. Read all memories
conn = sqlite3.connect('ai_buddy_memory.sqlite')
cursor = conn.cursor()
output.append("Current DB Content:")
for row in cursor.execute('SELECT * FROM long_term_memories'):
    output.append(str(row))
conn.close()

# 2. Test Query
output.append("\n--- Testing query_memory('ジュン') ---")
output.append(query_memory("ジュン"))

output.append("\n--- Testing query_memory('仕事') ---")
output.append(query_memory("仕事"))

with open("memory_dump.txt", "w", encoding="utf-8") as f:
    f.write("\n".join(output))
