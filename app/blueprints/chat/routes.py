import re

from flask import Blueprint, current_app, jsonify, request

from app.services.contact_directory import load_contact_directory, resolve_contact_query
from app.services.directory import get_hostel, get_ict, get_student_affairs, get_vc_contact
from app.services.knowledge_base import detect_hostel_context, find_relevant_entries, match_conversational
from app.services.llm import call_llm_with_retry
from app.services.store import (
    QUERY_LOGS,
    add_log,
    get_conversation_state,
    update_conversation_state,
)
from app.services.task_flow import process_task_message
from app.services.task_requests_db import list_chat_logs

chat_bp = Blueprint("chat", __name__)

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


def _build_contact_prompt(question, context_messages):
    context_text = _render_context(context_messages)
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
        "Current user message:\n"
        f"{question}\n\n"
        "Relevant conversation context:\n"
        f"{context_text}\n\n"
        "Available directory details:\n"
        f"{directory_snapshot}"
    )


def _handle_directory_contact(question, context_messages):
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
            "prompt": _build_contact_prompt(question, context_messages),
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


def _build_prompt(question, context_messages, kb_entries, extra_instructions=None):
    context_text = _render_context(context_messages)
    kb_text = _render_kb_entries(kb_entries)
    extra_text = f"\n\nSpecial instructions:\n{extra_instructions}" if extra_instructions else ""

    return (
        "Current user message:\n"
        f"{question}\n\n"
        "Relevant conversation context (last 3 to 5 messages):\n"
        f"{context_text}\n\n"
        "Relevant knowledge base entries:\n"
        f"{kb_text}"
        f"{extra_text}\n\n"
        "How to respond:\n"
        "1. Interpret all natural language naturally.\n"
        "2. Decide whether to answer conversationally, use knowledge base information, or combine both.\n"
        "3. If the query is unrelated, respond conversationally and gently guide back to university context when appropriate.\n"
        "4. Keep the response clean and conversational.\n"
        "5. Use short paragraphs with line breaks. Avoid markdown symbols like *, #, or heavy bullet formatting."
    )


@chat_bp.post("/api/chat")
def chat_api():
    payload = request.get_json(silent=True) or {}
    question = (payload.get("message") or "").strip()

    if not question:
        return jsonify({"error": "message is required"}), 400

    conversation_state = get_conversation_state()
    context_messages = _history_messages(conversation_state, limit=5)
    update_conversation_state(message=question, role="user", history_limit=12)

    task_result = process_task_message(question, conversation_state)

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
        update_conversation_state(message=response, role="assistant", history_limit=12)
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

    directory_result = _handle_directory_contact(question, context_messages)
    if directory_result.get("handled"):
        if directory_result.get("use_llm"):
            prompt = directory_result.get("prompt") or _build_contact_prompt(question, context_messages)
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
            update_conversation_state(message=response, role="assistant", history_limit=12)
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
        update_conversation_state(message=response, role="assistant", history_limit=12)
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

        update_conversation_state(message=response, role="assistant", history_limit=12)
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
        update_conversation_state(message=response, role="assistant", history_limit=12)
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
    if hostel_context:
        extra_instructions = HOSTEL_FALLBACK_INSTRUCTION
        if _is_hostel_registration_context(context_messages):
            extra_instructions = f"{extra_instructions}\n\n{HOSTEL_REGISTRATION_NOTE}"

    prompt = _build_prompt(question, context_messages, kb_entries, extra_instructions=extra_instructions)
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
        response = SMART_FALLBACK_MESSAGE
        source = "llm_fallback"
        fallback = True
        status = "unanswered"

    update_conversation_state(message=response, role="assistant", history_limit=12)

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
