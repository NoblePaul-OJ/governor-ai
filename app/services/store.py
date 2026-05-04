import json
import sqlite3
import threading
import uuid
from datetime import datetime
from pathlib import Path

from flask import has_app_context, session

from app.services.task_requests_db import get_query_insights, save_chat_log

QUERY_LOGS = []
QUERY_QUERY_COUNTS = {}
STORE_DATA = {}
STORE_LOCK = threading.RLock()
STORE_DB_PATH = Path(__file__).resolve().parents[1] / "data" / "user_sessions.db"
SESSION_PROFILE_KEY = "_governor_profile_session_id"
CONVERSATION_STATE = {
    "topic": None,
    "intent": None,
    "entities": {},
    "history": [],
    "state_version": 0,
    "task_flow": {
        "active_task": None,
        "current_step": None,
        "step_index": 0,
        "collected": {},
        "completed_task": None,
        "last_output": None,
        "state_version": 0,
    },
}

_CONFUSION_PHRASES = (
    "i don t understand",
    "i dont understand",
    "i do not understand",
    "i m confused",
    "im confused",
    "not sure",
    "please repeat",
    "say again",
)


def _now_iso():
    return datetime.now().isoformat(timespec="seconds")


def _normalize_query(text):
    import re

    cleaned = re.sub(r"[^a-zA-Z0-9\s]", " ", (text or "").lower())
    return " ".join(cleaned.split())


def _normalize_session_id(session_id):
    return str(session_id or "").strip()


def _is_confused_query(question):
    normalized = _normalize_query(question)
    return any(phrase in normalized for phrase in _CONFUSION_PHRASES)


def _table_exists(conn, table_name):
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type IN ('table', 'view') AND name = ?",
        (table_name,),
    ).fetchone()
    return row is not None


def _normalize_notes(notes):
    if isinstance(notes, list):
        values = notes
    elif isinstance(notes, str):
        values = [notes] if notes.strip() else []
    else:
        values = []

    cleaned = []
    for item in values:
        text = str(item or "").strip()
        if text and text not in cleaned:
            cleaned.append(text)
    return cleaned


def _serialize_notes(notes):
    cleaned = _normalize_notes(notes)
    return json.dumps(cleaned, ensure_ascii=False) if cleaned else None


def _deserialize_profile(profile_json):
    try:
        profile = json.loads(profile_json or "{}")
    except json.JSONDecodeError:
        profile = {}
    if isinstance(profile, dict):
        return profile
    return {}


def _deserialize_notes(notes_json):
    if not notes_json:
        return []

    try:
        notes = json.loads(notes_json)
    except json.JSONDecodeError:
        notes = []

    return _normalize_notes(notes)


def _profile_to_columns(profile):
    profile = dict(profile or {})
    columns = {}
    for key in ("name", "department", "level"):
        value = str(profile.get(key) or "").strip()
        columns[key] = value or None
    columns["notes_json"] = _serialize_notes(profile.get("notes"))
    return columns


def _user_row_to_profile(row):
    if not row:
        return {}

    profile = {}
    for key in ("name", "department", "level"):
        value = str(row[key] or "").strip()
        if value:
            profile[key] = value

    notes = _deserialize_notes(row["notes_json"])
    if notes:
        profile["notes"] = notes

    return profile


def _user_row_to_record(row):
    if not row:
        return {}

    record = {
        "id": row["id"],
        "session_id": row["session_id"],
        "name": str(row["name"] or "").strip() or None,
        "department": str(row["department"] or "").strip() or None,
        "level": str(row["level"] or "").strip() or None,
        "pending_field": str(row["pending_field"] or "").strip() or None,
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }

    notes = _deserialize_notes(row["notes_json"])
    if notes:
        record["notes"] = notes

    return record


def _ensure_user_exists(conn, session_id):
    now = _now_iso()
    conn.execute(
        """
        INSERT OR IGNORE INTO users (
            session_id,
            name,
            department,
            level,
            pending_field,
            notes_json,
            created_at,
            updated_at
        )
        VALUES (?, NULL, NULL, NULL, NULL, NULL, ?, ?)
        """,
        (session_id, now, now),
    )


def _upsert_user_profile(conn, session_id, profile, pending_field=None):
    session_id = _normalize_session_id(session_id)
    if not session_id:
        return

    columns = _profile_to_columns(profile)
    created_row = conn.execute(
        "SELECT created_at FROM users WHERE session_id = ?",
        (session_id,),
    ).fetchone()
    created_at = created_row["created_at"] if created_row else _now_iso()
    updated_at = _now_iso()
    conn.execute(
        """
        INSERT INTO users (
            session_id,
            name,
            department,
            level,
            pending_field,
            notes_json,
            created_at,
            updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(session_id) DO UPDATE SET
            name = excluded.name,
            department = excluded.department,
            level = excluded.level,
            pending_field = excluded.pending_field,
            notes_json = excluded.notes_json,
            updated_at = excluded.updated_at
        """,
        (
            session_id,
            columns["name"],
            columns["department"],
            columns["level"],
            pending_field,
            columns["notes_json"],
            created_at,
            updated_at,
        ),
    )


def _migrate_legacy_tables(conn):
    if _table_exists(conn, "user_sessions"):
        rows = conn.execute(
            "SELECT session_id, profile_json, pending_field, updated_at FROM user_sessions"
        ).fetchall()
        for row in rows:
            profile = _deserialize_profile(row["profile_json"])
            _upsert_user_profile(
                conn,
                row["session_id"],
                profile,
                pending_field=row["pending_field"],
            )

    if _table_exists(conn, "conversation_messages"):
        legacy_count = conn.execute(
            "SELECT COUNT(*) AS count FROM conversation_messages"
        ).fetchone()["count"]
        message_count = conn.execute(
            "SELECT COUNT(*) AS count FROM messages"
        ).fetchone()["count"]
        if legacy_count and not message_count:
            conn.execute(
                """
                INSERT INTO messages (session_id, role, message, timestamp)
                SELECT session_id, role, message, created_at
                FROM conversation_messages
                ORDER BY id
                """
            )


def _ensure_store_db():
    STORE_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(STORE_DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL UNIQUE,
                name TEXT,
                department TEXT,
                level TEXT,
                pending_field TEXT,
                notes_json TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                role TEXT NOT NULL,
                message TEXT NOT NULL,
                timestamp TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_messages_session_id_id
            ON messages(session_id, id)
            """
        )
        _migrate_legacy_tables(conn)
        conn.commit()


def _connect_store():
    _ensure_store_db()
    conn = sqlite3.connect(STORE_DB_PATH, timeout=5)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def add_log(
    question,
    intent,
    response,
    confidence,
    status="answered",
    workflow_type=None,
    is_fallback=False,
    is_timeout=False,
):
    if not QUERY_LOGS and QUERY_QUERY_COUNTS:
        QUERY_QUERY_COUNTS.clear()

    normalized = _normalize_query(question)
    repeated = bool(normalized and QUERY_QUERY_COUNTS.get(normalized, 0) > 0)
    confused = _is_confused_query(question)

    entry = {
        "id": len(QUERY_LOGS) + 1,
        "question": question,
        "intent": intent,
        "response": response,
        "confidence": confidence,
        "status": status,
        "timestamp": _now_iso(),
        "workflow_type": workflow_type,
        "is_fallback": bool(is_fallback),
        "is_timeout": bool(is_timeout),
        "is_confused_query": confused,
        "is_repeated_query": repeated,
    }
    QUERY_LOGS.append(entry)
    if normalized:
        QUERY_QUERY_COUNTS[normalized] = QUERY_QUERY_COUNTS.get(normalized, 0) + 1

    try:
        save_chat_log(
            user_query=question,
            bot_response=response,
            detected_intent=intent,
            workflow_type=workflow_type,
            status=status,
            is_fallback=is_fallback,
            is_timeout=is_timeout,
            is_confused_query=confused,
            is_repeated_query=repeated,
        )
    except Exception:
        pass

    return entry


def get_conversation_state():
    return CONVERSATION_STATE


def get_session_id():
    if has_app_context():
        session_id = session.get(SESSION_PROFILE_KEY)
        if not session_id:
            session_id = uuid.uuid4().hex
            session[SESSION_PROFILE_KEY] = session_id
            session.modified = True
        return session_id

    return "default-session"


def create_user(session_id):
    session_id = _normalize_session_id(session_id)
    if not session_id:
        return {}

    with STORE_LOCK:
        with _connect_store() as conn:
            _ensure_user_exists(conn, session_id)
            conn.commit()
        load_store()
    return get_user(session_id)


def get_user(session_id):
    session_id = _normalize_session_id(session_id)
    if not session_id:
        return {}

    with STORE_LOCK:
        with _connect_store() as conn:
            _ensure_user_exists(conn, session_id)
            conn.commit()
            row = conn.execute(
                """
                SELECT id, session_id, name, department, level, pending_field, notes_json, created_at, updated_at
                FROM users
                WHERE session_id = ?
                """,
                (session_id,),
            ).fetchone()

    return _user_row_to_record(row)


def load_store():
    global STORE_DATA
    with STORE_LOCK:
        with _connect_store() as conn:
            rows = conn.execute(
                """
                SELECT id, session_id, name, department, level, pending_field, notes_json, created_at, updated_at
                FROM users
                """
            ).fetchall()

        data = {}
        for row in rows:
            data[row["session_id"]] = {
                "profile": _user_row_to_profile(row),
                "pending_field": row["pending_field"],
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            }
        STORE_DATA = data
        return STORE_DATA


def save_store(data):
    global STORE_DATA
    with STORE_LOCK:
        payload = dict(data or {})
        with _connect_store() as conn:
            conn.execute("DELETE FROM users")
            for session_id, bucket in payload.items():
                if not isinstance(bucket, dict):
                    bucket = {}
                profile = dict(bucket.get("profile", {}))
                pending_field = bucket.get("pending_field")
                _upsert_user_profile(conn, session_id, profile, pending_field=pending_field)
            conn.commit()
        STORE_DATA = payload
        return STORE_DATA


def _profile_only(user_record):
    profile = {}
    for key in ("name", "department", "level"):
        value = str(user_record.get(key) or "").strip()
        if value:
            profile[key] = value

    notes = _normalize_notes(user_record.get("notes"))
    if notes:
        profile["notes"] = notes
    return profile


def get_user_profile(session_id):
    return _profile_only(get_user(session_id))


def get_user_memory(session_id):
    return get_user_profile(session_id)


def set_user_profile(session_id, profile):
    session_id = _normalize_session_id(session_id)
    if not session_id:
        return {}

    normalized = dict(profile or {}) if isinstance(profile, dict) else {}
    current = get_user(session_id)
    merged = dict(current or {})

    for key in ("name", "department", "level"):
        value = str(normalized.get(key) or "").strip()
        if value:
            merged[key] = value

    if "notes" in normalized:
        merged["notes"] = _normalize_notes(normalized.get("notes"))

    pending_field = current.get("pending_field")
    with STORE_LOCK:
        with _connect_store() as conn:
            _upsert_user_profile(conn, session_id, merged, pending_field=pending_field)
            conn.commit()
        load_store()

    return get_user_profile(session_id)


def clear_user_profile(session_id):
    session_id = _normalize_session_id(session_id)
    if not session_id:
        return {}

    with STORE_LOCK:
        with _connect_store() as conn:
            conn.execute("DELETE FROM users WHERE session_id = ?", (session_id,))
            conn.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
            conn.commit()
        load_store()
    return {}


def update_user(session_id, field, value):
    session_id = _normalize_session_id(session_id)
    field = str(field or "").strip()
    if not session_id or not field:
        return get_user(session_id)

    current = get_user(session_id)
    if field == "notes":
        notes = _normalize_notes(current.get("notes"))
        values = value if isinstance(value, list) else [value]
        for item in values:
            text = str(item or "").strip()
            if text and text not in notes:
                notes.append(text)
        current["notes"] = notes
    elif field in {"name", "department", "level"}:
        text = str(value or "").strip()
        if text:
            current[field] = text
    elif field == "pending_field":
        current["pending_field"] = str(value or "").strip() or None
    else:
        return current

    with STORE_LOCK:
        with _connect_store() as conn:
            _upsert_user_profile(
                conn,
                session_id,
                current,
                pending_field=current.get("pending_field"),
            )
            conn.commit()
        load_store()

    return get_user(session_id)


def update_user_memory(session_id, data):
    session_id = _normalize_session_id(session_id)
    if not session_id:
        return {}

    payload = data if isinstance(data, dict) else {}
    current = get_user(session_id)
    profile = dict(current or {})

    for key, value in payload.items():
        key = str(key or "").strip()
        if not key:
            continue
        if key == "notes":
            notes = _normalize_notes(profile.get("notes"))
            values = value if isinstance(value, list) else [value]
            for item in values:
                text = str(item or "").strip()
                if text and text not in notes:
                    notes.append(text)
            profile["notes"] = notes
            continue

        text = str(value or "").strip()
        if text:
            profile[key] = text

    return set_user_profile(session_id, profile)


def set_user_value(session_id, key, value):
    key = str(key or "").strip()
    if not key:
        return get_user_profile(session_id)

    if key in {"name", "department", "level", "notes", "pending_field"}:
        return update_user(session_id, key, value)

    profile = get_user_profile(session_id)
    profile[key] = str(value or "").strip()
    return set_user_profile(session_id, profile)


def get_user_value(session_id, key):
    key = str(key or "").strip()
    user = get_user(session_id)
    if key == "notes":
        return user.get("notes")
    return user.get(key)


def save_message(session_id, role, message):
    session_id = _normalize_session_id(session_id)
    role = str(role or "").strip().lower()
    content = str(message or "").strip()
    if not session_id or role not in {"user", "assistant"} or not content:
        return None

    timestamp = _now_iso()
    with STORE_LOCK:
        with _connect_store() as conn:
            _ensure_user_exists(conn, session_id)
            conn.execute(
                """
                INSERT INTO messages (session_id, role, message, timestamp)
                VALUES (?, ?, ?, ?)
                """,
                (session_id, role, content, timestamp),
            )
            conn.commit()

    return {"session_id": session_id, "role": role, "message": content}


def get_recent_messages(session_id, limit=5):
    session_id = _normalize_session_id(session_id)
    if not session_id:
        return []

    try:
        limit = int(limit)
    except (TypeError, ValueError):
        limit = 5
    limit = max(1, limit)

    with STORE_LOCK:
        with _connect_store() as conn:
            rows = conn.execute(
                """
                SELECT role, message, timestamp
                FROM messages
                WHERE session_id = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (session_id, limit),
            ).fetchall()

    return [
        {
            "role": row["role"],
            "content": row["message"],
            "created_at": row["timestamp"],
        }
        for row in reversed(rows)
    ]


def get_conversation_history(session_id, limit=5):
    return get_recent_messages(session_id, limit=limit)


def set_pending_field(session_id, field):
    session_id = _normalize_session_id(session_id)
    field = str(field or "").strip() or None
    current = get_user(session_id)
    current["pending_field"] = field

    with STORE_LOCK:
        with _connect_store() as conn:
            _upsert_user_profile(conn, session_id, current, pending_field=field)
            conn.commit()
        load_store()
    return field


def get_pending_field(session_id):
    session_id = _normalize_session_id(session_id)
    if not session_id:
        return None

    with STORE_LOCK:
        with _connect_store() as conn:
            row = conn.execute(
                "SELECT pending_field FROM users WHERE session_id = ?",
                (session_id,),
            ).fetchone()

    if not row:
        return None
    pending_field = row["pending_field"]
    return pending_field if pending_field else None


def clear_pending_field(session_id):
    session_id = _normalize_session_id(session_id)
    if not session_id:
        return None

    current = get_user(session_id)
    current["pending_field"] = None

    with STORE_LOCK:
        with _connect_store() as conn:
            _upsert_user_profile(conn, session_id, current, pending_field=None)
            conn.commit()
        load_store()
    return None


def reset_conversation_state():
    CONVERSATION_STATE["state_version"] = CONVERSATION_STATE.get("state_version", 0) + 1
    CONVERSATION_STATE["topic"] = None
    CONVERSATION_STATE["intent"] = None
    CONVERSATION_STATE["entities"] = {}
    CONVERSATION_STATE["history"] = []
    CONVERSATION_STATE["task_flow"] = {
        "active_task": None,
        "current_step": None,
        "step_index": 0,
        "collected": {},
        "completed_task": None,
        "last_output": None,
        "state_version": CONVERSATION_STATE["state_version"],
    }
    QUERY_QUERY_COUNTS.clear()
    return CONVERSATION_STATE


def _history_item(message, role="user"):
    if isinstance(message, dict):
        item_role = message.get("role") or role
        content = (message.get("content") or "").strip()
        if not content:
            return None
        return {"role": item_role, "content": content}

    text = str(message or "").strip()
    if not text:
        return None
    return {"role": role, "content": text}


def update_conversation_state(message=None, intent=None, topic=None, entities=None, history_limit=5, role="user"):
    if message:
        item = _history_item(message, role=role)
        if item is not None:
            CONVERSATION_STATE["history"].append(item)
        if len(CONVERSATION_STATE["history"]) > history_limit:
            CONVERSATION_STATE["history"] = CONVERSATION_STATE["history"][-history_limit:]

    if intent is not None:
        CONVERSATION_STATE["intent"] = intent

    if topic is not None:
        CONVERSATION_STATE["topic"] = topic

    if entities is not None:
        CONVERSATION_STATE["entities"] = entities

    return CONVERSATION_STATE


def set_last_intent(intent):
    update_conversation_state(intent=intent)


def get_last_intent():
    return CONVERSATION_STATE.get("intent")


def get_stats():
    total = len(QUERY_LOGS)
    matched = sum(1 for e in QUERY_LOGS if e.get("confidence", 0) > 0)
    fallback = total - matched
    per_intent = {}
    for e in QUERY_LOGS:
        label = e.get("intent") or "Unmatched"
        per_intent[label] = per_intent.get(label, 0) + 1

    return {
        "total": total,
        "matched": matched,
        "fallback": fallback,
        "per_intent": per_intent,
    }


def keyword_counts(top_n=10, stopwords=None):
    from collections import Counter
    import re

    if stopwords is None:
        stopwords = {"the", "and", "is", "to", "a", "in", "of", "for", "on", "with", "please"}

    counter = Counter()
    for e in QUERY_LOGS:
        text = e.get("question", "").lower()
        words = re.findall(r"\b\w+\b", text)
        for w in words:
            if w in stopwords:
                continue
            counter[w] += 1

    return counter.most_common(top_n)


def get_unanswered_questions():
    return [e.get("question") for e in QUERY_LOGS if e.get("status") == "unanswered"]


def get_unanswered_counts():
    from collections import Counter

    questions = [e.get("question") for e in QUERY_LOGS if e.get("status") == "unanswered"]
    counter = Counter(q for q in questions if q)
    return [{"question": question, "count": count} for question, count in counter.most_common()]


def get_system_insights(limit=10):
    db_insights = get_query_insights(limit=limit)
    top_queries = db_insights.get("top_queries", [])
    most_requested_services = db_insights.get("most_requested_services", [])

    if not top_queries and QUERY_LOGS:
        from collections import Counter

        query_counter = Counter(
            _normalize_query(entry.get("question")) for entry in QUERY_LOGS if entry.get("question")
        )
        top_queries = [
            {
                "query": query,
                "normalized_query": query,
                "count": count,
            }
            for query, count in query_counter.most_common(limit)
        ]

    if not most_requested_services and QUERY_LOGS:
        from collections import Counter

        service_counter = Counter(
            entry.get("intent") for entry in QUERY_LOGS if entry.get("intent")
        )
        if not service_counter:
            service_counter = Counter("Unmatched" for _ in QUERY_LOGS)
        most_requested_services = [
            {"service": service, "count": count} for service, count in service_counter.most_common(limit)
        ]

    failed_responses = sum(1 for entry in QUERY_LOGS if entry.get("status") == "unanswered")
    signal_counts = {
        "confused_queries": sum(1 for entry in QUERY_LOGS if entry.get("is_confused_query")),
        "repeated_queries": sum(1 for entry in QUERY_LOGS if entry.get("is_repeated_query")),
    }

    return {
        "top_queries": top_queries,
        "most_requested_services": most_requested_services,
        "unanswered_questions": get_unanswered_questions()[:limit],
        "unanswered_counts": get_unanswered_counts()[:limit],
        "failed_responses": failed_responses,
        "signal_counts": signal_counts,
    }
