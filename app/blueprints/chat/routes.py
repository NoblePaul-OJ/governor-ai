import json
import os
import re
import tempfile
import threading
from difflib import SequenceMatcher
from datetime import datetime, timezone
from pathlib import Path

from flask import Blueprint, current_app, g, jsonify, request

from app.services.contact_directory import load_contact_directory, resolve_contact_query
from app.services.conversation_manager import (
    create_conversation,
    delete_conversation,
    ensure_active_conversation,
    get_conversation,
    list_conversations,
    rename_conversation,
    touch_conversation,
)
from app.services.admin_auth import require_admin_access
from app.services.directory import get_contact, get_hostel, get_unit_contacts
from app.services.memory_extractor import detect_user_memory_message
from app.services.knowledge_base import (
    detect_hostel_context,
    find_relevant_entries,
    match_conversational,
    resolve_academic_structure_query,
)
from app.services.institutional_knowledge import resolve_institutional_query
from app.services.llm import call_llm_with_retry
from app.services.rule_engine import classify_intent
from app.services.store import (
    QUERY_LOGS,
    clear_user_profile,
    add_log,
    bind_session_id,
    get_conversation_state,
    get_session_id,
    get_recent_messages,
    get_user,
    get_pending_field,
    get_user_memory,
    get_user_profile,
    get_user_value,
    update_user,
    save_message,
    update_user_memory,
    set_user_profile,
    set_user_value,
    set_pending_field,
    clear_pending_field,
    update_conversation_state,
)
from app.services.response_formatter import (
    build_incomplete_message_reply,
    build_social_response,
    detect_incomplete_message,
    detect_user_tone,
    format_response,
    polish_response_text,
    normalize_user_message,
)
from app.services.personality import get_persona_prompt
from app.services.task_flow import process_task_message
from app.services.task_requests_db import list_chat_logs

chat_bp = Blueprint("chat", __name__)
FEEDBACK_LOCK = threading.Lock()

SMART_FALLBACK_MESSAGE = (
    "I'm having a slight delay right now, but I can still help. "
    "Could you rephrase or ask again?"
)


@chat_bp.after_request
def attach_conversation_id(response):
    conversation_id = str(getattr(g, "governor_conversation_id", "") or "").strip()
    if not conversation_id or request.path != "/api/chat" or not response.is_json:
        return response

    payload = response.get_json(silent=True)
    if isinstance(payload, dict) and "conversation_id" not in payload:
        payload["conversation_id"] = conversation_id
    if isinstance(payload, dict) and "feedback_prompt" not in payload:
        payload["feedback_prompt"] = _feedback_prompt_for_response(
            {"id": payload.get("log_id")},
            payload.get("reply"),
            fallback=bool(payload.get("fallback")),
        )
    if isinstance(payload, dict):
        response.set_data(json.dumps(payload, ensure_ascii=False))
        response.mimetype = "application/json"
    return response

HOSTEL_REGISTRATION_NOTE = (
    "Also, make sure your course registration and fees are sorted, as they can affect hostel allocation."
)

HOSTEL_FALLBACK_INSTRUCTION = (
    "You are Governor AI for Godfrey Okoye University. The user is asking about hostel or accommodation. "
    "Give a clear, practical, student-friendly answer based on a Nigerian university system. Be direct and helpful. "
    "Write as one or two natural paragraphs. Avoid markdown symbols, bullet lists, and repeated headings."
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

BURSARY_CONTACT_PHRASES = (
    "bursary",
    "fees office",
    "payment office",
    "school fees",
    "tuition payment",
)

ADMISSIONS_CONTACT_PHRASES = (
    "admissions",
    "admission",
    "admissions office",
    "admission office",
    "screening office",
    "clearance office",
)

UNIT_INTROS = {
    "vc": "The Vice Chancellor's Office handles formal correspondence and high-level administrative matters.",
    "student_affairs": "Student Affairs handles student welfare, support, and general student concerns.",
    "ict": "ICT Support handles portal login, registration, payment reflection, result checking, and technical support issues.",
    "bursary": "The Bursary Unit handles school fees, payment complaints, receipt issues, clearance verification, and financial inquiries.",
    "admissions": "Admissions handles admission inquiries, application issues, transfer inquiries, admission status, acceptance guidance, and prospective student support.",
}

UNIT_CONTACT_INTENTS = {
    "vc": "vc_contact",
    "student_affairs": "student_affairs_contact",
    "ict": "ict_contact",
    "bursary": "bursary_contact",
    "admissions": "admissions_contact",
}

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
    "If the user does not name a specific office, explain how to identify the right office and ask one short follow-up question only if it is necessary. "
    "Keep the response concise, natural, and unified. Mention each office only once and do not repeat labels like contact details, handles, or office fields."
)

FOLLOW_UP_STYLE_GUIDANCE = (
    "Avoid follow-up questions unless the answer truly depends on missing information. "
    "Answer the user's current statement first. "
    "Infer the likely campus context when reasonable. "
    "If the user confirms a previous interpretation, continue immediately with the best available answer instead of asking another clarification. "
    "Only ask one clarifying question if it is absolutely necessary. "
    "If the message is clearly incomplete and very short, ask a calm completion question instead of guessing. "
    "Prefer direct guidance and a calm, professional tone. "
    "Keep the response concise unless more detail is genuinely needed. "
    "Make the response feel natural, not like a checklist."
)

HUMAN_RESPONSE_GUIDANCE = (
    f"{get_persona_prompt()} "
    "Respond naturally to the user's tone and intent. "
    "Use a calm, intelligent, professional style with slight warmth. "
    "Answer directly before caveats or routing. "
    "Avoid slang, meme phrasing, childish language, playful filler, and over-excitement. "
    "Avoid AI-sounding phrases like 'I understand', 'I can help with that', 'to guide you correctly', 'please provide', and 'I apologize'. "
    "Emojis must be rare, contextual, and limited to one when useful; never use emoji spam. "
    "Use subtle uncertainty phrasing such as 'The last verified information available shows...' for changing university details. "
    "Do not sound chatty or dramatic. "
    "Do not repeat stored profile details unless they are directly relevant to the current question. "
    "If the user profile is useful, mention it lightly in passing rather than restating it as a label. "
    "If the user changes topic, answer only the new topic and do not carry over the old explanation unless it is essential. "
    "Use short paragraphs or simple numbered steps only when the user is asking for a procedure or workflow. "
    "Only introduce university-specific guidance when it becomes necessary."
)


def _tone_guidance(question):
    tone = detect_user_tone(question)
    tone_map = {
        "stressed": "The user sounds stressed or confused. Keep the reply clear, steady, and supportive. Acknowledge the difficulty.",
        "frustrated": "The user sounds frustrated. Acknowledge the issue calmly and provide clear, practical help.",
        "excited": "The user sounds excited or motivated. Match the energy subtly while staying professional.",
        "urgent": "The user sounds urgent. Keep the reply direct, concise, and action-oriented.",
        "casual": "The user sounds casual. Keep the reply natural, but still calm and professional.",
        "serious": "The user sounds serious. Keep the reply direct, concise, and formal.",
        "sarcasm": "The user is being playful or sarcastic. Respond with light understanding but stay grounded.",
        "humor": "The user is being lightly playful. Acknowledge it briefly, then stay useful and composed.",
        "tired": "The user sounds tired. Be gentle, concise, and practical.",
        "neutral": "Use a calm, professional tone with slight warmth.",
    }
    return f"Tone guidance:\n{tone_map.get(tone, tone_map['neutral'])}"


def _build_greeting(profile):
    profile = _normalize_user_context(profile)
    name = str(profile.get("name") or "").strip()

    if name:
        return f"Welcome back, {name}. How can I assist you today?"

    if profile:
        return "Welcome back. How can I assist you today?"

    hour = datetime.now().hour
    if hour < 12:
        salutation = "Good morning"
    elif hour < 18:
        salutation = "Good afternoon"
    else:
        salutation = "Good evening"

    return f"{salutation}. I'm Governor AI. Tell me what you need and I'll help from there."


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


def _is_confirmation_message(question):
    normalized = _normalize_text(question)
    if not normalized:
        return False
    confirmations = {
        "yes",
        "yeah",
        "yep",
        "correct",
        "exactly",
        "sure",
        "that is what i mean",
        "thats what i mean",
        "that's what i mean",
        "yes that is what i mean",
        "yes thats what i mean",
        "yes that's what i mean",
        "that one",
        "continue",
        "go on",
    }
    return normalized in confirmations or any(phrase in normalized for phrase in ("that is what i mean", "thats what i mean", "that's what i mean"))


def _assistant_asked_clarification(messages):
    last_assistant = _latest_assistant_message(messages)
    normalized = _normalize_text(last_assistant)
    if not normalized:
        return False
    if "?" not in last_assistant:
        return False
    clarification_markers = (
        "do you mean",
        "which",
        "what exactly",
        "clarify",
        "which year",
        "what year",
        "take off year",
        "provide",
        "specify",
    )
    return any(marker in normalized for marker in clarification_markers)


def _previous_user_message(messages, current_question):
    current = _normalize_text(current_question)
    for msg in reversed(messages or []):
        if str(msg.get("role") or "").lower() != "user":
            continue
        content = str(msg.get("content") or "").strip()
        if not content:
            continue
        if current and _normalize_text(content) == current:
            continue
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


def _commit_assistant_response(session_id, response, history_messages, question=None, avoid_repeat=False, conversation_id=None):
    if avoid_repeat:
        response = _avoid_repeated_response(response, history_messages, question=question)
    save_message(session_id, "assistant", response, conversation_id=conversation_id)
    update_conversation_state(message=response, role="assistant", history_limit=12, session_id=session_id)
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
    return "Noted. I'll remember that."


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
                r"\b(?:stop calling me|dont call me|don't call me)\s+.+?\s+call me\s+(?P<value>.+)$",
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
    if detect_incomplete_message(message):
        return False

    normalized = _normalize_text(message)
    if not normalized:
        return False
    if normalized.startswith(("what ", "which ", "who ", "where ", "when ", "why ", "how ", "is ", "are ", "do ", "does ", "can ")):
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
    conversation_id = str(getattr(g, "governor_conversation_id", "") or "").strip()
    if conversation_id:
        data["conversation_id"] = conversation_id
    return data


def _handle_memory_control(question, session_id, profile, task_active=False):
    pending_field = get_pending_field(session_id)
    memory_event = detect_user_memory_message(question)

    if pending_field and detect_incomplete_message(question):
        response = "That looks a bit unfinished. What would you like me to change it to?"
        log_entry = add_log(
            question=question,
            intent=f"memory_change_{pending_field}",
            response=response,
            confidence=1.0,
            status="answered",
            workflow_type=None,
            is_fallback=False,
            is_timeout=False,
        )
        return {
            "reply": response,
            "intent": f"memory_change_{pending_field}",
            "category": "memory",
            "confidence": 1.0,
            "source": "memory_control",
            "matched_question": None,
            "fallback": False,
            "contact_suggestion": None,
            "log_id": log_entry["id"],
            "profile": _normalize_user_context(profile),
        }

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

        if action == "clear_name":
            update_user(session_id, "name", None)
            clear_pending_field(session_id)
            updated_profile = get_user_memory(session_id)
            response = "Alright, I'll stop using that."
            log_entry = add_log(
                question=question,
                intent="memory_clear_name",
                response=response,
                confidence=1.0,
                status="answered",
                workflow_type=None,
                is_fallback=False,
                is_timeout=False,
            )
            return {
                "reply": response,
                "intent": "memory_clear_name",
                "category": "memory",
                "confidence": 1.0,
                "source": "memory_control",
                "matched_question": None,
                "fallback": False,
                "contact_suggestion": None,
                "log_id": log_entry["id"],
                "profile": updated_profile,
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
        return "No student profile is stored yet."

    parts = []
    name = user.get("name")
    department = user.get("department")
    level = user.get("level")
    notes = user.get("notes")

    if name:
        parts.append(f"name: {name}")
    if department:
        parts.append(f"department: {department}")
    if level:
        parts.append(f"level: {level}")
    if isinstance(notes, list) and notes:
        parts.append(f"note: {notes[-1]}")

    if not parts:
        return "No student profile is stored yet."

    return "Known profile details: " + "; ".join(parts)


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
    return "Send that again in a little more detail and I'll help from there."


def _build_intelligent_fallback_message(question, user=None, context_messages=None, kb_entries=None):
    normalized = _normalize_text(question)
    user = _normalize_user_context(user)
    context_messages = context_messages or []
    kb_entries = kb_entries or []

    if detect_incomplete_message(question):
        return build_incomplete_message_reply()

    if not normalized:
        return _build_personalized_fallback_message(user)

    if any(word in normalized for word in {"hard", "stress", "stressed", "overwhelmed", "tired", "sad", "frustrated", "confused"}):
        return "That sounds like a lot. Start with the part affecting you most right now."

    if any(word in normalized for word in {"funny", "lol", "lmao", "joking", "joke", "haha"}):
        return "I get you. Send the main thing you need help with and I'll stay with it."

    if any(word in normalized for word in {"life", "life is hard", "everything", "nothing", "bad"}):
        return "That sounds difficult. Start with one thing that is weighing on you."

    if kb_entries:
        top_entry = kb_entries[0] or {}
        answer = str(top_entry.get("answer") or "").strip()
        matched_question = str(top_entry.get("matched_question") or "").strip().lower()
        if answer:
            return answer
        if matched_question:
            return f"This seems related to {matched_question}. Send a bit more context and I'll narrow it down."

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
            return "Send a little more context and I'll narrow it down."

    return "The current university information available to me does not include that detail yet. Send a little more context and I'll help you route it properly."

def _normalize_text(text):
    cleaned = re.sub(r"[^a-zA-Z0-9\s]", " ", (text or "").lower())
    return " ".join(cleaned.split())


def _is_institutional_info_query(question):
    normalized = _normalize_text(question)
    if not normalized:
        return False

    if _contains_any(normalized, ("contact", "email", "phone", "call", "reach out")):
        return False
    if _contains_any(
        normalized,
        (
            "issue",
            "problem",
            "complaint",
            "not opening",
            "cannot",
            "can t",
            "cant",
            "invalid",
            "error",
            "not reflecting",
            "not reflected",
            "failed",
        ),
    ):
        return False

    question_starts = (
        "who ",
        "what ",
        "where ",
        "when ",
        "which ",
        "how ",
        "can ",
        "is ",
        "are ",
    )
    info_markers = (
        "cut off",
        "cutoff",
        "installment",
        "instalment",
        "recent",
        "happening",
        "motto",
        "founded",
        "founder",
        "portal",
        "transcript",
        "ranking",
        "accreditation",
        "scholarship",
        "pioneer staff",
        "pioneer management",
        "pioneer officers",
        "take off staff",
        "takeoff staff",
        "principal officers",
        "governance structure",
        "management hierarchy",
        "university hierarchy",
        "earliest management",
        "dean",
        "deans",
        "hod",
        "heads of departments",
        "senate",
        "board of trustees",
        "bot",
        "heads the",
        "head of department",
        "head of faculty",
        "vice chancellor",
        "tell me about him",
        "tell me about her",
        "president of nigeria",
        "pope",
        "governor of enugu",
        "minister of education",
        "executive secretary",
        "nuc",
        "dvc",
        "registrar",
        "bursar",
        "librarian",
        "provost",
        "deputy provost",
        "chief medical director",
        "cmd",
        "chancellor",
        "proprietor",
        "board of trustees",
        "bot",
    )
    return normalized.startswith(question_starts) or _contains_any(normalized, info_markers)


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
    return polish_response_text(cleaned or str(text or "").strip())


def _clean_contact_response(text):
    return polish_response_text(_clean_hostel_response(text))


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


def _clean_contact_value(value):
    text = str(value or "").strip()
    return text if text and text.lower() not in {"not available yet", "unavailable yet"} else ""


def _clean_contact_list(value):
    if not isinstance(value, list):
        value = [value] if value not in (None, "") else []

    items = []
    for item in value:
        text = _clean_contact_value(item)
        if text and text not in items:
            items.append(text)
    return items


def _contact_summary(contact):
    issues = _clean_contact_list(
        contact.get("common_issues") or contact.get("common_issue_types") or contact.get("handles")
    )
    if issues:
        sample = issues[:4]
        if len(sample) == 1:
            return f"Supports {sample[0]}."
        if len(sample) == 2:
            return f"Supports {sample[0]} and {sample[1]}."
        return f"Supports {', '.join(sample[:-1])}, and {sample[-1]}."

    note = _clean_contact_value(contact.get("description") or contact.get("note"))
    if note:
        return note if note.endswith(".") else f"{note}."

    return ""


def _format_unit_contact_reply(unit_key, intro=None):
    contact = get_unit_contacts(unit_key)
    if not contact:
        return None

    unit_name = contact.get("unit_name") or UNIT_INTROS.get(unit_key, unit_key.replace("_", " ").title())
    lines = [f"{unit_name} is the right office for that."]
    phone_values = _clean_contact_list(contact.get("phones") or contact.get("phone"))
    whatsapp = _clean_contact_value(contact.get("whatsapp"))
    email_values = _clean_contact_list(contact.get("emails") or contact.get("email"))
    office = _clean_contact_value(contact.get("office_location") or contact.get("office"))
    office_hours = _clean_contact_value(contact.get("office_hours"))

    if phone_values or whatsapp:
        phone_label = "\U0001f4de Phone / WhatsApp:" if whatsapp or len(phone_values) == 1 else "\U0001f4de Phone:"
        phone_lines = phone_values[:]
        if whatsapp and whatsapp not in phone_lines:
            phone_lines.append(whatsapp)
        lines.extend(["", phone_label, "\n".join(phone_lines)])
    if email_values:
        lines.extend(["", "\U0001f4e7 Email:", "\n".join(email_values)])
    if office:
        lines.extend(["", "\U0001f4cd Office:", office])
    if office_hours:
        lines.extend(["", "\U0001f552 Office Hours:", office_hours])

    reply = "\n".join(lines).strip()

    return {
        "handled": True,
        "source": "directory_contact",
        "intent": UNIT_CONTACT_INTENTS.get(unit_key, f"{unit_key}_contact"),
        "category": "contact_directory",
        "reply": reply,
        "confidence": 1.0,
        "matched_question": None,
        "fallback": False,
        "use_llm": False,
        "contact": contact,
    }


def _detect_hostel_key(normalized_text):
    for alias, key in HOSTEL_CONTACT_ALIASES.items():
        if alias in normalized_text:
            return key
    return None


def _build_contact_prompt(question, context_messages, user=None):
    context_text = _render_context(context_messages)
    user_text = _render_user_context(user)
    user_guidance = _render_user_followup_guidance(user)
    contact_sections = []
    for unit_key in ("vc", "student_affairs", "ict", "bursary", "admissions"):
        contact = get_contact(unit_key)
        if not contact:
            continue
        section_lines = [contact.get("unit_name") or unit_key.replace("_", " ").title()]
        phone_values = _clean_contact_list(contact.get("phones") or contact.get("phone"))
        for phone in phone_values:
            section_lines.append(f"Phone: {phone}")
        for email in _clean_contact_list(contact.get("emails") or contact.get("email")):
            section_lines.append(f"Email: {email}")
        whatsapp = _clean_contact_value(contact.get("whatsapp"))
        if whatsapp and whatsapp not in phone_values:
            section_lines.append(f"WhatsApp: {whatsapp}")
        office = _clean_contact_value(contact.get("office_location") or contact.get("office"))
        if office:
            section_lines.append(f"Office: {office}")
        office_hours = _clean_contact_value(contact.get("office_hours"))
        if office_hours:
            section_lines.append(f"Office hours: {office_hours}")
        summary = _contact_summary(contact)
        if summary:
            section_lines.append(f"Summary: {summary}")
        contact_sections.append("\n".join(section_lines))

    directory_snapshot = "\n\n".join(contact_sections)

    return (
        f"{GENERAL_CONTACT_PROMPT}\n\n"
        f"{FOLLOW_UP_STYLE_GUIDANCE}\n\n"
        f"{HUMAN_RESPONSE_GUIDANCE}\n\n"
        f"{_tone_guidance(question)}\n\n"
        "User context:\n"
        f"{user_text}\n\n"
        "Follow-up guidance:\n"
        f"{user_guidance}\n\n"
        "Current user message:\n"
        f"{question}\n\n"
        "Conversation so far:\n"
        f"{context_text}\n\n"
        "Available directory details:\n"
        f"{directory_snapshot}\n\n"
        "How to respond:\n"
        "1. Write one smooth paragraph first.\n"
        "2. Mention the contact details only once and avoid repeating labels like contact details, handles, or office fields.\n"
        "3. If the user did not name a specific office, ask only one short clarifying question.\n"
        "4. Keep the tone calm, intelligent, and professional."
    )


def _handle_directory_contact(question, context_messages, user=None):
    normalized = _normalize_text(question)
    if not normalized:
        return {"handled": False}

    if _contains_any(normalized, VC_CONTACT_PHRASES):
        result = _format_unit_contact_reply("vc")
        if result:
            return result

    if _contains_any(normalized, STUDENT_AFFAIRS_CONTACT_PHRASES):
        result = _format_unit_contact_reply("student_affairs")
        if result:
            return result

    if _contains_any(normalized, ICT_CONTACT_PHRASES):
        result = _format_unit_contact_reply("ict")
        if result:
            return result

    if _contains_any(normalized, BURSARY_CONTACT_PHRASES):
        result = _format_unit_contact_reply("bursary")
        if result:
            return result

    if _contains_any(normalized, ADMISSIONS_CONTACT_PHRASES):
        result = _format_unit_contact_reply("admissions")
        if result:
            return result

    hostel_key = _detect_hostel_key(normalized)
    if hostel_key:
        info = get_hostel(hostel_key)
        hostel_name = f"{hostel_key.replace('_', ' ').title()} Hostel"
        office = _clean_contact_value(info.get("office"))
        phone = _clean_contact_value(info.get("phone"))
        details = []
        if office and office.lower() not in {"not available yet", "unavailable yet"}:
            details.append(f"the office is {office}")
        if phone and phone.lower() not in {"not available yet", "unavailable yet"}:
            details.append(f"the phone number is {phone}")

        if details:
            detail_text = " and ".join(details)
            reply = f"I found {hostel_name}. For now, {detail_text}."
        else:
            reply = f"I found {hostel_name}, but the contact details are still being updated."

        return {
            "handled": True,
            "source": "directory_contact",
            "intent": f"{hostel_key}_contact",
            "category": "contact_directory",
            "reply": reply,
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
        return {
            "handled": True,
            "source": "directory_contact",
            "intent": "hostel_contact",
            "category": "contact_directory",
            "reply": "If you need hostel assistance, go to the hostel office closest to your accommodation. If you tell me your hostel name, I can narrow it down.",
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
        f"{_tone_guidance(question)}\n\n"
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
        "7. Use short paragraphs by default. Use numbered steps only when the user is asking for a process or workflow. Avoid markdown symbols like *, #, or heavy bullet formatting.\n"
        "8. Do not start with filler like 'here's a quick answer' or similar phrases.\n"
        "9. If the user confirms your previous interpretation, continue with the answer immediately; do not ask another clarification.\n"
        "10. If confidence is high or medium, answer directly. Use a soft qualifier for medium confidence. Ask only one clarification when the request is genuinely impossible to infer.\n"
        "11. Stay calm, intelligent, professional, and slightly warm. Never sound playful or childish."
    )


def _finalize_response(response, question, category=None, profile=None):
    return format_response(response, user_input=question, category=category, profile=profile)


def _feedback_prompt_for_response(log_entry, response, fallback=False):
    if fallback or not isinstance(log_entry, dict):
        return None

    try:
        log_id = int(log_entry.get("id") or 0)
    except (TypeError, ValueError):
        log_id = 0

    text = str(response or "").strip()
    if log_id <= 0 or log_id % 5 != 0 or len(text.split()) < 35:
        return None

    prompts = (
        "Did that solve your issue?",
        "Was this helpful?",
        "Would you like me to guide you further?",
        "Let me know if you want a more detailed explanation.",
    )
    return prompts[(log_id // 5 - 1) % len(prompts)]


@chat_bp.post("/api/chat")
def chat_api():
    payload = request.get_json(silent=True) or {}
    question = normalize_user_message(payload.get("message"))
    incoming_profile = _normalize_user_context(payload.get("user", {}))
    session_id = _normalize_session_id(payload.get("session_id")) or get_session_id()
    bind_session_id(session_id)
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

    conversation = ensure_active_conversation(
        session_id,
        conversation_id=payload.get("conversation_id"),
        first_message=question,
    )
    conversation_id = conversation["conversation_id"] if conversation else None
    g.governor_conversation_id = conversation_id

    conversation_state = get_conversation_state(session_id)
    history_before = get_recent_messages(session_id, limit=5, conversation_id=conversation_id)
    contextual_intent = classify_intent(question, history=history_before)
    save_message(session_id, "user", question, conversation_id=conversation_id)
    touch_conversation(session_id, conversation_id, message=question)
    update_conversation_state(message=question, role="user", history_limit=12, session_id=session_id)
    task_active = bool((conversation_state.get("task_flow") or {}).get("active_task"))
    context_messages = get_recent_messages(session_id, limit=5, conversation_id=conversation_id)
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

    if not task_active and _is_confirmation_message(question) and _assistant_asked_clarification(history_before):
        previous_question = _previous_user_message(history_before, question)
        continuation_result = resolve_institutional_query(previous_question)
        if continuation_result.get("handled"):
            response = continuation_result.get("reply") or SMART_FALLBACK_MESSAGE
            intent_label = continuation_result.get("intent")
            confidence = float(continuation_result.get("confidence", 0.75))
            category = continuation_result.get("category") or "institutional_knowledge"

            update_conversation_state(
                intent=intent_label,
                topic=category,
                history_limit=12,
                session_id=session_id,
            )
            response = _finalize_response(response, previous_question or question, category=category, profile=profile)
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
                    "source": "context_continuation",
                    "matched_question": previous_question,
                    "fallback": False,
                    "contact_suggestion": None,
                    "log_id": log_entry["id"],
                    "freshness": continuation_result.get("freshness"),
                }
            )

    if _normalize_text(question) in {"tell me about him", "tell me more about him", "about him"}:
        last_assistant = _latest_assistant_message(history_before)
        if "christian anieke" in _normalize_text(last_assistant):
            institutional_result = resolve_institutional_query("tell me about the vice chancellor")
            if institutional_result.get("handled"):
                response = institutional_result.get("reply") or SMART_FALLBACK_MESSAGE
                intent_label = institutional_result.get("intent")
                confidence = float(institutional_result.get("confidence", 1.0))
                category = institutional_result.get("category") or "institutional_knowledge"
                update_conversation_state(
                    intent=intent_label,
                    topic=category,
                    history_limit=12,
                    session_id=session_id,
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
                        "source": institutional_result.get("source", "institutional_knowledge"),
                        "matched_question": "tell me about the vice chancellor",
                        "fallback": False,
                        "contact_suggestion": None,
                        "log_id": log_entry["id"],
                        "freshness": institutional_result.get("freshness"),
                    }
                )

    if _is_institutional_info_query(question):
        institutional_result = resolve_institutional_query(question)
        if institutional_result.get("handled"):
            response = institutional_result.get("reply") or SMART_FALLBACK_MESSAGE
            intent_label = institutional_result.get("intent")
            confidence = float(institutional_result.get("confidence", 1.0))
            category = institutional_result.get("category") or "institutional_knowledge"

            update_conversation_state(
                intent=intent_label,
                topic=category,
                history_limit=12,
                session_id=session_id,
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
                    "source": institutional_result.get("source", "institutional_knowledge"),
                    "matched_question": institutional_result.get("matched_question"),
                    "fallback": False,
                    "contact_suggestion": None,
                    "log_id": log_entry["id"],
                    "freshness": institutional_result.get("freshness"),
                }
            )

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
                session_id=session_id,
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

    academic_result = resolve_academic_structure_query(question)
    if academic_result.get("handled"):
        response = academic_result.get("reply") or SMART_FALLBACK_MESSAGE
        intent_label = academic_result.get("intent")
        confidence = float(academic_result.get("confidence", 1.0))
        category = academic_result.get("category") or "academic_structure"

        update_conversation_state(
            intent=intent_label,
            topic=category,
            history_limit=12,
            session_id=session_id,
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
                "source": academic_result.get("source", "academic_structure"),
                "matched_question": None,
                "fallback": False,
                "contact_suggestion": None,
                "log_id": log_entry["id"],
            }
        )

    if detect_incomplete_message(question):
        response = build_incomplete_message_reply()
        response = _finalize_response(response, question, category="conversation_clarity", profile=profile)
        response = _commit_assistant_response(session_id, response, history_before, question=question, avoid_repeat=False)
        log_entry = add_log(
            question=question,
            intent="message_cut_off",
            response=response,
            confidence=0.95,
            status="clarification",
            workflow_type=None,
            is_fallback=False,
            is_timeout=False,
        )
        return jsonify(
            {
                "reply": response,
                "intent": "message_cut_off",
                "category": "conversation_clarity",
                "confidence": 0.95,
                "source": "clarification",
                "matched_question": None,
                "fallback": False,
                "contact_suggestion": None,
                "log_id": log_entry["id"],
            }
        )

    social_response = build_social_response(question, profile=profile)
    if social_response:
        response = _finalize_response(social_response, question, category="conversational", profile=profile)
        response = _commit_assistant_response(session_id, response, history_before, question=question, avoid_repeat=False)
        log_entry = add_log(
            question=question,
            intent="social_context",
            response=response,
            confidence=0.92,
            status="answered",
            workflow_type=None,
            is_fallback=False,
            is_timeout=False,
        )
        return jsonify(
            {
                "reply": response,
                "intent": "social_context",
                "category": "conversational",
                "confidence": 0.92,
                "source": "personality_layer",
                "matched_question": None,
                "fallback": False,
                "contact_suggestion": None,
                "log_id": log_entry["id"],
                "profile": _normalize_user_context(profile),
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
                    "contact": directory_result.get("contact"),
                }
            )

        response = directory_result.get("reply") or SMART_FALLBACK_MESSAGE
        confidence = float(directory_result.get("confidence", 1.0))
        intent_label = directory_result.get("intent")
        update_conversation_state(
            intent=intent_label,
            topic=directory_result.get("category"),
            history_limit=12,
            session_id=session_id,
        )
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
                "contact": directory_result.get("contact"),
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
                session_id=session_id,
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

    institutional_result = resolve_institutional_query(question)
    if institutional_result.get("handled"):
        response = institutional_result.get("reply") or SMART_FALLBACK_MESSAGE
        intent_label = institutional_result.get("intent")
        confidence = float(institutional_result.get("confidence", 1.0))
        category = institutional_result.get("category") or "institutional_knowledge"

        update_conversation_state(
            intent=intent_label,
            topic=category,
            history_limit=12,
            session_id=session_id,
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
                "source": institutional_result.get("source", "institutional_knowledge"),
                "matched_question": institutional_result.get("matched_question"),
                "fallback": False,
                "contact_suggestion": None,
                "log_id": log_entry["id"],
                "freshness": institutional_result.get("freshness"),
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
            session_id=session_id,
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
                session_id=session_id,
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
    feedback_aliases = {
        "yes": "helpful",
        "no": "not_helpful",
        "helpful": "helpful",
        "not_helpful": "not_helpful",
        "not helpful": "not_helpful",
        "inaccurate": "inaccurate",
        "report_inaccurate": "inaccurate",
    }
    feedback_type = feedback_aliases.get(feedback, feedback)
    comment_value = payload.get("comment")
    comment = "" if comment_value is None else str(comment_value).strip()
    session_id = _normalize_session_id(payload.get("session_id")) or get_session_id()
    bind_session_id(session_id)

    if not message or not response or feedback_type not in {"helpful", "not_helpful", "inaccurate"}:
        return jsonify({"error": "message, response, and feedback are required"}), 400

    data = {
        "session_id": session_id,
        "message": message,
        "user_message": message,
        "response": response,
        "ai_response": response,
        "feedback": feedback_type,
        "feedback_type": feedback_type,
        "comment": comment,
        "log_id": payload.get("log_id"),
        "intent": payload.get("intent"),
        "category": payload.get("category"),
        "source": payload.get("source"),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    _append_feedback_entry(data)

    return jsonify({"ok": True}), 201


@chat_bp.post("/api/profile/reset")
def profile_reset_api():
    payload = request.get_json(silent=True) or {}
    session_id = _normalize_session_id(payload.get("session_id")) or get_session_id()
    bind_session_id(session_id)
    clear_user_profile(session_id)
    reset_state = get_conversation_state(session_id)
    reset_state["history"] = []
    return jsonify({"ok": True}), 200


@chat_bp.get("/api/profile")
def profile_get_api():
    session_id = _normalize_session_id(request.args.get("session_id")) or get_session_id()
    bind_session_id(session_id)
    profile = get_user_profile(session_id)
    pending_field = get_pending_field(session_id)
    return jsonify(
        {
            "session_id": session_id,
            "profile": _normalize_user_context(profile),
            "pending_field": pending_field,
            "greeting": _build_greeting(profile),
        }
    )


@chat_bp.get("/api/history")
def history_get_api():
    session_id = _normalize_session_id(request.args.get("session_id")) or get_session_id()
    conversation_id = _normalize_session_id(request.args.get("conversation_id"))
    bind_session_id(session_id)
    conversation = ensure_active_conversation(session_id, conversation_id=conversation_id)
    conversation_id = conversation["conversation_id"] if conversation else None
    g.governor_conversation_id = conversation_id

    try:
        limit = int(request.args.get("limit", 80))
    except (TypeError, ValueError):
        limit = 80
    limit = min(max(limit, 1), 200)

    profile = get_user_profile(session_id)
    messages = get_recent_messages(session_id, limit=limit, conversation_id=conversation_id)
    return jsonify(
        {
            "session_id": session_id,
            "conversation_id": conversation_id,
            "conversation": conversation,
            "messages": messages,
            "profile": _normalize_user_context(profile),
            "greeting": _build_greeting(profile),
        }
    )


@chat_bp.get("/api/conversations")
def conversations_get_api():
    session_id = _normalize_session_id(request.args.get("session_id")) or get_session_id()
    bind_session_id(session_id)
    active = ensure_active_conversation(session_id, conversation_id=request.args.get("conversation_id"))
    conversations = list_conversations(session_id)
    return jsonify(
        {
            "session_id": session_id,
            "active_conversation_id": active["conversation_id"] if active else None,
            "conversations": conversations,
        }
    )


@chat_bp.post("/api/conversations")
def conversations_create_api():
    payload = request.get_json(silent=True) or {}
    session_id = _normalize_session_id(payload.get("session_id")) or get_session_id()
    bind_session_id(session_id)
    title = str(payload.get("title") or "").strip() or None
    conversation = create_conversation(session_id, title=title)
    return jsonify({"session_id": session_id, "conversation": conversation}), 201


@chat_bp.get("/api/conversations/<conversation_id>")
def conversation_detail_api(conversation_id):
    session_id = _normalize_session_id(request.args.get("session_id")) or get_session_id()
    bind_session_id(session_id)
    conversation = get_conversation(session_id, conversation_id)
    if not conversation:
        return jsonify({"error": "conversation not found"}), 404

    try:
        limit = int(request.args.get("limit", 200))
    except (TypeError, ValueError):
        limit = 200
    limit = min(max(limit, 1), 300)

    profile = get_user_profile(session_id)
    messages = get_recent_messages(session_id, limit=limit, conversation_id=conversation_id)
    return jsonify(
        {
            "session_id": session_id,
            "conversation_id": conversation_id,
            "conversation": conversation,
            "messages": messages,
            "profile": _normalize_user_context(profile),
            "greeting": _build_greeting(profile),
        }
    )


@chat_bp.patch("/api/conversations/<conversation_id>")
def conversation_rename_api(conversation_id):
    payload = request.get_json(silent=True) or {}
    session_id = _normalize_session_id(payload.get("session_id")) or get_session_id()
    bind_session_id(session_id)
    title = str(payload.get("title") or "").strip()
    if not title:
        return jsonify({"error": "title is required"}), 400

    conversation = rename_conversation(session_id, conversation_id, title)
    if not conversation:
        return jsonify({"error": "conversation not found"}), 404

    return jsonify({"session_id": session_id, "conversation": conversation})


@chat_bp.delete("/api/conversations/<conversation_id>")
def conversation_delete_api(conversation_id):
    payload = request.get_json(silent=True) or {}
    session_id = _normalize_session_id(payload.get("session_id")) or get_session_id()
    bind_session_id(session_id)

    deleted = delete_conversation(session_id, conversation_id)
    if not deleted:
        return jsonify({"error": "conversation not found"}), 404

    latest = ensure_active_conversation(session_id)
    return jsonify(
        {
            "ok": True,
            "session_id": session_id,
            "active_conversation_id": latest["conversation_id"] if latest else None,
            "conversation": latest,
            "conversations": list_conversations(session_id),
        }
    )


@chat_bp.get("/api/logs")
def logs_api():
    protection = require_admin_access()
    if protection:
        return protection

    logs = list_chat_logs(limit=100)
    if logs:
        return jsonify(logs)
    return jsonify(QUERY_LOGS[-100:])


@chat_bp.get("/api/intents")
def intents_api():
    protection = require_admin_access()
    if protection:
        return protection

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
