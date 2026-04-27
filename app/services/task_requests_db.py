import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from flask import current_app, has_app_context


def _db_enabled(config):
    return bool(config.get("TASK_DB_ENABLED", False))


def _resolve_db_path(raw_path):
    path = Path(raw_path)
    if path.is_absolute():
        return path
    return Path(__file__).resolve().parents[2] / path


def _connect(db_path):
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return sqlite3.connect(db_path)


def _create_table(conn):
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS task_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_key TEXT NOT NULL,
            task_label TEXT NOT NULL,
            output_type TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )


def _create_chat_log_table(conn):
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS chat_query_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_query TEXT NOT NULL,
            bot_response TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            detected_intent TEXT,
            workflow_type TEXT,
            status TEXT,
            is_fallback INTEGER NOT NULL DEFAULT 0,
            is_timeout INTEGER NOT NULL DEFAULT 0,
            is_confused_query INTEGER NOT NULL DEFAULT 0,
            is_repeated_query INTEGER NOT NULL DEFAULT 0,
            normalized_query TEXT NOT NULL
        )
        """
    )


def initialize_task_db(app):
    if not _db_enabled(app.config):
        return

    db_path = _resolve_db_path(app.config.get("TASK_DB_PATH", "task_requests.db"))
    with _connect(db_path) as conn:
        _create_table(conn)
        conn.commit()


def initialize_query_log_db(app):
    if not app.config.get("QUERY_LOG_DB_ENABLED", True):
        return

    db_path = _resolve_db_path(app.config.get("QUERY_LOG_DB_PATH", "chat_query_logs.db"))
    with _connect(db_path) as conn:
        _create_chat_log_table(conn)
        conn.commit()


def save_task_request(task_key, task_label, output_type, payload):
    if not _db_enabled(current_app.config):
        return None

    db_path = _resolve_db_path(current_app.config.get("TASK_DB_PATH", "task_requests.db"))
    created_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    payload_json = json.dumps(payload, ensure_ascii=True)

    with _connect(db_path) as conn:
        _create_table(conn)
        cursor = conn.execute(
            """
            INSERT INTO task_requests (task_key, task_label, output_type, payload_json, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (task_key, task_label, output_type, payload_json, created_at),
        )
        conn.commit()
        return int(cursor.lastrowid)


def _query_log_db_enabled():
    return has_app_context() and bool(current_app.config.get("QUERY_LOG_DB_ENABLED", True))


def _normalize_query(text):
    import re

    cleaned = re.sub(r"[^a-zA-Z0-9\s]", " ", (text or "").lower())
    return " ".join(cleaned.split())


def save_chat_log(
    user_query,
    bot_response,
    detected_intent=None,
    workflow_type=None,
    status="answered",
    is_fallback=False,
    is_timeout=False,
    is_confused_query=False,
    is_repeated_query=False,
):
    if not _query_log_db_enabled():
        return None

    db_path = _resolve_db_path(current_app.config.get("QUERY_LOG_DB_PATH", "chat_query_logs.db"))
    timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    normalized_query = _normalize_query(user_query)

    with _connect(db_path) as conn:
        _create_chat_log_table(conn)
        cursor = conn.execute(
            """
            INSERT INTO chat_query_logs (
                user_query,
                bot_response,
                timestamp,
                detected_intent,
                workflow_type,
                status,
                is_fallback,
                is_timeout,
                is_confused_query,
                is_repeated_query,
                normalized_query
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(user_query or "").strip(),
                str(bot_response or "").strip(),
                timestamp,
                detected_intent,
                workflow_type,
                status,
                int(bool(is_fallback)),
                int(bool(is_timeout)),
                int(bool(is_confused_query)),
                int(bool(is_repeated_query)),
                normalized_query,
            ),
        )
        conn.commit()
        return int(cursor.lastrowid)


def list_task_requests(limit=200):
    if not _db_enabled(current_app.config):
        return []

    db_path = _resolve_db_path(current_app.config.get("TASK_DB_PATH", "task_requests.db"))
    with _connect(db_path) as conn:
        _create_table(conn)
        cursor = conn.execute(
            """
            SELECT id, task_key, task_label, output_type, payload_json, created_at
            FROM task_requests
            ORDER BY id DESC
            LIMIT ?
            """,
            (max(1, int(limit)),),
        )
        rows = cursor.fetchall()

    entries = []
    for row in rows:
        payload = {}
        try:
            payload = json.loads(row[4] or "{}")
        except Exception:
            payload = {}

        entries.append(
            {
                "id": row[0],
                "task_key": row[1],
                "task_label": row[2],
                "output_type": row[3],
                "payload": payload,
                "created_at": row[5],
            }
        )

    return entries


def list_chat_logs(limit=200):
    if not _query_log_db_enabled():
        return []

    db_path = _resolve_db_path(current_app.config.get("QUERY_LOG_DB_PATH", "chat_query_logs.db"))
    with _connect(db_path) as conn:
        _create_chat_log_table(conn)
        cursor = conn.execute(
            """
            SELECT
                id,
                user_query,
                bot_response,
                timestamp,
                detected_intent,
                workflow_type,
                status,
                is_fallback,
                is_timeout,
                is_confused_query,
                is_repeated_query,
                normalized_query
            FROM chat_query_logs
            ORDER BY id DESC
            LIMIT ?
            """,
            (max(1, int(limit)),),
        )
        rows = cursor.fetchall()

    entries = []
    for row in rows:
        status = row[6]
        detected_intent = row[4]
        workflow_type = row[5]
        confidence = 0.0 if status in {"unanswered", "fallback", "timeout"} or row[7] or row[8] else 1.0
        entries.append(
            {
                "id": row[0],
                "user_query": row[1],
                "bot_response": row[2],
                "timestamp": row[3],
                "detected_intent": detected_intent,
                "workflow_type": workflow_type,
                "status": status,
                "is_fallback": bool(row[7]),
                "is_timeout": bool(row[8]),
                "is_confused_query": bool(row[9]),
                "is_repeated_query": bool(row[10]),
                "normalized_query": row[11],
                "question": row[1],
                "response": row[2],
                "intent": workflow_type or detected_intent,
                "confidence": confidence,
            }
        )

    return entries


def get_query_insights(limit=10):
    if not _query_log_db_enabled():
        return {
            "top_queries": [],
            "failed_responses": 0,
            "most_requested_services": [],
            "signal_counts": {
                "confused_queries": 0,
                "repeated_queries": 0,
            },
        }

    db_path = _resolve_db_path(current_app.config.get("QUERY_LOG_DB_PATH", "chat_query_logs.db"))
    with _connect(db_path) as conn:
        _create_chat_log_table(conn)

        top_queries = conn.execute(
            """
            SELECT
                normalized_query,
                MIN(user_query) AS sample_query,
                COUNT(*) AS total
            FROM chat_query_logs
            WHERE TRIM(normalized_query) != ''
            GROUP BY normalized_query
            ORDER BY total DESC, sample_query ASC
            LIMIT ?
            """,
            (max(1, int(limit)),),
        ).fetchall()

        failed_responses = conn.execute(
            """
            SELECT COUNT(*)
            FROM chat_query_logs
            WHERE is_fallback = 1
               OR is_timeout = 1
               OR LOWER(COALESCE(status, '')) IN ('unanswered', 'fallback', 'timeout')
            """
        ).fetchone()[0]

        services = conn.execute(
            """
            SELECT
                COALESCE(
                    NULLIF(workflow_type, ''),
                    NULLIF(detected_intent, ''),
                    'Unclassified'
                ) AS service,
                COUNT(*) AS total
            FROM chat_query_logs
            WHERE COALESCE(
                NULLIF(workflow_type, ''),
                NULLIF(detected_intent, ''),
                'Unclassified'
            ) != 'Unclassified'
            GROUP BY service
            ORDER BY total DESC, service ASC
            LIMIT ?
            """,
            (max(1, int(limit)),),
        ).fetchall()

        signal_counts = conn.execute(
            """
            SELECT
                SUM(CASE WHEN is_confused_query = 1 THEN 1 ELSE 0 END) AS confused_queries,
                SUM(CASE WHEN is_repeated_query = 1 THEN 1 ELSE 0 END) AS repeated_queries
            FROM chat_query_logs
            """
        ).fetchone()

    return {
        "top_queries": [
            {
                "query": row[1],
                "normalized_query": row[0],
                "count": row[2],
            }
            for row in top_queries
        ],
        "failed_responses": int(failed_responses or 0),
        "most_requested_services": [
            {
                "service": row[0],
                "count": row[1],
            }
            for row in services
        ],
        "signal_counts": {
            "confused_queries": int((signal_counts[0] if signal_counts and signal_counts[0] is not None else 0)),
            "repeated_queries": int((signal_counts[1] if signal_counts and signal_counts[1] is not None else 0)),
        },
    }
