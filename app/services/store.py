from datetime import datetime
import uuid

from flask import has_app_context, session

from app.services.task_requests_db import get_query_insights, save_chat_log

# In-memory query log for prototype stage.
QUERY_LOGS = []
QUERY_QUERY_COUNTS = {}
STORE_DATA = {}
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


def _normalize_query(text):
    import re

    cleaned = re.sub(r"[^a-zA-Z0-9\s]", " ", (text or "").lower())
    return " ".join(cleaned.split())


def _is_confused_query(question):
    normalized = _normalize_query(question)
    return any(phrase in normalized for phrase in _CONFUSION_PHRASES)


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
        "timestamp": datetime.now().isoformat(timespec="seconds"),
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
        # Logging must never block the chat path.
        pass

    return entry


def get_conversation_state():
    return CONVERSATION_STATE


def load_store():
    return STORE_DATA


def save_store(data):
    global STORE_DATA
    STORE_DATA = data
    return STORE_DATA


def get_session_id():
    if has_app_context():
        session_id = session.get(SESSION_PROFILE_KEY)
        if not session_id:
            session_id = uuid.uuid4().hex
            session[SESSION_PROFILE_KEY] = session_id
            session.modified = True
        return session_id

    return "default-session"


def get_user_profile(session_id):
    data = load_store()
    return data.get(session_id, {}).get("profile", {})


def set_user_profile(session_id, profile):
    data = load_store()
    bucket = data.setdefault(session_id, {})
    bucket["profile"] = dict(profile or {})
    return bucket["profile"]


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


# Backwards-compatible helpers (if other modules still call these).
def set_last_intent(intent):
    update_conversation_state(intent=intent)


def get_last_intent():
    return CONVERSATION_STATE.get("intent")


def get_stats():
    """Return simple analytics over the stored queries.

    The result is used by the administrative dashboard to evaluate coverage
    and identify how many interactions fell back to staff contact.
    """

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
    """Return the most frequent words seen in questions.

    ``stopwords`` may be an iterable of tokens to ignore.  If not provided we use
    a small built-in list of generic words that add little value to analysis.
    """

    import re
    from collections import Counter

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
    """Return unanswered questions in the order they were logged."""

    return [e.get("question") for e in QUERY_LOGS if e.get("status") == "unanswered"]


def get_unanswered_counts():
    """Return unanswered question frequency counts."""

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
            (entry.get("workflow_type") or entry.get("intent"))
            for entry in QUERY_LOGS
            if (entry.get("workflow_type") or entry.get("intent"))
        )
        most_requested_services = [
            {"service": service, "count": count}
            for service, count in service_counter.most_common(limit)
        ]

    failed_responses = db_insights.get("failed_responses")
    if failed_responses is None:
        failed_responses = sum(
            1
            for entry in QUERY_LOGS
            if entry.get("is_fallback")
            or entry.get("is_timeout")
            or entry.get("status") in {"unanswered", "fallback", "timeout"}
        )

    signal_counts = db_insights.get("signal_counts") or {}
    if (not has_app_context()) or (
        not top_queries
        and not most_requested_services
        and not db_insights.get("failed_responses")
        and not signal_counts
        and QUERY_LOGS
    ):
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

        service_counter = Counter(
            (entry.get("workflow_type") or entry.get("intent"))
            for entry in QUERY_LOGS
            if (entry.get("workflow_type") or entry.get("intent"))
        )
        most_requested_services = [
            {"service": service, "count": count}
            for service, count in service_counter.most_common(limit)
        ]

        failed_responses = sum(
            1
            for entry in QUERY_LOGS
            if entry.get("is_fallback")
            or entry.get("is_timeout")
            or entry.get("status") in {"unanswered", "fallback", "timeout"}
        )
        signal_counts = {
            "confused_queries": sum(1 for entry in QUERY_LOGS if entry.get("is_confused_query")),
            "repeated_queries": sum(1 for entry in QUERY_LOGS if entry.get("is_repeated_query")),
        }
    elif not signal_counts:
        signal_counts = {
            "confused_queries": sum(1 for entry in QUERY_LOGS if entry.get("is_confused_query")),
            "repeated_queries": sum(1 for entry in QUERY_LOGS if entry.get("is_repeated_query")),
        }

    return {
        "top_queries": top_queries,
        "failed_responses": int(failed_responses or 0),
        "most_requested_services": most_requested_services,
        "signal_counts": signal_counts,
    }
