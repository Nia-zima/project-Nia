# backend/scripts/debug_check_db.py
from __future__ import annotations

import sys
from pathlib import Path

# プロジェクトルートをパスに追加
PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.append(str(PROJECT_ROOT))

from backend.core.db import get_conn, health_check

def print_section(title: str) -> None:
    print(f"\n{'='*10} {title} {'='*10}")

def view_messages(limit: int = 5) -> None:
    conn = get_conn()
    try:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(messages)").fetchall()}
        ts_col = "ts" if "ts" in cols else "created_at"
        rows = conn.execute(
            f"SELECT id, {ts_col} as ts, role, content_json FROM messages ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        print_section(f"Recent Messages (Max {limit})")
        if not rows:
            print("No messages found.")
        for r in rows:
            print(f"[{r['ts']}] {r['role']}: {r['content_json'][:50]}...")
    finally:
        conn.close()

def view_memories(limit: int = 5) -> None:
    conn = get_conn()
    try:
        rows = conn.execute("SELECT id, created_at, summary, importance, processed FROM daily_memories ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
        print_section(f"Recent Memories (Max {limit})")
        if not rows:
            print("No memories found.")
        for r in rows:
            status = "[Processed]" if r['processed'] else "[PENDING]"
            print(f"{status} Imp:{r['importance']:.2f} | {r['summary'][:60]}...")
    finally:
        conn.close()

def view_dreams(limit: int = 3) -> None:
    conn = get_conn()
    try:
        rows = conn.execute("SELECT id, created_at, mood, dream_text, presented FROM dreams ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
        print_section(f"Recent Dreams (Max {limit})")
        if not rows:
            print("No dreams found.")
        for r in rows:
            status = "[SHOWN]" if r['presented'] else "[UNREAD]"
            print(f"{status} Mood:{r['mood']} | {r['dream_text'][:60]}...")
    finally:
        conn.close()

def view_events(limit: int = 3) -> None:
    conn = get_conn()
    try:
        rows = conn.execute("SELECT id, ts, event_type, payload_json FROM events ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        print_section(f"Recent Telemetry Events (Max {limit})")
        if not rows:
            print("No events found (new DB?).")
        for r in rows:
            print(f"[{r['ts']}] {r['event_type']}: {r['payload_json'][:60]}...")
    finally:
        conn.close()

def view_memory_events(limit: int = 5) -> None:
    conn = get_conn()
    try:
        rows = conn.execute(
            """
            SELECT event_id, created_at, thread_id, event_type, message_id, turn_id, payload_json
            FROM memory_events
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        print_section(f"Recent Memory Events (Max {limit})")
        if not rows:
            print("No memory_events found.")
        for r in rows:
            print(
                f"[{r['created_at']}] {r['event_type']} "
                f"thread={r['thread_id']} msg={r['message_id']} turn={r['turn_id']} "
                f"payload={str(r['payload_json'])[:80]}..."
            )
    finally:
        conn.close()

def main() -> None:
    print("Checking DB Connection...")
    hc = health_check()
    print(f"DB Path: {hc.get('db_path')}")
    print(f"Integrity: {hc.get('integrity_check')}")
    print(f"Tables: {hc.get('tables')}")
    
    view_messages()
    view_memories()
    view_memory_events()
    view_dreams()
    view_events()
    print("\nDONE.")

if __name__ == "__main__":
    main()
