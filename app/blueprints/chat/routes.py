import json
import os
import re
import tempfile
import threading
from difflib import SequenceMatcher
from datetime import datetime, timezone
from pathlib import Path

from flask import Blueprint, current_app, jsonify, request

from app.services.contact_directory import load_contact_directory, resolve_contact_query
from app.services.directory import get_hostel, get_ict, get_student_affairs, get_vc_contact
from app.services.memory_extractor import detect_user_memory_message
from app.services.knowledge_base import detect_hostel_context, find_relevant_entries, match_conversational
from app.services.llm import call_llm_with_retry
from app.services.rule_engine import classify_intent
from app.services.store import (
    QUERY_LOGS,
    clear_user_profile,
    add_log,
    get_conversation_state,
    get_session_id,
    get_recent_messages,
    get_user,
    get_pending_field,
    get_user_memory,
    get_user_profile,
    get_user_value,
    save_message,
    update_user_memory,
    set_user_profile,
    set_user_value,
    set_pending_field,
    clear_pending_field,
    update_conversation_state,
)
from app.services.response_formatter import format_response
from app.services.task_flow import process_task_message
from app.services.task_requests_db import list_chat_logs

chat_bp = Blueprint("chat", __name__)
FEEDBACK_LOCK = threading.Lock()

SMART_FALLBACK_MESSAGE = (
    "I'm having a slight delay right now, but I can still help. "
    "Could you rephrase or ask again?"
)

HOSTEL_REGISTRATION_NOTE = (
    "Also, make sure your course registration and fees are sorted, as they can affect hostel allocation."
)

HOSTEL_FALLBACK_INSTRUCTION = (
    "You are Governor AI for Godfrey Okoye University. The user is asking about hostel or accommodation. "
    "Give a clear, practical, student-friendly answer based on a Nigerian university system. Be direct and helpful. "
    "Do not use symbols like *, #, or markdown bullet lists. Use short paragraphs with line breaks."
)
HOSTEL_REGISTRATION_CONTEXT_PHRASES = (
    "i have not registered",
    "i havent registered",
    "i have not registered courses",
    "not registered courses",
    "course registration not done",
    "did not register courses",
    "didn't register courses",
)

VC_CONTACT_PHRASES = (
    "vc",
    "vice chancellor",
    "contact vc",
    "email vc",
    "vc email",
    "vice chancellor office",
)

STUDENT_AFFAIRS_CONTACT_PHRASES = (
    "student affairs",
    "welfare",
    "student support",
    "complain",
    "complaint",
    "report issue",
    "general support",
)

ICT_CONTACT_PHRASES = (
    "ict",
    "portal issue",
    "cannot login",
    "can't login",
    "login problem",
    "website problem",
    "technical support",
)

HOSTEL_CONTACT_ALIASES = {
    "sacred heart hostel": "sacred_heart",
    "ad gentes hostel": "ad_gentes",
    "st stephen hostel": "st_stephen",
    "st mary hostel": "st_mary",
    "nwabueze hostel": "nwabueze",
    "our saviour hostel": "our_saviour",
}

GENERAL_CONTACT_PROMPT = (
    "You are Governor AI for Godfrey Okoye University. Suggest the appropriate office and include contact guidance. "
    "If the user does not name a specific office, explain how to identify the right office and ask a short follow-up question. "
    "Use clean paragraphs with line breaks and no bullets or markdown symbols."
)

FOLLOW_UP_STYLE_GUIDANCE = (
    "Do not ask multiple follow-up questions unnecessarily. "
    "Answer the user's current statement first. "
    "Only ask ONE clarifying question if it is absolutely necessary. "
    "Prefer direct guidance and a calm, professional tone. "
    "Keep the response concise unless more detail is genuinely needed. "
    "Make the response feel natural, not like a checklist."
)

HUMAN_RESPONSE_GUIDANCE = (
    "Respond naturally to the user's tone and intent. "
    "Use a calm, intelligent, professional style with slight warmth. "
    "Avoid slang, childish phrasing, and playful filler. "
    "Do not repeat stored profile details unless they are directly relevant to the current question. "
    "If the user changes topic, answer only the new topic and do not carry over the old explanation unless it is essential. "
    "Use short paragraphs or simple numbered steps. "
    "Only introduce university-specific guidance when it becomes necessary."
)


def _feedback_file_path():
    path = Path(current_app.root_path) / "data" / "feedback.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _load_feedback_entries(path):
    if not path.exists():
        return []

    try:
        raw = path.read_text(encoding="utf-8").strip()
        if not raw:
            return []

        data = json.loads(raw)
        if isinstance(data, list):
            return data
    except (OSError, json.JSONDecodeError):
        current_app.logger.warning("Feedback store could not be read cleanly; starting a new list.")

    return []


def _write_feedback_entries(path, entries):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_handle = None
    tmp_path = None
    try:
        tmp_handle = tempfile.NamedTemporaryFile(
            mode="w",
            delete=False,
            dir=str(path.parent),
            prefix=f"{path.stem}_",
            suffix=".tmp",
            encoding="utf-8",
        )
        tmp_path = Path(tmp_handle.name)
        json.dump(entries, tmp_handle, ensure_ascii=False, indent=2)
        tmp_handle.flush()
        os.fsync(tmp_handle.fileno())
    finally:
        if tmp_handle is not None:
            tmp_handle.close()

    if tmp_path is None:
        raise RuntimeError("Unable to create a temporary feedback file")

    os.replace(tmp_path, path)


def _append_feedback_entry(entry):
    path = _feedback_file_path()
    with FEEDBACK_LOCK:
        entries = _load_feedback_entries(path)
        entries.append(entry)
        _write_feedback_entries(path, entries)




def _history_messages(conversation_state, limit=5):
    history = conversation_state.get("history", [])
    normalized = []
    for item in history:
        if isinstance(item, dict):
            role = str(item.get("role") or "user").strip().lower()
            content = str(item.get("content") or "").strip()
        else:
            role = "user"
            content = str(item).strip()

        if not content:
            continue
        if role not in {"user", "assistant"}:
            role = "user"
        normalized.append({"role": role, "content": content})

    if len(normalized) > limit:
        normalized = normalized[-limit:]
    return normalized


def _render_context(messages):
    if not messages:
        return "No previous messages."
    lines = []
    for msg in messages:
        speaker = "User" if msg["role"] == "user" else "Assistant"
        lines.append(f"{speaker}: {msg['content']}")
    return "\n".join(lines)


def _latest_assistant_message(messages):
    for msg in reversed(messages or []):
        if str(msg.get("role") or "").lower() == "assistant":
            content = str(msg.get("content") or "").strip()
            if content:
                return content
    return ""


def _avoid_repeated_response(response, history_messages, question=None):
    response_text = str(response or "").strip()
    last_assistant = _latest_assistant_message(history_messages)
    if not response_text or not last_assistant:
        return response_text

    response_norm = _normalize_text(response_text)
    last_norm = _normalize_text(last_assistant)
    if not response_norm or not last_norm:
        return response_text

    similarity = SequenceMatcher(None, response_norm, last_norm).ratio()
    if similarity < 0.88:
        return response_text

    if len(response_text.split()) > 18:
        first_sentence = re.split(r"(?<=[.!?])\s+", response_text)[0].strip()
        if first_sentence and first_sentence != response_text:
            return f"{first_sentence} If you want, I can continue with the next part."

    if question and _normalize_text(question) in {"also", "and", "what about that", "what about it"}:
        return "I covered that part already. Tell me the new detail and I'll focus on that."

    return "I've already covered that. Tell me which part you want me to focus on next."


def _commit_assistant_response(session_id, response, history_messages, question=None, avoid_repeat=False):
    if avoid_repeat:
        response = _avoid_repeated_response(response, history_messages, question=question)
    save_message(session_id, "assistant", response)
    update_conversation_state(message=response, role="assistant", history_limit=12)
    return response


def _render_kb_entries(entries):
    if not entries:
        return "No direct knowledge base match."

    blocks = []
    for index, entry in enumerate(entries, start=1):
        blocks.append(
            "\n".join(
                [
                    f"Entry {index}",
                    f"Intent: {entry.get('intent') or 'Unknown'}",
                    f"Category: {entry.get('category') or 'Unknown'}",
                    f"Confidence: {entry.get('confidence', 0.0)}",
                    f"Matched question: {entry.get('matched_question') or 'N/A'}",
                    f"Answer snippet: {entry.get('answer') or ''}",
                ]
            )
        )
    return "\n\n".join(blocks)


def _normalize_user_context(user):
    if not isinstance(user, dict):
        user = {}

    name = str(user.get("name") or "").strip()
    department = str(user.get("department") or "").strip()
    level = str(user.get("level") or "").strip()
    notes = user.get("notes")
    normalized_notes = []
    if isinstance(notes, list):
        normalized_notes = [str(note).strip() for note in notes if str(note).strip()]
    elif isinstance(notes, str):
        note_text = notes.strip()
        if note_text:
            normalized_notes = [note_text]

    if not any([name, department, level, normalized_notes]):
        return {}

    profile = {}
    if name:
        profile["name"] = name
    if department:
        profile["department"] = department
    if level:
        profile["level"] = level
    if normalized_notes:
        profile["notes"] = normalized_notes

    return profile


def _normalize_session_id(session_id):
    return str(session_id or "").strip()


def _merge_user_profiles(stored_profile, incoming_profile):
    merged = dict(stored_profile or {})
    incoming = _normalize_user_context(incoming_profile)

    for key, value in incoming.items():
        if value:
            merged[key] = value

    return _normalize_user_context(merged)


def _clean_memory_value(field, value):
    text = str(value or "").strip()
    text = re.sub(r"^[\s,;:.-]+", "", text)
    text = text.strip(" .")

    if field == "level":
        match = re.search(r"(\d{2,3})", text)
        if match:
            return match.group(1)

    if field == "department":
        text = re.sub(r"\bdepartment\b", "", text, flags=re.IGNORECASE).strip()
        text = " ".join(part.capitalize() for part in text.split())

    if field == "name":
        text = " ".join(part.capitalize() for part in text.split())

    return text


def _memory_profile_statement(profile):
    profile = _normalize_user_context(profile)
    if not profile:
        return ""

    name = profile.get("name")
    dept = profile.get("department")
    level = profile.get("level")

    if name and dept and level:
        return f"You are a {level} level {dept} student."
    if name and dept:
        return f"{name}, you are in the {dept} department."
    if name and level:
        return f"{name}, you are a {level} level student."
    if dept and level:
        return f"You are a {level} level {dept} student."
    if name:
        return f"You are now {name}."
    if dept:
        return f"You are in the {dept} department."
    if level:
        return f"You are a {level} level student."

    notes = profile.get("notes")
    if isinstance(notes, list) and notes:
        return str(notes[-1]).strip().rstrip(".") + "."

    return ""


def _memory_confirmation(profile):
    statement = _memory_profile_statement(profile)
    return f"Alright, I'll remember that. {statement}" if statement else "Alright, I'll remember that."


def _memory_recall_summary(profile):
    profile = _normalize_user_context(profile)
    if not profile:
        return "I don't have any stored details yet."

    parts = []
    name = profile.get("name")
    dept = profile.get("department")
    level = profile.get("level")

    if name:
        parts.append(f"Your name is {name}.")
    if dept and level:
        parts.append(f"You are a {level} level {dept} student.")
    elif dept:
        parts.append(f"You are in the {dept} department.")
    elif level:
        parts.append(f"You are a {level} level student.")

    notes = profile.get("notes")
    if isinstance(notes, list) and notes:
        parts.append(f"I also remember: {notes[-1]}.")

    return " ".join(parts) if parts else "I don't have any stored details yet."


def _memory_recall_response(field, profile):
    profile = _normalize_user_context(profile)
    if field == "name":
        name = profile.get("name")
        return f"Your name is {name}." if name else "I don't have your name stored yet."
    if field == "department":
        department = profile.get("department")
        if department and profile.get("level"):
            return f"You are a {profile['level']} level {department} student."
        return f"Your department is {department}." if department else "I don't have your department stored yet."
    if field == "level":
        level = profile.get("level")
        if level and profile.get("department"):
            return f"You are a {level} level {profile['department']} student."
        return f"Your level is {level}." if level else "I don't have your level stored yet."
    if field == "summary":
        return _memory_recall_summary(profile)

    return "I don't have that stored yet."


def detect_user_update(message):
    text = str(message or "").strip()
    normalized = _normalize_text(text)
    if not normalized:
        return None

    update_patterns = [
        (
            "level",
            [
                r"\b(?:change|update|set)\s+my\s+level(?:\s+to)?\s+(?P<value>\d{2,3})(?:\s*level)?$",
                r"\b(?:i am now|i m now|im now|i am|i m|im)\s+(?P<value>\d{2,3})\s*level$",
                r"\b(?:my|the)\s+level\s+is\s+(?P<value>\d{2,3})$",
            ],
        ),
        (
            "department",
            [
                r"\b(?:change|update|set)\s+my\s+department(?:\s+to)?\s+(?P<value>.+)$",
                r"\b(?:i am in|i m in|im in)\s+(?P<value>.+?)\s+department$",
                r"\b(?:my|the)\s+department\s+is\s+(?P<value>.+)$",
                r"\b(?:i study|i m studying|im studying)\s+(?P<value>.+)$",
            ],
        ),
        (
            "name",
            [
                r"\b(?:change|update|set)\s+my\s+name(?:\s+to)?\s+(?P<value>.+)$",
                r"\bcall me\s+(?P<value>.+)$",
                r"\bmy name is\s+(?P<value>.+)$",
                r"\b(?:i am|i m|im)\s+(?P<value>[a-z][a-z\s'.-]{1,50})$",
            ],
        ),
        (
            "notes",
            [
                r"\bi prefer\s+(?P<value>.+)$",
                r"\bi stay in\s+(?P<value>.+)$",
                r"\bi live in\s+(?P<value>.+)$",
                r"\bi stay at\s+(?P<value>.+)$",
                r"\bi reside in\s+(?P<value>.+)$",
            ],
        ),
    ]

    for field, patterns in update_patterns:
        for pattern in patterns:
            match = re.search(pattern, normalized, flags=re.IGNORECASE)
            if not match:
                continue

            value = _clean_memory_value(field, match.group("value"))
            if field == "name":
                if not value or any(term in _normalize_text(value) for term in {"level", "department", "study", "student"}):
                    continue
            if field == "department":
                if not value:
                    continue
            if field == "notes":
                value = _clean_memory_value("notes", value)

            if value:
                return {
                    "action": "update",
                    "field": field,
                    "value": value,
                }

    clarify_patterns = {
        "name": [r"^(change|update|set)\s+my\s+name$"],
        "department": [r"^(change|update|set)\s+my\s+department$"],
        "level": [r"^(change|update|set)\s+my\s+level$"],
    }
    for field, patterns in clarify_patterns.items():
        if any(re.search(pattern, normalized) for pattern in patterns):
            return {
                "action": "clarify",
                "field": field,
                "prompt": "What would you like me to change it to?",
            }

    return None


def detect_memory_recall(message):
    normalized = _normalize_text(message)
    if not normalized:
        return None

    if any(
        phrase in normalized
        for phrase in (
            "what is my name",
            "whats my name",
            "what's my name",
            "who am i",
            "who am i to you",
        )
    ):
        return "name"

    if any(
        phrase in normalized
        for phrase in (
            "what is my department",
            "whats my department",
            "what's my department",
            "which department am i in",
            "what department am i in",
        )
    ):
        return "department"

    if any(
        phrase in normalized
        for phrase in (
            "what is my level",
            "whats my level",
            "what's my level",
            "what level am i",
            "what level am i in",
        )
    ):
        return "level"

    if any(
        phrase in normalized
        for phrase in (
            "what do you know about me",
            "tell me what you know about me",
            "what have you saved about me",
            "remember about me",
        )
    ):
        return "summary"

    return None


def _looks_like_pending_value(message):
    normalized = _normalize_text(message)
    if not normalized:
        return False
    if normalized.startswith(("what ", "who ", "where ", "when ", "why ", "how ", "is ", "are ", "do ", "does ", "can ")):
        return False
    return len(normalized.split()) <= 6


def _is_explicit_memory_command(message):
    normalized = _normalize_text(message)
    if not normalized:
        return False

    explicit_starts = (
        "call me ",
        "my name is ",
        "change my ",
        "update my ",
        "set my ",
        "change my name ",
        "update my name ",
        "set my name ",
        "change my department ",
        "update my department ",
        "set my department ",
        "change my level ",
        "update my level ",
        "set my level ",
        "i changed department to ",
        "i prefer ",
        "i stay in ",
        "i stay at ",
        "i live in ",
        "i reside in ",
    )
    return any(normalized.startswith(prefix) for prefix in explicit_starts)


def _build_profile_payload(payload, profile=None):
    data = dict(payload or {})
    normalized_profile = _normalize_user_context(profile)
    if normalized_profile:
        data["profile"] = normalized_profile
    return data


def _handle_memory_control(question, session_id, profile, task_active=False):
    pending_field = get_pending_field(session_id)
    memory_event = detect_user_memory_message(question)

    if memory_event:
        action = memory_event.get("action")
        field = memory_event.get("field")

        if action == "clarify" and field:
            set_pending_field(session_id, field)
            response = memory_event.get("prompt") or "What would you like me to change it to?"
            log_entry = add_log(
                question=question,
                intent=f"memory_change_{field}",
                response=response,
                confidence=1.0,
                status="answered",
                workflow_type=None,
                is_fallback=False,
                is_timeout=False,
            )
            return {
                "reply": response,
                "intent": f"memory_change_{field}",
                "category": "memory",
                "confidence": 1.0,
                "source": "memory_control",
                "matched_question": None,
                "fallback": False,
                "contact_suggestion": None,
                "log_id": log_entry["id"],
                "profile": _normalize_user_context(profile),
            }

        if action == "recall":
            response = _memory_recall_response(field, profile)
            log_entry = add_log(
                question=question,
                intent=f"memory_recall_{field}",
                response=response,
                confidence=1.0,
                status="answered",
                workflow_type=None,
                is_fallback=False,
                is_timeout=False,
            )
            return {
                "reply": response,
                "intent": f"memory_recall_{field}",
                "category": "memory",
                "confidence": 1.0,
                "source": "memory_control",
                "matched_question": None,
                "fallback": False,
                "contact_suggestion": None,
                "log_id": log_entry["id"],
                "profile": _normalize_user_context(profile),
            }

        if action == "update":
            data = memory_event.get("data") or {}
            if data and (not task_active or _is_explicit_memory_command(question)):
                update_user_memory(session_id, data)
                clear_pending_field(session_id)
                updated_profile = get_user_memory(session_id)
                response = _memory_confirmation(updated_profile)
                log_entry = add_log(
                    question=question,
                    intent="memory_update",
                    response=response,
                    confidence=1.0,
                    status="answered",
                    workflow_type=None,
                    is_fallback=False,
                    is_timeout=False,
                )
                return {
                    "reply": response,
                    "intent": "memory_update",
                    "category": "memory",
                    "confidence": 1.0,
                    "source": "memory_control",
                    "matched_question": None,
                    "fallback": False,
                    "contact_suggestion": None,
                    "log_id": log_entry["id"],
                    "profile": updated_profile,
                }

    if pending_field and not task_active:
        recall_field = None
    else:
        recall_field = detect_memory_recall(question)

    if recall_field:
        response = _memory_recall_response(recall_field, profile)
        log_entry = add_log(
            question=question,
            intent=f"memory_recall_{recall_field}",
            response=response,
            confidence=1.0,
            status="answered",
            workflow_type=None,
            is_fallback=False,
            is_timeout=False,
        )
        return {
            "reply": response,
            "intent": f"memory_recall_{recall_field}",
            "category": "memory",
            "confidence": 1.0,
            "source": "memory_control",
            "matched_question": None,
            "fallback": False,
            "contact_suggestion": None,
            "log_id": log_entry["id"],
            "profile": _normalize_user_context(profile),
        }

    if pending_field and not task_active and _looks_like_pending_value(question):
        value = _clean_memory_value(pending_field, question)
        if value:
            update_user_memory(session_id, {pending_field: value})
            clear_pending_field(session_id)
            updated_profile = get_user_memory(session_id)
            response = _memory_confirmation(updated_profile)
            log_entry = add_log(
                question=question,
                intent="memory_update",
                response=response,
                confidence=1.0,
                status="answered",
                workflow_type=None,
                is_fallback=False,
                is_timeout=False,
            )
            return {
                "reply": response,
                "intent": "memory_update",
                "category": "memory",
                "confidence": 1.0,
                "source": "memory_control",
                "matched_question": None,
                "fallback": False,
                "contact_suggestion": None,
                "log_id": log_entry["id"],
                "profile": updated_profile,
            }

    return None


def _render_user_context(user):
    user = _normalize_user_context(user)
    if not user:
        return "Name: Unknown\nDepartment: Unknown\nLevel: Unknown"

    name = user.get("name") or "Unknown"
    department = user.get("department") or "Unknown"
    level = user.get("level") or "Unknown"
    notes = user.get("notes")
    note_text = ""
    if isinstance(notes, list) and notes:
        note_text = f"\nNotes: {notes[-1]}"

    return (
        f"Name: {name}\n"
        f"Department: {department}\n"
        f"Level: {level}"
        f"{note_text}"
    )


def _render_user_followup_guidance(user):
    user = _normalize_user_context(user)
    if not user:
        return (
            "No user profile is available. Ask for personal details only if they are strictly necessary."
        )

    known_fields = []
    missing_fields = []
    for field in ("name", "department", "level"):
        if user.get(field):
            known_fields.append(field)
        else:
            missing_fields.append(field)

    known_text = ", ".join(known_fields) if known_fields else "none"
    missing_text = ", ".join(missing_fields) if missing_fields else "none"

    if user.get("department") and user.get("level"):
        return (
            "The user's department and level are already known. Do not ask for them again. "
            f"Known profile fields: {known_text}. Missing profile fields: {missing_text}. "
            "Only ask for missing information if it is absolutely necessary to answer the user's question."
        )

    if user.get("department"):
        return (
            "The user's department is already known. Do not ask for it again. "
            f"Known profile fields: {known_text}. Missing profile fields: {missing_text}. "
            "Only ask for missing information if it is absolutely necessary to answer the user's question."
        )

    if user.get("level"):
        return (
            "The user's level is already known. Do not ask for it again. "
            f"Known profile fields: {known_text}. Missing profile fields: {missing_text}. "
            "Only ask for missing information if it is absolutely necessary to answer the user's question."
        )

    return (
        f"Known profile fields: {known_text}. Missing profile fields: {missing_text}. "
        "Only ask for missing information if it is absolutely necessary to answer the user's question."
    )


def _build_personalized_fallback_message(user):
    user = _normalize_user_context(user)
    if not user:
        return SMART_FALLBACK_MESSAGE

    if user.get("department") and user.get("level"):
        context_hint = (
            f" I can tailor this for a {user['level']} level {user['department']} student if that helps."
        )
    elif user.get("department"):
        context_hint = f" I can tailor this for your {user['department']} department if that helps."
    elif user.get("level"):
        context_hint = f" I can tailor this for your {user['level']} level if that helps."
    else:
        context_hint = ""

    return f"I'm having a slight delay right now, but I can still help. Could you rephrase or ask again?{context_hint}"


def _build_intelligent_fallback_message(question, user=None, context_messages=None, kb_entries=None):
    normalized = _normalize_text(question)
    user = _normalize_user_context(user)
    context_messages = context_messages or []
    kb_entries = kb_entries or []

    if not normalized:
        return _build_personalized_fallback_message(user)

    if any(word in normalized for word in {"hard", "stress", "stressed", "overwhelmed", "tired", "sad", "frustrated", "confused"}):
        return "That sounds like a lot right now. Tell me which part you want help with first."

    if any(word in normalized for word in {"funny", "lol", "lmao", "joking", "joke", "haha"}):
        return "What do you mean exactly? If you want, explain it a bit more and I'll help."

    if any(word in normalized for word in {"life", "life is hard", "everything", "nothing", "bad"}):
        return "That sounds difficult. If you want, tell me what is making it feel that way."

    if kb_entries:
        top_entry = kb_entries[0] or {}
        answer = str(top_entry.get("answer") or "").strip()
        matched_question = str(top_entry.get("matched_question") or "").strip().lower()
        if answer:
            return f"I may be close here. {answer}"
        if matched_question:
            return f"I might be hearing something like '{matched_question}'. Can you confirm if that's what you mean?"

    if context_messages:
        recent_user_message = next(
            (
                str(msg.get("content") or "").strip()
                for msg in reversed(context_messages)
                if str(msg.get("role") or "").lower() == "user" and str(msg.get("content") or "").strip()
            ),
            "",
        )
        if recent_user_message:
            return f"I'm not fully sure, but it sounds like you mean: {recent_user_message}. Tell me a little more and I'll help."

    return "I'm not fully sure yet, but I can help if you tell me a little more about what's going on."

def _normalize_text(text):
    cleaned = re.sub(r"[^a-zA-Z0-9\s]", " ", (text or "").lower())
    return " ".join(cleaned.split())


def _is_hostel_registration_context(context_messages):
    if not context_messages:
        return False

    combined = " ".join(_normalize_text(msg.get("content", "")) for msg in context_messages)
    return any(phrase in combined for phrase in HOSTEL_REGISTRATION_CONTEXT_PHRASES)


def _clean_hostel_response(text):
    lines = []
    for raw_line in str(text or "").splitlines():
        line = raw_line.strip()
        if not line:
            if lines and lines[-1] != "":
                lines.append("")
            continue

        line = re.sub(r"^[*\-#]+\s*", "", line)
        line = re.sub(r"^\d+[.)]\s*", "", line)
        lines.append(line)

    cleaned = "\n".join(lines).strip()
    return cleaned or str(text or "").strip()


def _clean_contact_response(text):
    return _clean_hostel_response(text)


def _hostel_response_note(context_messages):
    return HOSTEL_REGISTRATION_NOTE if _is_hostel_registration_context(context_messages) else ""


def _contains_any(normalized_text, phrases):
    return any(phrase in normalized_text for phrase in phrases)


def _has_known_office_reference(question):
    normalized = _normalize_text(question)
    if not normalized:
        return False

    for entry in load_contact_directory():
        office_name = _normalize_text(entry.get("office_name", ""))
        office_core = " ".join(
            token for token in office_name.split() if token not in {"office", "unit", "and", "s"}
        )
        if office_name and office_name in normalized:
            return True
        if office_core and office_core in normalized:
            return True
    return False


def _detect_hostel_key(normalized_text):
    for alias, key in HOSTEL_CONTACT_ALIASES.items():
        if alias in normalized_text:
            return key
    return None


def _build_contact_prompt(question, context_messages, user=None):
    context_text = _render_context(context_messages)
    user_text = _render_user_context(user)
    user_guidance = _render_user_followup_guidance(user)
    directory_snapshot = "\n".join(
        [
            "VC contact",
            f"Email: {get_vc_contact().get('email', 'Not available yet')}",
            f"Office: {get_vc_contact().get('office', 'Not available yet')}",
            f"Note: {get_vc_contact().get('note', '')}",
            "",
            "Student Affairs contact",
            f"Phone: {get_student_affairs().get('phone', 'Not available yet')}",
            f"Office: {get_student_affairs().get('office', 'Not available yet')}",
            f"Note: {get_student_affairs().get('note', '')}",
            "",
            "ICT contact",
            f"Phone: {get_ict().get('phone', 'Not available yet')}",
            f"Office: {get_ict().get('office', 'Not available yet')}",
            f"Note: {get_ict().get('note', '')}",
        ]
    )

    return (
        f"{GENERAL_CONTACT_PROMPT}\n\n"
        f"{FOLLOW_UP_STYLE_GUIDANCE}\n\n"
        f"{HUMAN_RESPONSE_GUIDANCE}\n\n"
        "User context:\n"
        f"{user_text}\n\n"
        "Follow-up guidance:\n"
        f"{user_guidance}\n\n"
        "Current user message:\n"
        f"{question}\n\n"
        "Conversation so far:\n"
        f"{context_text}\n\n"
        "Available directory details:\n"
        f"{directory_snapshot}"
    )


def _handle_directory_contact(question, context_messages, user=None):
    normalized = _normalize_text(question)
    if not normalized:
        return {"handled": False}

    if _contains_any(normalized, VC_CONTACT_PHRASES):
        vc = get_vc_contact()
        email = vc.get("email") or "Not available yet"
        office = vc.get("office") or "Not available yet"
        note = vc.get("note") or ""
        lines = [
            "If you want to reach the Vice Chancellor of Godfrey Okoye University, here is the direct option.",
            "",
            f"You can send an email to: {email}",
            f"Office: {office}",
            "",
            "For physical visits, go to the VC's office through the secretary.",
        ]
        if note:
            lines.extend(["", note])
        return {
            "handled": True,
            "source": "directory_contact",
            "intent": "vc_contact",
            "category": "contact_directory",
            "reply": "\n".join(lines),
            "confidence": 1.0,
            "matched_question": None,
            "fallback": False,
            "use_llm": False,
        }

    if _contains_any(normalized, STUDENT_AFFAIRS_CONTACT_PHRASES):
        info = get_student_affairs()
        phone = info.get("phone") or "Not available yet"
        office = info.get("office") or "Not available yet"
        note = info.get("note") or "They handle complaints, welfare, and student support."
        lines = [
            "For student-related issues, you should contact Student Affairs.",
            "",
            f"Phone: {phone}",
            f"Office: {office}",
            "",
            note,
        ]
        return {
            "handled": True,
            "source": "directory_contact",
            "intent": "student_affairs_contact",
            "category": "contact_directory",
            "reply": "\n".join(lines),
            "confidence": 1.0,
            "matched_question": None,
            "fallback": False,
            "use_llm": False,
        }

    if _contains_any(normalized, ICT_CONTACT_PHRASES):
        info = get_ict()
        phone = info.get("phone") or "Not available yet"
        office = info.get("office") or "Not available yet"
        note = info.get("note") or "They handle portal issues, login problems, and technical support."
        lines = [
            "For portal or technical issues, contact ICT support.",
            "",
            f"Phone: {phone}",
            f"Office: {office}",
            "",
            note,
        ]
        return {
            "handled": True,
            "source": "directory_contact",
            "intent": "ict_contact",
            "category": "contact_directory",
            "reply": "\n".join(lines),
            "confidence": 1.0,
            "matched_question": None,
            "fallback": False,
            "use_llm": False,
        }

    hostel_key = _detect_hostel_key(normalized)
    if hostel_key:
        info = get_hostel(hostel_key)
        office = info.get("office") or "Not available yet"
        phone = info.get("phone") or "Not available yet"
        hostel_name = hostel_key.replace("_", " ").title()
        lines = [
            "Here is the information for your hostel.",
            "",
            f"Hostel: {hostel_name}",
            f"Office: {office}",
            f"Phone: {phone}",
        ]
        return {
            "handled": True,
            "source": "directory_contact",
            "intent": f"{hostel_key}_contact",
            "category": "contact_directory",
            "reply": "\n".join(lines),
            "confidence": 1.0,
            "matched_question": None,
            "fallback": False,
            "use_llm": False,
        }

    hostel_contact_signals = (
        "hostel office",
        "hostel contact",
        "hostel assistance",
        "hostel help",
        "accommodation office",
        "accommodation contact",
        "accommodation assistance",
        "accommodation help",
    )
    if _contains_any(normalized, hostel_contact_signals):
        lines = [
            "If you need hostel assistance, go to the hostel office closest to your accommodation.",
            "",
            "If you tell me your hostel name, I can give more specific guidance.",
        ]
        return {
            "handled": True,
            "source": "directory_contact",
            "intent": "hostel_contact",
            "category": "contact_directory",
            "reply": "\n".join(lines),
            "confidence": 0.9,
            "matched_question": None,
            "fallback": False,
            "use_llm": False,
        }

    if _is_contact_request(normalized) and not _has_known_office_reference(question):
        return {
            "handled": True,
            "source": "llm_primary",
            "intent": "contact_guidance",
            "category": "contact_directory",
            "reply": None,
            "confidence": 0.0,
            "matched_question": None,
            "fallback": False,
            "use_llm": True,
            "prompt": _build_contact_prompt(question, context_messages, user=user),
        }

    return {"handled": False}


def _is_contact_request(question):
    normalized = _normalize_text(question)
    if not normalized:
        return False

    contact_signals = (
        "contact",
        "email",
        "phone",
        "call",
        "reach",
        "reach out",
        "how do i get in touch",
        "how can i get in touch",
        "who do i speak to",
    )
    return _contains_any(normalized, contact_signals)


def _build_prompt(question, context_messages, kb_entries, extra_instructions=None, user=None):
    context_text = _render_context(context_messages)
    kb_text = _render_kb_entries(kb_entries)
    user_text = _render_user_context(user)
    user_guidance = _render_user_followup_guidance(user)
    extra_text = f"\n\nSpecial instructions:\n{extra_instructions}" if extra_instructions else ""

    return (
        "You are Governor AI for Godfrey Okoye University.\n\n"
        "User context:\n"
        f"{user_text}\n\n"
        f"{FOLLOW_UP_STYLE_GUIDANCE}\n\n"
        f"{HUMAN_RESPONSE_GUIDANCE}\n\n"
        "Follow-up guidance:\n"
        f"{user_guidance}\n\n"
        "Current user message:\n"
        f"{question}\n\n"
        "Conversation so far (last 5 messages):\n"
        f"{context_text}\n\n"
        "Relevant knowledge base entries:\n"
        f"{kb_text}"
        f"{extra_text}\n\n"
        "How to respond:\n"
        "1. Interpret all natural language naturally.\n"
        "2. Decide whether to answer conversationally, use knowledge base information, or combine both.\n"
        "3. Do not repeat stored name, department, or level unless the current question directly needs it.\n"
        "4. Only ask for missing personal information if it is absolutely necessary to answer the user's question.\n"
        "5. If the user changes topic, answer only the new topic and do not carry over the previous explanation unless essential.\n"
        "6. Keep the response concise by default and expand only when needed.\n"
        "7. Use short paragraphs or simple numbered steps. Avoid markdown symbols like *, #, or heavy bullet formatting.\n"
        "8. Do not start with filler like 'here's a quick answer' or similar phrases."
    )


def _finalize_response(response, question, category=None, profile=None):
    return format_response(response, user_input=question, category=category, profile=profile)


@chat_bp.post("/api/chat")
def chat_api():
    payload = request.get_json(silent=True) or {}
    question = (payload.get("message") or "").strip()
    incoming_profile = _normalize_user_context(payload.get("user", {}))
    session_id = _normalize_session_id(payload.get("session_id")) or get_session_id()
    user_record = get_user(session_id)
    user_memory = _normalize_user_context(user_record)
    profile = _merge_user_profiles(user_memory, incoming_profile)

    if profile:
        set_user_profile(session_id, profile)
    elif user_memory:
        profile = _normalize_user_context(user_memory)

    user = profile

    if not question:
        return jsonify({"error": "message is required"}), 400

    conversation_state = get_conversation_state()
    history_before = get_recent_messages(session_id, limit=5)
    contextual_intent = classify_intent(question, history=history_before)
    save_message(session_id, "user", question)
    update_conversation_state(message=question, role="user", history_limit=12)
    task_active = bool((conversation_state.get("task_flow") or {}).get("active_task"))
    context_messages = get_recent_messages(session_id, limit=5)
    memory_result = _handle_memory_control(question, session_id, profile, task_active=task_active)
    if memory_result:
        if memory_result.get("reply"):
            memory_result["reply"] = _commit_assistant_response(
                session_id,
                memory_result["reply"],
                history_before,
                question=question,
                avoid_repeat=False,
            )
        return jsonify(_build_profile_payload(memory_result, memory_result.get("profile")))

    task_result = process_task_message(
        question,
        conversation_state,
        profile=profile,
        session_id=session_id,
        history=context_messages,
    )

    if task_result.get("handled"):
        response = task_result.get("reply") or SMART_FALLBACK_MESSAGE
        task_key = task_result.get("task_key")
        completed = bool(task_result.get("completed"))
        request_id = task_result.get("request_id")
        current_step = task_result.get("current_step")

        if task_key:
            update_conversation_state(
                intent=task_key,
                topic="task_workflow",
                history_limit=12,
            )

        if completed:
            status = "task_completed"
        elif task_key:
            status = "task_in_progress"
        else:
            status = "task_cancelled"

        confidence = 1.0 if task_key else 0.0
        response = _finalize_response(response, question, category="task_workflow", profile=profile)
        response = _commit_assistant_response(session_id, response, history_before, question=question, avoid_repeat=False)
        log_entry = add_log(
            question=question,
            intent=task_key,
            response=response,
            confidence=confidence,
            status=status,
            workflow_type=task_key,
            is_fallback=False,
            is_timeout=False,
        )

        return jsonify(
            {
                "reply": response,
                "intent": task_key,
                "category": "task_workflow",
                "confidence": confidence,
                "source": "task_flow",
                "matched_question": None,
                "fallback": False,
                "contact_suggestion": None,
                "log_id": log_entry["id"],
                "task": {
                    "active": bool(task_key) and not completed,
                    "completed": completed,
                    "key": task_key,
                    "label": task_result.get("task_label"),
                    "output_type": task_result.get("output_type"),
                    "current_step": current_step,
                    "request_id": request_id,
                },
            }
        )

    directory_result = _handle_directory_contact(question, context_messages, user=user)
    if directory_result.get("handled"):
        if directory_result.get("use_llm"):
            prompt = directory_result.get("prompt") or _build_contact_prompt(question, context_messages, user=user)
            timeout_seconds = int(current_app.config.get("OPENAI_TIMEOUT", 25))
            response = call_llm_with_retry(prompt, timeout=timeout_seconds, retries=1)
            if response:
                response = _clean_contact_response(response)
            else:
                response = SMART_FALLBACK_MESSAGE
                directory_result["fallback"] = True

            intent_label = directory_result.get("intent")
            confidence = float(directory_result.get("confidence", 0.0) if response else 0.0)
            status = "answered" if response != SMART_FALLBACK_MESSAGE else "unanswered"
            response = _finalize_response(response, question, category=directory_result.get("category"), profile=profile)
            response = _commit_assistant_response(session_id, response, history_before, question=question, avoid_repeat=True)
            log_entry = add_log(
                question=question,
                intent=intent_label,
                response=response,
                confidence=confidence,
                status=status,
                workflow_type=None,
                is_fallback=response == SMART_FALLBACK_MESSAGE,
                is_timeout=False,
            )
            return jsonify(
                {
                    "reply": response,
                    "intent": intent_label,
                    "category": directory_result.get("category"),
                    "confidence": confidence,
                    "source": directory_result.get("source"),
                    "matched_question": None,
                    "fallback": response == SMART_FALLBACK_MESSAGE,
                    "contact_suggestion": None,
                    "log_id": log_entry["id"],
                }
            )

        response = directory_result.get("reply") or SMART_FALLBACK_MESSAGE
        confidence = float(directory_result.get("confidence", 1.0))
        intent_label = directory_result.get("intent")
        update_conversation_state(intent=intent_label, topic=directory_result.get("category"), history_limit=12)
        response = _finalize_response(response, question, category=directory_result.get("category"), profile=profile)
        response = _commit_assistant_response(session_id, response, history_before, question=question, avoid_repeat=False)
        log_entry = add_log(
            question=question,
            intent=intent_label,
            response=response,
            confidence=confidence,
            status="answered",
            workflow_type=None,
            is_fallback=False,
            is_timeout=False,
        )
        return jsonify(
            {
                "reply": response,
                "intent": intent_label,
                "category": directory_result.get("category"),
                "confidence": confidence,
                "source": directory_result.get("source"),
                "matched_question": None,
                "fallback": False,
                "contact_suggestion": None,
                "log_id": log_entry["id"],
            }
        )

    contact_result = resolve_contact_query(question)
    if contact_result.get("handled"):
        response = contact_result.get("reply") or SMART_FALLBACK_MESSAGE
        matched = bool(contact_result.get("matched"))
        entry = contact_result.get("entry") or {}
        intent_label = entry.get("office_name")
        confidence = 1.0 if matched else 0.6
        status = "contact_matched" if matched else "contact_unmatched"

        if matched:
            update_conversation_state(
                intent=intent_label,
                topic="contact_directory",
                history_limit=12,
            )

        response = _finalize_response(response, question, category="contact_directory", profile=profile)
        response = _commit_assistant_response(session_id, response, history_before, question=question, avoid_repeat=False)
        log_entry = add_log(
            question=question,
            intent=intent_label,
            response=response,
            confidence=confidence,
            status=status,
            workflow_type=None,
            is_fallback=False,
            is_timeout=False,
        )

        return jsonify(
            {
                "reply": response,
                "intent": intent_label,
                "category": "contact_directory",
                "confidence": confidence,
                "source": "contact_directory",
                "matched_question": None,
                "fallback": False,
                "contact_suggestion": None,
                "log_id": log_entry["id"],
                "contact": entry if matched else None,
            }
        )

    hostel_match = match_conversational(question)
    hostel_context = detect_hostel_context(question)
    hostel_direct = bool(hostel_match.get("matched") and str(hostel_match.get("category") or "").lower() == "hostel")

    if hostel_direct:
        response = _clean_hostel_response(hostel_match.get("answer") or SMART_FALLBACK_MESSAGE)
        note = _hostel_response_note(context_messages)
        if note and note.lower() not in response.lower():
            response = f"{response}\n\n{note}"

        intent_label = hostel_match.get("intent")
        category = hostel_match.get("category") or "hostel"
        matched_question = hostel_match.get("matched_question")
        confidence = float(hostel_match.get("confidence", 1.0))

        update_conversation_state(
            intent=intent_label,
            topic=category,
            history_limit=12,
        )
        response = _finalize_response(response, question, category=category, profile=profile)
        response = _commit_assistant_response(session_id, response, history_before, question=question, avoid_repeat=False)
        log_entry = add_log(
            question=question,
            intent=intent_label,
            response=response,
            confidence=confidence,
            status="answered",
            workflow_type=None,
            is_fallback=False,
            is_timeout=False,
        )

        return jsonify(
            {
                "reply": response,
                "intent": intent_label,
                "category": category,
                "confidence": confidence,
                "source": "knowledge_base",
                "matched_question": matched_question,
                "fallback": False,
                "contact_suggestion": None,
                "log_id": log_entry["id"],
            }
        )

    kb_entries = find_relevant_entries(question, limit=3, min_confidence=0.3)

    hostel_context = hostel_context or detect_hostel_context(question, kb_entries)
    extra_instructions = None
    if contextual_intent.get("contextual") or contextual_intent.get("topic_shift"):
        followup_hint = (
            f"Conversation continuity hint: the previous topic was {contextual_intent.get('intent_label')}. "
            "Continue naturally without repeating the previous answer. "
            "If the user is adding a new issue, treat it as a new issue rather than restarting the old one. "
            "If the user has changed topic, focus only on the new topic."
        )
        extra_instructions = followup_hint
    if hostel_context:
        extra_instructions = HOSTEL_FALLBACK_INSTRUCTION
        if _is_hostel_registration_context(context_messages):
            extra_instructions = f"{extra_instructions}\n\n{HOSTEL_REGISTRATION_NOTE}"
        if contextual_intent.get("contextual"):
            extra_instructions = f"{extra_instructions}\n\n{followup_hint}"

    prompt = _build_prompt(
        question,
        context_messages,
        kb_entries,
        extra_instructions=extra_instructions,
        user=user,
    )
    timeout_seconds = int(current_app.config.get("OPENAI_TIMEOUT", 25))
    response = call_llm_with_retry(prompt, timeout=timeout_seconds, retries=1)

    top_entry = kb_entries[0] if kb_entries else {}
    intent_label = top_entry.get("intent")
    category = top_entry.get("category")
    matched_question = top_entry.get("matched_question")
    confidence = float(top_entry.get("confidence", 0.0)) if response else 0.0

    if response:
        source = "llm_primary"
        fallback = False
        status = "answered"
        if intent_label or category:
            update_conversation_state(
                intent=intent_label,
                topic=category or intent_label,
                history_limit=12,
            )
        if hostel_context:
            response = _clean_hostel_response(response)
            note = _hostel_response_note(context_messages)
            if note and note.lower() not in response.lower():
                response = f"{response}\n\n{note}"
    else:
        current_app.logger.warning("LLM failed after retry, using smart fallback.")
        response = _build_intelligent_fallback_message(
            question,
            user=user,
            context_messages=context_messages,
            kb_entries=kb_entries,
        )
        source = "llm_fallback"
        fallback = True
        status = "unanswered"

    response = _finalize_response(response, question, category=category, profile=profile)
    response = _commit_assistant_response(session_id, response, history_before, question=question, avoid_repeat=True)

    log_entry = add_log(
        question=question,
        intent=intent_label,
        response=response,
        confidence=confidence,
        status=status,
        workflow_type=None,
        is_fallback=fallback,
        is_timeout=False,
    )

    contact_suggestion = None
    if fallback:
        office = current_app.config["FALLBACK_CONTACT"]
        contact_suggestion = f"If you still need help, contact {office}."

    return jsonify(
        {
            "reply": response,
            "intent": intent_label,
            "category": category,
            "confidence": confidence,
            "source": source,
            "matched_question": matched_question,
            "fallback": fallback,
            "contact_suggestion": contact_suggestion,
            "log_id": log_entry["id"],
        }
    )


@chat_bp.post("/api/feedback")
def feedback_api():
    payload = request.get_json(silent=True) or {}
    message = str(payload.get("message") or "").strip()
    response = str(payload.get("response") or "").strip()
    feedback = str(payload.get("feedback") or "").strip().lower()
    comment_value = payload.get("comment")
    comment = "" if comment_value is None else str(comment_value).strip()

    if not message or not response or feedback not in {"yes", "no"}:
        return jsonify({"error": "message, response, and feedback are required"}), 400

    data = {
        "message": message,
        "response": response,
        "feedback": feedback,
        "comment": comment,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    _append_feedback_entry(data)
    print("Feedback received:", data)

    return jsonify({"ok": True}), 201


@chat_bp.post("/api/profile/reset")
def profile_reset_api():
    payload = request.get_json(silent=True) or {}
    session_id = _normalize_session_id(payload.get("session_id")) or get_session_id()
    clear_user_profile(session_id)
    return jsonify({"ok": True}), 200


@chat_bp.get("/api/profile")
def profile_get_api():
    session_id = _normalize_session_id(request.args.get("session_id")) or get_session_id()
    profile = get_user_profile(session_id)
    pending_field = get_pending_field(session_id)
    return jsonify(
        {
            "profile": _normalize_user_context(profile),
            "pending_field": pending_field,
        }
    )


@chat_bp.get("/api/logs")
def logs_api():
    logs = list_chat_logs(limit=100)
    if logs:
        return jsonify(logs)
    return jsonify(QUERY_LOGS[-100:])


@chat_bp.get("/api/intents")
def intents_api():
    from app.services.rule_engine import INTENT_RULES

    return jsonify(
        [
            {
                "intent_key": key,
                "label": row["label"],
                "office": row["office"],
            }
            for key, row in INTENT_RULES.items()
        ]
    )




