import os
import re
import uuid
from datetime import datetime, timedelta

from app.services.store import STORE_LOCK, _connect_store, _normalize_session_id, _now_iso


DEFAULT_TIMEOUT_MINUTES = 60


def _timeout_minutes():
    raw = os.getenv("GOVERNOR_CONVERSATION_TIMEOUT_MINUTES", str(DEFAULT_TIMEOUT_MINUTES))
    try:
        value = int(raw)
    except (TypeError, ValueError):
        value = DEFAULT_TIMEOUT_MINUTES
    return min(max(value, 30), 120)


def _parse_iso(value):
    try:
        return datetime.fromisoformat(str(value or ""))
    except ValueError:
        return None


def _clean_title(text):
    text = re.sub(r"\s+", " ", str(text or "").strip())
    text = re.sub(r"[^A-Za-z0-9&' /-]", "", text).strip()
    if not text:
        return "New Conversation"
    words = text.split()
    return " ".join(words[:7]).title()


def _preview_text(text, limit=92):
    cleaned = re.sub(r"\s+", " ", str(text or "").strip())
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: max(0, limit - 1)].rstrip() + "..."


def _date_label(value):
    parsed = _parse_iso(value)
    if not parsed:
        return ""
    return parsed.strftime("%b %-d") if os.name != "nt" else parsed.strftime("%b %#d")


def clean_manual_title(text):
    title = _clean_title(text)
    return title if title != "New Conversation" else ""


def generate_conversation_title(message="", intent=None, category=None):
    normalized = re.sub(r"[^a-z0-9\s]", " ", str(message or "").lower())
    normalized = " ".join(normalized.split())
    category = str(category or "").lower()
    intent = str(intent or "").lower()

    rules = [
        (("course", "register"), "Course Registration Help"),
        (("registration",), "Course Registration Help"),
        (("ict",), "ICT Support Inquiry"),
        (("portal",), "Portal Support Inquiry"),
        (("bursary",), "Bursary Support"),
        (("fee",), "School Fees Help"),
        (("hostel",), "Hostel Support"),
        (("admission",), "Admissions Inquiry"),
        (("transcript",), "Transcript Request"),
        (("letter", "draft"), "Official Letter Request"),
        (("permission", "travel"), "Travel Permission Request"),
        (("contact",), "Contact Inquiry"),
    ]

    haystack = f"{normalized} {intent} {category}"
    for keywords, title in rules:
        if all(keyword in haystack for keyword in keywords):
            return title

    return _clean_title(message)


def create_conversation(session_id, title=None):
    session_id = _normalize_session_id(session_id)
    if not session_id:
        return None

    now = _now_iso()
    conversation_id = uuid.uuid4().hex
    title = _clean_title(title or "New Conversation")

    with STORE_LOCK:
        with _connect_store() as conn:
            conn.execute(
                """
                INSERT INTO conversations (conversation_id, session_id, title, created_at, last_updated)
                VALUES (?, ?, ?, ?, ?)
                """,
                (conversation_id, session_id, title, now, now),
            )
            conn.commit()

    return {
        "conversation_id": conversation_id,
        "session_id": session_id,
        "title": title,
        "timestamp": now,
        "last_updated": now,
        "messages": [],
    }


def _adopt_legacy_messages(session_id, conversation_id):
    with STORE_LOCK:
        with _connect_store() as conn:
            row = conn.execute(
                """
                SELECT message
                FROM messages
                WHERE session_id = ? AND conversation_id IS NULL AND role = 'user'
                ORDER BY id
                LIMIT 1
                """,
                (session_id,),
            ).fetchone()
            title = generate_conversation_title(row["message"]) if row else None
            conn.execute(
                """
                UPDATE messages
                SET conversation_id = ?
                WHERE session_id = ? AND conversation_id IS NULL
                """,
                (conversation_id, session_id),
            )
            if title and title != "New Conversation":
                conn.execute(
                    """
                    UPDATE conversations
                    SET title = ?
                    WHERE session_id = ? AND conversation_id = ?
                    """,
                    (title, session_id, conversation_id),
                )
            conn.commit()


def get_conversation(session_id, conversation_id):
    session_id = _normalize_session_id(session_id)
    conversation_id = str(conversation_id or "").strip()
    if not session_id or not conversation_id:
        return None

    with STORE_LOCK:
        with _connect_store() as conn:
            row = conn.execute(
                """
                SELECT conversation_id, session_id, title, created_at, last_updated
                FROM conversations
                WHERE session_id = ? AND conversation_id = ?
                """,
                (session_id, conversation_id),
            ).fetchone()

    if not row:
        return None
    return {
        "conversation_id": row["conversation_id"],
        "session_id": row["session_id"],
        "title": row["title"],
        "timestamp": row["created_at"],
        "last_updated": row["last_updated"],
        "date_label": _date_label(row["last_updated"]),
    }


def get_latest_conversation(session_id):
    session_id = _normalize_session_id(session_id)
    if not session_id:
        return None

    with STORE_LOCK:
        with _connect_store() as conn:
            row = conn.execute(
                """
                SELECT conversation_id, session_id, title, created_at, last_updated
                FROM conversations
                WHERE session_id = ?
                ORDER BY last_updated DESC
                LIMIT 1
                """,
                (session_id,),
            ).fetchone()

    if not row:
        return None
    return {
        "conversation_id": row["conversation_id"],
        "session_id": row["session_id"],
        "title": row["title"],
        "timestamp": row["created_at"],
        "last_updated": row["last_updated"],
        "date_label": _date_label(row["last_updated"]),
    }


def is_conversation_stale(conversation):
    last_updated = _parse_iso((conversation or {}).get("last_updated"))
    if not last_updated:
        return True
    return datetime.now() - last_updated > timedelta(minutes=_timeout_minutes())


def ensure_active_conversation(session_id, conversation_id=None, first_message=None, force_new=False):
    session_id = _normalize_session_id(session_id)
    if not session_id:
        return None

    if force_new:
        return create_conversation(session_id, generate_conversation_title(first_message))

    selected = get_conversation(session_id, conversation_id)
    if selected:
        return selected

    latest = get_latest_conversation(session_id)
    if latest and not is_conversation_stale(latest):
        return latest

    created = create_conversation(session_id, generate_conversation_title(first_message))
    if created:
        _adopt_legacy_messages(session_id, created["conversation_id"])
        return get_conversation(session_id, created["conversation_id"]) or created
    return created


def touch_conversation(session_id, conversation_id, message=None, intent=None, category=None):
    session_id = _normalize_session_id(session_id)
    conversation_id = str(conversation_id or "").strip()
    if not session_id or not conversation_id:
        return None

    now = _now_iso()
    title = generate_conversation_title(message, intent=intent, category=category)
    with STORE_LOCK:
        with _connect_store() as conn:
            existing = conn.execute(
                """
                SELECT title FROM conversations
                WHERE session_id = ? AND conversation_id = ?
                """,
                (session_id, conversation_id),
            ).fetchone()
            if not existing:
                return None

            current_title = str(existing["title"] or "").strip()
            should_update_title = current_title in {"", "New Conversation"} and title != "New Conversation"
            if should_update_title:
                conn.execute(
                    """
                    UPDATE conversations
                    SET title = ?, last_updated = ?
                    WHERE session_id = ? AND conversation_id = ?
                    """,
                    (title, now, session_id, conversation_id),
                )
            else:
                conn.execute(
                    """
                    UPDATE conversations
                    SET last_updated = ?
                    WHERE session_id = ? AND conversation_id = ?
                    """,
                    (now, session_id, conversation_id),
                )
            conn.commit()

    return get_conversation(session_id, conversation_id)


def list_conversations(session_id, limit=60):
    session_id = _normalize_session_id(session_id)
    if not session_id:
        return []

    try:
        limit = int(limit)
    except (TypeError, ValueError):
        limit = 60
    limit = min(max(limit, 1), 200)

    with STORE_LOCK:
        with _connect_store() as conn:
            rows = conn.execute(
                """
                SELECT c.conversation_id, c.session_id, c.title, c.created_at, c.last_updated,
                       COUNT(m.id) AS message_count,
                       (
                           SELECT m2.message
                           FROM messages m2
                           WHERE m2.session_id = c.session_id
                             AND m2.conversation_id = c.conversation_id
                             AND m2.role = 'user'
                           ORDER BY m2.id DESC
                           LIMIT 1
                       ) AS preview
                FROM conversations c
                LEFT JOIN messages m ON m.conversation_id = c.conversation_id
                WHERE c.session_id = ?
                GROUP BY c.conversation_id
                ORDER BY c.last_updated DESC
                LIMIT ?
                """,
                (session_id, limit),
            ).fetchall()

    return [
        {
            "conversation_id": row["conversation_id"],
            "session_id": row["session_id"],
            "title": row["title"],
            "timestamp": row["created_at"],
            "last_updated": row["last_updated"],
            "date_label": _date_label(row["last_updated"]),
            "preview": _preview_text(row["preview"]),
            "message_count": int(row["message_count"] or 0),
        }
        for row in rows
    ]


def rename_conversation(session_id, conversation_id, title):
    session_id = _normalize_session_id(session_id)
    conversation_id = str(conversation_id or "").strip()
    title = clean_manual_title(title)
    if not session_id or not conversation_id or not title:
        return None

    now = _now_iso()
    with STORE_LOCK:
        with _connect_store() as conn:
            result = conn.execute(
                """
                UPDATE conversations
                SET title = ?, last_updated = ?
                WHERE session_id = ? AND conversation_id = ?
                """,
                (title, now, session_id, conversation_id),
            )
            conn.commit()

    if result.rowcount <= 0:
        return None
    return get_conversation(session_id, conversation_id)


def delete_conversation(session_id, conversation_id):
    session_id = _normalize_session_id(session_id)
    conversation_id = str(conversation_id or "").strip()
    if not session_id or not conversation_id:
        return False

    with STORE_LOCK:
        with _connect_store() as conn:
            existing = conn.execute(
                """
                SELECT 1
                FROM conversations
                WHERE session_id = ? AND conversation_id = ?
                """,
                (session_id, conversation_id),
            ).fetchone()
            if not existing:
                return False

            conn.execute(
                """
                DELETE FROM messages
                WHERE session_id = ? AND conversation_id = ?
                """,
                (session_id, conversation_id),
            )
            conn.execute(
                """
                DELETE FROM conversations
                WHERE session_id = ? AND conversation_id = ?
                """,
                (session_id, conversation_id),
            )
            conn.commit()

    return True
