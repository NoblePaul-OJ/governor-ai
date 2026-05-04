import copy
import re

from flask import session

from app.services.store import get_session_id, get_user_profile
from app.services.task_requests_db import save_task_request


WORKFLOW_DEFINITIONS = {
    "book_hostel": {
        "label": "Hostel Booking",
        "output_type": "request_summary",
        "office": "Student Affairs Office",
        "keywords": [
            "hostel booking",
            "book hostel",
            "hostel application",
            "apply hostel",
            "apply for hostel",
            "i want hostel",
            "want hostel",
            "need hostel",
            "hostel registration",
        ],
        "intro": "Alright, I will guide you through hostel application at Godfrey Okoye University.",
        "step_1_context": "First step: confirm if you have paid your school fees, because hostel access depends on that.",
        "fields": [
            {
                "key": "fees_paid",
                "label": "School Fees Paid",
                "question": "Have you paid your school fees? Reply yes or no.",
                "aliases": ["fees paid", "school fees", "payment status"],
            },
            {
                "key": "full_name",
                "label": "Full Name",
                "question": "Please share your full name.",
                "aliases": ["name", "full name"],
            },
            {
                "key": "matric_number",
                "label": "Matric Number",
                "question": "What is your matric number?",
                "aliases": ["matric", "matric number", "reg number"],
            },
            {
                "key": "department_level",
                "label": "Department and Level",
                "question": "Which department and level are you in?",
                "aliases": ["department", "level", "department and level"],
            },
            {
                "key": "preferred_hostel",
                "label": "Preferred Hostel",
                "question": "Which hostel do you prefer?",
                "aliases": ["hostel", "preferred hostel"],
            },
            {
                "key": "phone",
                "label": "Phone Number",
                "question": "What phone number should be used for updates?",
                "aliases": ["phone", "phone number", "contact"],
            },
        ],
        "step_2": {
            "question": "Reply continue when you are ready for the final summary.",
        },
    },
    "vc_appointment": {
        "label": "VC Appointment",
        "output_type": "appointment_letter",
        "recipient": "Vice Chancellor",
        "email": "vc.office@gouni.edu.ng",
        "keywords": [
            "see the vc",
            "meet the vc",
            "appointment with vc",
            "vc appointment",
            "vice chancellor appointment",
            "meet vc",
            "meeting with vice chancellor",
            "request appointment with vc",
        ],
        "intro": "Alright, I will guide you through requesting an appointment with the Vice Chancellor.",
        "step_1_context": "First step: share your full name so I can begin the appointment request.",
        "fields": [
            {
                "key": "name",
                "label": "Name",
                "question": "Please share your full name.",
                "aliases": ["name", "full name"],
            },
            {
                "key": "matric",
                "label": "Matric Number",
                "question": "Please share your matric number and department.",
                "aliases": ["matric", "matric number", "reg number"],
            },
            {
                "key": "department",
                "label": "Department",
                "question": "Please share your matric number and department.",
                "aliases": ["department", "level", "department and level"],
            },
            {
                "key": "reason",
                "label": "Reason",
                "question": "What is the reason for the appointment?",
                "aliases": ["purpose", "reason"],
            },
            {
                "key": "urgency",
                "label": "Urgency",
                "question": "How urgent is the appointment request?",
                "aliases": ["urgent", "urgency"],
            },
            {
                "key": "preferred_time",
                "label": "Preferred Time",
                "question": "What preferred time would you like for the appointment?",
                "aliases": ["time", "preferred time"],
            },
        ],
        "step_2": {
            "question": "Reply continue when you are ready for the final summary.",
        },
    },
    "contact_request": {
        "label": "Contact Request",
        "output_type": "request_summary",
        "office": "Relevant University Office",
        "keywords": [
            "contact request",
            "request contact",
            "help me contact",
            "need to contact office",
            "connect me to office",
        ],
        "intro": "Alright, I will guide you through creating a formal contact request.",
        "step_1_context": "First step: tell me who you want to contact and why, so the request can be routed correctly.",
        "fields": [
            {
                "key": "full_name",
                "label": "Full Name",
                "question": "Please share your full name.",
                "aliases": ["name", "full name"],
            },
            {
                "key": "target_office",
                "label": "Target Office",
                "question": "Which office do you want to contact?",
                "aliases": ["office", "target office"],
            },
            {
                "key": "purpose",
                "label": "Contact Purpose",
                "question": "What is the purpose of this contact request?",
                "aliases": ["purpose", "reason"],
            },
            {
                "key": "preferred_channel",
                "label": "Preferred Channel",
                "question": "How do you prefer to be contacted back: email, phone, or both?",
                "aliases": ["channel", "preferred channel"],
            },
            {
                "key": "callback_contact",
                "label": "Callback Contact",
                "question": "Please share your callback phone or email.",
                "aliases": ["callback", "contact", "phone", "email"],
            },
        ],
        "step_2": {
            "question": "Reply continue when you are ready for the final summary.",
        },
    },
    "report_issue": {
        "label": "Complaint or Issue Report",
        "output_type": "request_summary",
        "office": "Student Affairs and ICT Support",
        "keywords": [
            "report issue",
            "report problem",
            "raise issue",
            "lodge complaint",
            "issue report",
        ],
        "intro": "Alright, I will guide you through reporting this issue properly.",
        "step_1_context": "First step: share clear details so the university can resolve the issue faster.",
        "fields": [
            {
                "key": "full_name",
                "label": "Full Name",
                "question": "Please share your full name.",
                "aliases": ["name", "full name"],
            },
            {
                "key": "matric_number",
                "label": "Matric Number",
                "question": "What is your matric number?",
                "aliases": ["matric", "matric number", "reg number"],
            },
            {
                "key": "issue_type",
                "label": "Issue Type",
                "question": "What kind of issue is this?",
                "aliases": ["type", "issue type", "category"],
            },
            {
                "key": "issue_location",
                "label": "Issue Location or System",
                "question": "Where did this issue happen?",
                "aliases": ["location", "system", "page"],
            },
            {
                "key": "issue_details",
                "label": "Issue Details",
                "question": "Please describe the issue clearly.",
                "aliases": ["details", "description", "issue"],
            },
        ],
        "step_2": {
            "question": "Reply continue when you are ready for the final summary.",
        },
    },
    "get_transcript": {
        "label": "Transcript Request",
        "output_type": "request_summary",
        "office": "Exams and Records Office",
        "keywords": [
            "get transcript",
            "request transcript",
            "need transcript",
            "transcript request",
            "collect transcript",
        ],
        "intro": "Alright, I will guide you through transcript request steps.",
        "step_1_context": "First step: share your academic record details so the records office can process your request.",
        "fields": [
            {
                "key": "full_name",
                "label": "Full Name",
                "question": "Please share your full name.",
                "aliases": ["name", "full name"],
            },
            {
                "key": "matric_number",
                "label": "Matric Number",
                "question": "What is your matric number?",
                "aliases": ["matric", "matric number", "reg number"],
            },
            {
                "key": "department",
                "label": "Department",
                "question": "Which department did you graduate from or currently belong to?",
                "aliases": ["department"],
            },
            {
                "key": "graduation_year",
                "label": "Graduation Year",
                "question": "What is your graduation year or expected year?",
                "aliases": ["year", "graduation year"],
            },
            {
                "key": "delivery_method",
                "label": "Delivery Method",
                "question": "How should your transcript be delivered: pickup, email, or courier?",
                "aliases": ["delivery", "delivery method"],
            },
        ],
        "step_2": {
            "question": "Reply continue when you are ready for the final summary.",
        },
    },
}

_CANCEL_TERMS = {
    "cancel",
    "stop",
    "exit",
    "quit",
    "reset",
    "start over",
    "never mind",
    "nevermind",
}

_HOSTEL_BOOKING_PHRASES = {
    "hostel booking",
    "book hostel",
    "hostel application",
    "apply hostel",
    "apply for hostel",
    "i want hostel",
    "want hostel",
    "need hostel",
    "hostel registration",
    "accommodation registration",
    "how to apply for hostel",
    "need accommodation",
    "want accommodation",
}

_HOSTEL_SUPPORT_PHRASES = {
    "hostel full",
    "no space",
    "no accommodation",
    "hostels are full",
    "hostel problem",
    "hostel complaint",
    "issue with hostel",
    "complain hostel",
    "my room has issues",
    "room issue",
    "no water",
    "electricity problem",
    "complain about hostel",
    "change hostel",
    "change room",
    "move hostel",
}

_TASK_HINT = (
    "You can say hostel booking, VC appointment, contact request, complaint or issue report, transcript request, or travel permission."
)

_SESSION_KEY = "task_flow_state"


def _normalize(text):
    cleaned = re.sub(r"[^a-zA-Z0-9\s]", " ", (text or "").lower())
    return " ".join(cleaned.split())


def _is_yes(value):
    normalized = _normalize(value)
    yes_terms = {"yes", "yeah", "yep", "done", "completed", "submitted", "ready", "paid", "true"}
    return any(term in normalized.split() for term in yes_terms) or (
        "not yet" not in normalized and "yes" in normalized
    )


def _is_no(value):
    normalized = _normalize(value)
    no_terms = {"no", "not", "never", "pending", "false"}
    if "not yet" in normalized:
        return True
    return any(term in normalized.split() for term in no_terms)


def _is_cancel_message(message):
    normalized = _normalize(message)
    return any(term in normalized for term in _CANCEL_TERMS)


def _contains_any_phrase(normalized, phrases):
    return any(phrase in normalized for phrase in phrases)


def _is_hostel_support_message(normalized):
    if not normalized:
        return False
    return _contains_any_phrase(normalized, _HOSTEL_SUPPORT_PHRASES)


def _is_hostel_booking_message(normalized):
    if not normalized:
        return False
    if _contains_any_phrase(normalized, _HOSTEL_BOOKING_PHRASES):
        return True

    hostel_terms = {"hostel", "accommodation"}
    booking_signals = {"apply", "application", "book", "booking", "register", "registration", "need", "want"}
    words = set(normalized.split())
    return bool(words & hostel_terms) and bool(words & booking_signals)


def handle_travel_permission(profile):
    response = ""

    response += "If you want permission to travel, you need to go through the Student Affairs process.\n\n"

    response += "First, write a simple request stating your reason for travel and how long you will be away.\n\n"

    response += "Then take it to the Student Affairs Office for approval.\n\n"

    response += "If required, you may also need endorsement from your department.\n\n"

    response += "Student Affairs Contact:\n"
    response += "Phone: 08166915454\n"
    response += "Office: Not available yet\n\n"

    response += "For urgent cases, it is better to go there physically rather than relying only on calls."

    return response


def _detect_intent(message):
    normalized = _normalize(message)
    if not normalized:
        return None

    if _is_hostel_support_message(normalized):
        return None

    if _is_hostel_booking_message(normalized):
        return "book_hostel"

    best_key = None
    best_score = 0
    for workflow_key, payload in WORKFLOW_DEFINITIONS.items():
        for phrase in payload["keywords"]:
            phrase_n = _normalize(phrase)
            if not phrase_n:
                continue
            if phrase_n in normalized:
                score = len(phrase_n.split())
                if score > best_score:
                    best_score = score
                    best_key = workflow_key
    return best_key


def _state_version(conversation_state):
    return int(conversation_state.get("state_version") or 0)


def _empty_task_state(version=0):
    return {
        "active_task": None,
        "current_step": None,
        "step_index": 0,
        "collected": {},
        "completed_task": None,
        "last_output": None,
        "paused_task": None,
        "paused_step": None,
        "paused_step_index": 0,
        "paused_collected": {},
        "paused_workflows": {},
        "vc_appointment": _empty_vc_state(),
        "state_version": version,
    }


def _copy_task_state(task_state):
    return copy.deepcopy(task_state)


def _empty_vc_state():
    return {
        "name": "",
        "matric": "",
        "department": "",
        "reason": "",
        "urgency": "",
        "preferred_time": "",
        "summary": "",
        "confirmed": False,
        "letter": "",
    }


def _save_task_state(task_state, conversation_state):
    version = _state_version(conversation_state)
    task_state["state_version"] = version
    copied = _copy_task_state(task_state)
    session[_SESSION_KEY] = copied
    session.modified = True
    conversation_state["task_flow"] = _copy_task_state(task_state)
    return task_state


def _ensure_task_state(conversation_state):
    version = _state_version(conversation_state)
    session_state = session.get(_SESSION_KEY)
    if not isinstance(session_state, dict) or session_state.get("state_version") != version:
        task_state = conversation_state.get("task_flow")
        if not isinstance(task_state, dict) or task_state.get("state_version") != version:
            task_state = _empty_task_state(version)
        else:
            task_state = _copy_task_state(task_state)
        task_state["state_version"] = version
        task_state.setdefault("paused_task", None)
        task_state.setdefault("paused_step", None)
        task_state.setdefault("paused_step_index", 0)
        task_state.setdefault("paused_collected", {})
        task_state.setdefault("paused_workflows", {})
        task_state.setdefault("vc_appointment", _empty_vc_state())
        _save_task_state(task_state, conversation_state)
        return task_state

    task_state = _copy_task_state(session_state)
    task_state["state_version"] = version
    task_state.setdefault("paused_task", None)
    task_state.setdefault("paused_step", None)
    task_state.setdefault("paused_step_index", 0)
    task_state.setdefault("paused_collected", {})
    task_state.setdefault("paused_workflows", {})
    task_state.setdefault("vc_appointment", _empty_vc_state())
    conversation_state["task_flow"] = _copy_task_state(task_state)
    return task_state


def _reset_active_workflow(task_state):
    task_state["active_task"] = None
    task_state["current_step"] = None
    task_state["step_index"] = 0
    task_state["collected"] = {}


def _vc_data(task_state):
    data = task_state.get("vc_appointment")
    if not isinstance(data, dict):
        data = _empty_vc_state()
    else:
        defaults = _empty_vc_state()
        for key, value in defaults.items():
            data.setdefault(key, value)
    task_state["vc_appointment"] = data
    return data


def _set_vc_step(task_state, step, index):
    task_state["active_task"] = "vc_appointment"
    task_state["current_step"] = step
    task_state["step_index"] = index


def _pause_vc_workflow(task_state):
    _pause_active_workflow(task_state)


def _pause_active_workflow(task_state):
    active_task = task_state.get("active_task")
    if not active_task:
        return

    if active_task == "vc_appointment":
        data = copy.deepcopy(_vc_data(task_state))
    else:
        data = copy.deepcopy(task_state.get("collected", {}))

    paused_workflows = dict(task_state.get("paused_workflows") or {})
    paused_workflows[active_task] = {
        "step": task_state.get("current_step"),
        "step_index": int(task_state.get("step_index", 0) or 0),
        "collected": data,
    }
    task_state["paused_workflows"] = paused_workflows
    task_state["paused_task"] = active_task
    task_state["paused_step"] = task_state.get("current_step")
    task_state["paused_step_index"] = task_state.get("step_index", 0)
    task_state["paused_collected"] = data
    task_state["active_task"] = None
    task_state["current_step"] = None
    task_state["step_index"] = 0


def _resume_vc_workflow(task_state):
    paused_workflows = dict(task_state.get("paused_workflows") or {})
    paused = paused_workflows.get("vc_appointment", {})
    if not isinstance(paused, dict):
        paused = {}
    paused_collected = paused.get("collected") if isinstance(paused, dict) else None
    if not isinstance(paused_collected, dict):
        paused_collected = task_state.get("paused_collected")
    if not isinstance(paused_collected, dict):
        paused_collected = _empty_vc_state()
    vc_data = _vc_data(task_state)
    vc_data.update(paused_collected)
    task_state["collected"] = copy.deepcopy(vc_data)
    paused_step = paused.get("step") or task_state.get("paused_step") or "step_1"
    paused_index = int(paused.get("step_index") or task_state.get("paused_step_index") or 1)
    paused_workflows.pop("vc_appointment", None)
    task_state["paused_workflows"] = paused_workflows
    task_state["paused_task"] = None
    task_state["paused_step"] = None
    task_state["paused_step_index"] = 0
    task_state["paused_collected"] = {}
    task_state["active_task"] = "vc_appointment"
    task_state["current_step"] = paused_step
    task_state["step_index"] = paused_index


def _is_vc_trigger_message(message):
    detected = _detect_intent(message)
    return detected == "vc_appointment"


def _is_general_interruption(message):
    normalized = _normalize(message)
    if not normalized:
        return False

    if "?" in (message or ""):
        return True

    question_starts = (
        "how ",
        "what ",
        "where ",
        "when ",
        "why ",
        "can you",
        "could you",
        "do you know",
        "please help",
        "help me contact",
        "tell me",
    )
    if normalized.startswith(question_starts):
        return True

    detected = _detect_intent(message)
    return detected is not None and detected != "vc_appointment"


def _vc_summary_lines(vc_data):
    return [
        "Step 6",
        "VC appointment summary",
        "",
        f"Name: {vc_data.get('name', '')}",
        f"Matric: {vc_data.get('matric', '')}",
        f"Department: {vc_data.get('department', '')}",
        f"Reason: {vc_data.get('reason', '')}",
        f"Urgency: {vc_data.get('urgency', '')}",
        f"Preferred time: {vc_data.get('preferred_time', '')}",
        "",
        "Please confirm if I should generate the formal appointment letter.",
        "Reply yes to confirm or no to review the details again.",
    ]


def _vc_letter_output(vc_data):
    lines = [
        "Formal Appointment Letter",
        "",
        "To: Vice Chancellor",
        "Godfrey Okoye University",
        "",
        "Dear Vice Chancellor,",
        "",
        "I respectfully request an appointment with you.",
        "",
        f"Name: {vc_data.get('name', '')}",
        f"Matric: {vc_data.get('matric', '')}",
        f"Department: {vc_data.get('department', '')}",
        f"Reason: {vc_data.get('reason', '')}",
        f"Urgency: {vc_data.get('urgency', '')}",
        f"Preferred time: {vc_data.get('preferred_time', '')}",
        "",
        "Please consider this request and grant me an opportunity to meet at your convenience.",
        "",
        "Thank you.",
        "",
        "Sincerely,",
        vc_data.get("name", "Student"),
    ]
    return "\n".join(lines)


def _extract_vc_name(message):
    return (message or "").strip()


def _extract_vc_matric_department(message):
    text = (message or "").strip()
    matric = ""
    department = ""

    normalized = _normalize(text)
    if ":" in text:
        segments = re.split(r"[,;\n]", text)
        for segment in segments:
            if ":" not in segment:
                continue
            lhs, rhs = segment.split(":", 1)
            label = _normalize(lhs)
            value = rhs.strip()
            if not value:
                continue
            if "matric" in label or "reg" in label:
                matric = value
            elif "dept" in label or "department" in label:
                department = value

    if not matric or not department:
        parts = [part.strip() for part in re.split(r",|/| and |\n", text) if part.strip()]
        if len(parts) >= 2:
            if not matric:
                matric = parts[0]
            if not department:
                department = parts[1]
        elif len(parts) == 1:
            if not matric:
                matric = parts[0]

    if not matric and "matric" in normalized:
        matric = text
    if not department and "department" in normalized:
        department = text

    return matric, department


def _extract_vc_single_field(message):
    return (message or "").strip()


def _build_vc_prompt(step, vc_data):
    if step == "step_1":
        return "\n".join(
            [
                "Step 1",
                "Please share your full name.",
            ]
        )

    if step == "step_2":
        return "\n".join(
            [
                "Step 2",
                "Please share your matric number and department.",
            ]
        )

    if step == "step_3":
        return "\n".join(
            [
                "Step 3",
                "What is the reason for the appointment?",
            ]
        )

    if step == "step_4":
        return "\n".join(
            [
                "Step 4",
                "How urgent is the appointment request?",
            ]
        )

    if step == "step_5":
        return "\n".join(
            [
                "Step 5",
                "What preferred time would you like for the appointment?",
            ]
        )

    if step == "step_6":
        return "\n".join(_vc_summary_lines(vc_data))

    return "\n".join(_vc_summary_lines(vc_data))


def _start_vc_workflow(task_state):
    task_state["active_task"] = "vc_appointment"
    task_state["current_step"] = "step_1"
    task_state["step_index"] = 1
    task_state["completed_task"] = None
    task_state["last_output"] = None
    task_state["paused_task"] = None
    task_state["paused_step"] = None
    task_state["paused_step_index"] = 0
    task_state["paused_collected"] = {}
    task_state["vc_appointment"] = _empty_vc_state()
    task_state["collected"] = task_state["vc_appointment"]
    return "\n".join(
        [
            "Alright, I will guide you through requesting an appointment with the Vice Chancellor.",
            "",
            "Step 1",
            "Please share your full name.",
        ]
    )


def _complete_vc_workflow(task_state, conversation_state):
    vc_data = _vc_data(task_state)
    output = _vc_letter_output(vc_data)
    request_id = None
    try:
        request_id = save_task_request(
            task_key="vc_appointment",
            task_label="VC Appointment",
            output_type="appointment_letter",
            payload=vc_data,
        )
    except Exception:
        request_id = None

    task_state["active_task"] = None
    task_state["current_step"] = None
    task_state["step_index"] = 0
    task_state["completed_task"] = "vc_appointment"
    task_state["last_output"] = output
    task_state["collected"] = {}
    _save_task_state(task_state, conversation_state)

    if request_id is not None:
        output = f"{output}\n\nReference ID: {request_id}"

    return {
        "reply": output,
        "task_key": "vc_appointment",
        "task_label": "VC Appointment",
        "output_type": "appointment_letter",
        "current_step": None,
        "completed": True,
        "request_id": request_id,
    }


def _process_vc_message(question, conversation_state):
    task_state = _ensure_task_state(conversation_state)
    vc_data = _vc_data(task_state)
    active_task = task_state.get("active_task")
    current_step = task_state.get("current_step")
    message = (question or "").strip()
    normalized = _normalize(message)

    if active_task != "vc_appointment" and task_state.get("paused_task") == "vc_appointment":
        if _is_vc_trigger_message(message) or normalized in {"continue", "resume", "go on"}:
            _resume_vc_workflow(task_state)
            _save_task_state(task_state, conversation_state)
            current_step = task_state.get("current_step")
            vc_data = _vc_data(task_state)
            return {
                "handled": True,
                "reply": _build_vc_prompt(current_step, vc_data),
                "task_key": "vc_appointment",
                "task_label": "VC Appointment",
                "output_type": "appointment_letter",
                "current_step": current_step,
                "completed": False,
                "request_id": None,
            }

    if active_task != "vc_appointment" and not _is_vc_trigger_message(message):
        return {"handled": False}

    if active_task != "vc_appointment":
        if task_state.get("active_task"):
            _pause_active_workflow(task_state)
        reply = _start_vc_workflow(task_state)
        _save_task_state(task_state, conversation_state)
        return {
            "handled": True,
            "reply": reply,
            "task_key": "vc_appointment",
            "task_label": "VC Appointment",
            "output_type": "appointment_letter",
            "current_step": "step_1",
            "completed": False,
            "request_id": None,
        }

    if _is_general_interruption(message):
        _pause_vc_workflow(task_state)
        _save_task_state(task_state, conversation_state)
        return {"handled": False, "paused": True}

    if current_step == "step_1":
        vc_data["name"] = _extract_vc_name(message)
        task_state["collected"] = copy.deepcopy(vc_data)
        _set_vc_step(task_state, "step_2", 2)
        reply = "\n".join(
            [
                "Step 2",
                f"Thank you, {vc_data['name'] or 'student'}.",
                "Please share your matric number and department.",
            ]
        )
        _save_task_state(task_state, conversation_state)
        return {
            "handled": True,
            "reply": reply,
            "task_key": "vc_appointment",
            "task_label": "VC Appointment",
            "output_type": "appointment_letter",
            "current_step": "step_2",
            "completed": False,
            "request_id": None,
        }

    if current_step == "step_2":
        matric, department = _extract_vc_matric_department(message)
        if matric:
            vc_data["matric"] = matric
        if department:
            vc_data["department"] = department
        task_state["collected"] = copy.deepcopy(vc_data)
        _set_vc_step(task_state, "step_3", 3)
        reply = "\n".join(
            [
                "Step 3",
                "Thank you.",
                "What is the reason for the appointment?",
            ]
        )
        _save_task_state(task_state, conversation_state)
        return {
            "handled": True,
            "reply": reply,
            "task_key": "vc_appointment",
            "task_label": "VC Appointment",
            "output_type": "appointment_letter",
            "current_step": "step_3",
            "completed": False,
            "request_id": None,
        }

    if current_step == "step_3":
        vc_data["reason"] = _extract_vc_single_field(message)
        task_state["collected"] = copy.deepcopy(vc_data)
        _set_vc_step(task_state, "step_4", 4)
        reply = "\n".join(
            [
                "Step 4",
                "How urgent is the appointment request?",
            ]
        )
        _save_task_state(task_state, conversation_state)
        return {
            "handled": True,
            "reply": reply,
            "task_key": "vc_appointment",
            "task_label": "VC Appointment",
            "output_type": "appointment_letter",
            "current_step": "step_4",
            "completed": False,
            "request_id": None,
        }

    if current_step == "step_4":
        vc_data["urgency"] = _extract_vc_single_field(message)
        task_state["collected"] = copy.deepcopy(vc_data)
        _set_vc_step(task_state, "step_5", 5)
        reply = "\n".join(
            [
                "Step 5",
                "What preferred time would you like for the appointment?",
            ]
        )
        _save_task_state(task_state, conversation_state)
        return {
            "handled": True,
            "reply": reply,
            "task_key": "vc_appointment",
            "task_label": "VC Appointment",
            "output_type": "appointment_letter",
            "current_step": "step_5",
            "completed": False,
            "request_id": None,
        }

    if current_step == "step_5":
        vc_data["preferred_time"] = _extract_vc_single_field(message)
        vc_data["summary"] = "\n".join(_vc_summary_lines(vc_data))
        task_state["collected"] = copy.deepcopy(vc_data)
        _set_vc_step(task_state, "step_6", 6)
        reply = _build_vc_prompt("step_6", vc_data)
        _save_task_state(task_state, conversation_state)
        return {
            "handled": True,
            "reply": reply,
            "task_key": "vc_appointment",
            "task_label": "VC Appointment",
            "output_type": "appointment_letter",
            "current_step": "step_6",
            "completed": False,
            "request_id": None,
        }

    if current_step == "step_6":
        if _is_yes(message):
            vc_data["confirmed"] = True
            task_state["collected"] = copy.deepcopy(vc_data)
            _save_task_state(task_state, conversation_state)
            completed = _complete_vc_workflow(task_state, conversation_state)
            completed["handled"] = True
            return completed

        if _is_no(message):
            vc_data["confirmed"] = False
            task_state["collected"] = copy.deepcopy(vc_data)
            task_state["current_step"] = "step_6"
            task_state["step_index"] = 6
            _save_task_state(task_state, conversation_state)
            return {
                "handled": True,
                "reply": "\n".join(
                    [
                        "Step 6",
                        "No problem. Tell me which detail you want to update, or say continue to review the summary again.",
                    ]
                ),
                "task_key": "vc_appointment",
                "task_label": "VC Appointment",
                "output_type": "appointment_letter",
                "current_step": "step_6",
                "completed": False,
                "request_id": None,
            }

        vc_data["summary"] = "\n".join(_vc_summary_lines(vc_data))
        task_state["collected"] = copy.deepcopy(vc_data)
        _save_task_state(task_state, conversation_state)
        return {
            "handled": True,
            "reply": "\n".join(_vc_summary_lines(vc_data)),
            "task_key": "vc_appointment",
            "task_label": "VC Appointment",
            "output_type": "appointment_letter",
            "current_step": "step_6",
            "completed": False,
            "request_id": None,
        }

    return {"handled": False}


def _extract_structured_answers(message, workflow):
    answers = {}
    segments = re.split(r"[,\n;]", message or "")
    fields = list(workflow["fields"])

    for segment in segments:
        if ":" not in segment:
            continue
        lhs, rhs = segment.split(":", 1)
        label = _normalize(lhs)
        value = rhs.strip()
        if not label or not value:
            continue

        for field in fields:
            aliases = [_normalize(a) for a in field.get("aliases", [])]
            aliases.append(_normalize(field["label"]))
            if label in aliases:
                answers[field["key"]] = value
                break
    return answers


def _next_missing_field(workflow, collected):
    for field in workflow["fields"]:
        value = str(collected.get(field["key"], "")).strip()
        if not value:
            return field
    return None


def _step2_context(workflow_key, collected):
    if workflow_key == "book_hostel":
        if _is_yes(collected.get("fees_paid", "")):
            return "You can continue with hostel processing. Keep your payment receipt and hostel choice ready."
        return "Please complete school fees payment first before hostel allocation can continue."

    if workflow_key == "vc_appointment":
        return "Your request details are ready. Keep your documents and preferred date in mind before submission."

    if workflow_key == "contact_request":
        office = collected.get("target_office", "the selected office")
        return f"I will route this request to {office}. Keep your callback contact available."

    if workflow_key == "report_issue":
        return "Please keep screenshots or evidence ready so the issue can be handled faster."

    if workflow_key == "get_transcript":
        return "Please keep your payment details and delivery preference ready for the records office."

    return "I will now prepare the next action step."


def _next_actions(workflow_key, workflow, collected):
    if workflow_key == "book_hostel":
        actions = []
        if _is_no(collected.get("fees_paid", "")):
            actions.append("Complete school fees payment first through the approved payment channel.")
        else:
            actions.append("Keep your school fees receipt ready for verification.")

        actions.append("Submit the hostel request form on the student portal.")
        actions.append("Monitor your portal and student affairs updates for hostel allocation.")
        actions.append("If allocation delays continue, follow up with Student Affairs Office.")
        return actions

    if workflow_key == "vc_appointment":
        actions = [
            "Send the appointment request draft to the VC office email.",
            "Monitor your email and phone for response from the VC office.",
        ]
        return actions

    if workflow_key == "contact_request":
        actions = [
            "Submit this contact request through the official university communication channel.",
            "Keep your callback contact available for response.",
        ]
        return actions

    if workflow_key == "report_issue":
        actions = [
            "Submit the issue report to Student Affairs or ICT support based on issue type.",
            "Keep screenshots or evidence ready for verification.",
            "Follow up quickly if the issue is still affecting your access or learning.",
        ]
        return actions

    if workflow_key == "get_transcript":
        actions = [
            "Submit your transcript request to Exams and Records Office.",
            "Track confirmation or collection details from the records office.",
        ]
        return actions

    return ["Proceed with the responsible office using the details collected."]


def _build_summary_output(workflow_key, workflow, collected):
    lines = [
        "Step 3",
        f"Final summary for {workflow['label']}",
        "",
        "Request summary",
        f"Destination office: {workflow.get('office', workflow.get('recipient', 'University Office'))}",
        "",
        "Collected details:",
    ]
    for field in workflow["fields"]:
        value = collected.get(field["key"], "Not provided")
        lines.append(f"{field['label']}: {value}")

    actions = _next_actions(workflow_key, workflow, collected)
    lines.extend(["", "Next actions:"])
    for index, action in enumerate(actions, start=1):
        lines.append(f"Action {index}: {action}")
    return "\n".join(lines)


def _subject_from_collected(workflow, collected):
    subject = str(collected.get("subject", "")).strip()
    if subject:
        return subject
    return f"{workflow['label']} Request"


def _build_email_output(workflow_key, workflow, collected):
    recipient = workflow.get("recipient", "University Office")
    email = workflow.get("email", "office@gouni.edu.ng")
    sender_name = collected.get("full_name", "Student")
    subject = _subject_from_collected(workflow, collected)

    lines = [
        "Step 3",
        f"Final summary for {workflow['label']}",
        "",
        "Email draft",
        f"To: {email}",
        f"Subject: {subject}",
        "",
        f"Dear {recipient},",
        "",
    ]

    purpose = str(collected.get("purpose", "")).strip()
    if purpose:
        lines.append(f"I am writing to request support regarding: {purpose}.")
    else:
        lines.append(f"I am writing to submit my {workflow['label'].lower()} request.")

    lines.extend(["", "Collected details:"])

    for field in workflow["fields"]:
        value = collected.get(field["key"], "Not provided")
        lines.append(f"{field['label']}: {value}")

    actions = _next_actions(workflow_key, workflow, collected)
    lines.extend(["", "Next actions:"])
    for index, action in enumerate(actions, start=1):
        lines.append(f"Action {index}: {action}")

    lines.extend(["", "Thank you.", f"{sender_name}"])

    return "\n".join(lines)


def _build_step2_output(workflow_key, workflow, collected):
    lines = [
        "Step 2",
        _step2_context(workflow_key, collected),
        workflow.get("step_2", {}).get("question", "Reply continue when you are ready for the final summary."),
    ]
    return "\n".join(lines)


def _build_output(workflow_key, workflow, collected):
    output_type = workflow["output_type"]
    if output_type == "email_draft":
        return _build_email_output(workflow_key, workflow, collected)
    return _build_summary_output(workflow_key, workflow, collected)


def _start_workflow(task_state, workflow_key):
    task_state["active_task"] = workflow_key
    task_state["current_step"] = "step_1"
    task_state["step_index"] = 1
    task_state["collected"] = {}
    task_state["completed_task"] = None
    task_state["last_output"] = None

    workflow = WORKFLOW_DEFINITIONS[workflow_key]
    first_field = workflow["fields"][0]
    return "\n".join(
        [
            workflow["intro"],
            "",
            "Step 1",
            workflow.get("step_1_context", ""),
            first_field["question"],
        ]
    )


def _complete_workflow(task_state, workflow_key, workflow, collected, conversation_state):
    output = _build_output(workflow_key, workflow, collected)
    output_type = workflow["output_type"]

    request_id = None
    try:
        request_id = save_task_request(
            task_key=workflow_key,
            task_label=workflow["label"],
            output_type=output_type,
            payload=collected,
        )
    except Exception:
        request_id = None

    task_state["active_task"] = None
    task_state["current_step"] = None
    task_state["step_index"] = 0
    task_state["completed_task"] = workflow_key
    task_state["last_output"] = output
    _save_task_state(task_state, conversation_state)

    if request_id is not None:
        output = f"{output}\n\nReference ID: {request_id}"

    return {
        "reply": output,
        "task_key": workflow_key,
        "task_label": workflow["label"],
        "output_type": output_type,
        "current_step": None,
        "completed": True,
        "request_id": request_id,
    }


def process_task_message(question, conversation_state, profile=None, session_id=None, history=None):
    task_state = _ensure_task_state(conversation_state)
    active_task = task_state.get("active_task")
    current_step = task_state.get("current_step")
    if profile is None:
        resolved_session_id = session_id or get_session_id()
        profile = get_user_profile(resolved_session_id)

    if active_task and _is_cancel_message(question):
        _reset_active_workflow(task_state)
        _save_task_state(task_state, conversation_state)
        return {
            "handled": True,
            "reply": f"Task cancelled. {_TASK_HINT}",
            "task_key": None,
            "task_label": None,
            "output_type": None,
            "current_step": None,
            "completed": False,
            "request_id": None,
        }

    detected_intent = _detect_intent(question)
    if detected_intent == "travel_permission":
        reply = handle_travel_permission(profile)
        return {
            "handled": True,
            "reply": reply,
            "task_key": "travel_permission",
            "task_label": "Travel Permission",
            "output_type": "request_summary",
            "current_step": None,
            "completed": True,
            "request_id": None,
        }

    vc_result = _process_vc_message(question, conversation_state)
    if vc_result.get("handled"):
        return vc_result

    task_state = _ensure_task_state(conversation_state)
    active_task = task_state.get("active_task")

    if not active_task:
        detected = detected_intent
        if not detected:
            return {"handled": False}

        reply = _start_workflow(task_state, detected)
        _save_task_state(task_state, conversation_state)
        workflow = WORKFLOW_DEFINITIONS[detected]
        return {
            "handled": True,
            "reply": reply,
            "task_key": detected,
            "task_label": workflow["label"],
            "output_type": workflow["output_type"],
            "current_step": task_state.get("current_step"),
            "completed": False,
            "request_id": None,
        }

    workflow = WORKFLOW_DEFINITIONS.get(active_task)
    if not workflow:
        _reset_active_workflow(task_state)
        _save_task_state(task_state, conversation_state)
        return {"handled": False}

    collected = dict(task_state.get("collected", {}))
    message = (question or "").strip()

    if current_step == "step_2":
        task_state["current_step"] = "step_3"
        task_state["step_index"] = 3
        _save_task_state(task_state, conversation_state)
        completed = _complete_workflow(task_state, active_task, workflow, collected, conversation_state)
        completed["handled"] = True
        completed["current_step"] = None
        return completed

    structured = _extract_structured_answers(message, workflow)
    if structured:
        collected.update(structured)
        captured_note = "Noted your provided details."
    else:
        next_field = _next_missing_field(workflow, collected)
        if next_field:
            collected[next_field["key"]] = message
            captured_note = f"Noted {next_field['label']}."
        else:
            captured_note = "Noted."

    task_state["collected"] = collected
    next_field = _next_missing_field(workflow, collected)

    if next_field is not None:
        task_state["current_step"] = "step_1"
        task_state["step_index"] = 1
        _save_task_state(task_state, conversation_state)
        reply = "\n".join(["Step 1", captured_note, next_field["question"]])
        return {
            "handled": True,
            "reply": reply,
            "task_key": active_task,
            "task_label": workflow["label"],
            "output_type": workflow["output_type"],
            "current_step": "step_1",
            "completed": False,
            "request_id": None,
        }

    task_state["current_step"] = "step_2"
    task_state["step_index"] = 2
    _save_task_state(task_state, conversation_state)
    reply = _build_step2_output(active_task, workflow, collected)
    return {
        "handled": True,
        "reply": reply,
        "task_key": active_task,
        "task_label": workflow["label"],
        "output_type": workflow["output_type"],
        "current_step": "step_2",
        "completed": False,
        "request_id": None,
    }
