from datetime import datetime

from fastapi import APIRouter

from backend.core.db import get_conn

router = APIRouter()


@router.get("/summary")
def get_stats_summary():
    """会話統計サマリーを取得"""
    conn = get_conn()
    cursor = conn.cursor()

    try:
        # 今日の日付
        today = datetime.now().strftime("%Y-%m-%d")

        # 各種統計を取得
        stats = {}

        # 総イベント数
        cursor.execute("SELECT COUNT(*) FROM events")
        stats["total_events"] = cursor.fetchone()[0]

        # 今日の会話数
        cursor.execute(
            """
            SELECT COUNT(*) FROM events
            WHERE event_type = 'chat_received'
            AND ts LIKE ?
            """,
            (f"{today}%",),
        )
        stats["today_chats"] = cursor.fetchone()[0]

        # 総会話数
        cursor.execute("SELECT COUNT(*) FROM events WHERE event_type = 'chat_received'")
        stats["total_chats"] = cursor.fetchone()[0]

        # 記憶統計（現行パイプラインに合わせる）
        # 候補数 = memory_events の候補系イベント数
        try:
            cursor.execute(
                """
                SELECT COUNT(*)
                FROM memory_events
                WHERE event_type IN ('capture_recorded', 'memory_pending')
                """
            )
            stats["memory_candidates"] = cursor.fetchone()[0]
        except Exception:
            stats["memory_candidates"] = 0

        # pending = memory_pending - (approved/rejected ref_event_id)
        try:
            cursor.execute(
                """
                SELECT COUNT(*)
                FROM memory_events p
                WHERE p.event_type = 'memory_pending'
                  AND p.event_id NOT IN (
                    SELECT COALESCE(CAST(json_extract(a.payload_json, '$.ref_event_id') AS TEXT), '')
                    FROM memory_events a
                    WHERE a.event_type IN ('memory_approved', 'memory_rejected')
                      AND json_extract(a.payload_json, '$.ref_event_id') IS NOT NULL
                  )
                """
            )
            stats["memory_pending"] = cursor.fetchone()[0]
        except Exception:
            stats["memory_pending"] = 0

        try:
            cursor.execute("SELECT COUNT(*) FROM memory_events WHERE event_type = 'memory_approved'")
            stats["memory_approved"] = cursor.fetchone()[0]
        except Exception:
            stats["memory_approved"] = 0

        try:
            cursor.execute("SELECT COUNT(*) FROM memory_events WHERE event_type = 'memory_rejected'")
            stats["memory_rejected"] = cursor.fetchone()[0]
        except Exception:
            stats["memory_rejected"] = 0

        # 記録済 = 思考/エピソードとして保存されたイベント数
        try:
            cursor.execute(
                """
                SELECT COUNT(*)
                FROM memory_events
                WHERE event_type IN ('thought_registered', 'episode_added')
                """
            )
            stats["memory_written"] = cursor.fetchone()[0]
        except Exception:
            stats["memory_written"] = 0

        # 最後の会話時刻
        cursor.execute(
            """
            SELECT ts FROM events
            WHERE event_type = 'chat_received'
            ORDER BY id DESC LIMIT 1
            """
        )
        row = cursor.fetchone()
        stats["last_chat_time"] = row[0] if row else None

        return stats
    finally:
        conn.close()
