import asyncio

from backend.core.db import get_conn
from backend.services.memory_manager import memory_manager

output = []
output.append("--- Testing Memory ---")

# 1. Read all memories (unified DB)
conn = get_conn()
try:
    cursor = conn.cursor()
    output.append("Current memories table:")
    for row in cursor.execute('SELECT id, ts, content, tags_json, confidence, surprise, source, thread_id FROM memories ORDER BY ts DESC LIMIT 50'):
        output.append(str(dict(row)))
finally:
    conn.close()

# 2. Test Query
output.append("\n--- Testing recall_memories('ジュン') ---")
results = asyncio.run(memory_manager.recall_memories(query="ジュン", limit=5))
if results:
    output.append("\n".join([f"・{r.get('content', '')}" for r in results]))
else:
    output.append("(no results)")

output.append("\n--- Testing recall_memories('仕事') ---")
results = asyncio.run(memory_manager.recall_memories(query="仕事", limit=5))
if results:
    output.append("\n".join([f"・{r.get('content', '')}" for r in results]))
else:
    output.append("(no results)")

with open("memory_dump.txt", "w", encoding="utf-8") as f:
    f.write("\n".join(output))
