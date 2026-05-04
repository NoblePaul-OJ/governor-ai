import re

# Supervised, rule-bound intent catalog (prototype phase).
INTENT_RULES = {
    "fees_payment": {
        "label": "Fees & Payment",
        "office": "Bursary Office",
        "keywords": ["fee", "fees", "payment", "invoice", "tuition", "bursary"],
        "response": "For fee/payment issues, visit the Bursary portal, generate your invoice, and confirm payment deadline.",
    },
    "course_registration": {
        "label": "Course Registration",
        "office": "Academic Affairs Office",
        "keywords": ["register", "registered", "registration", "course form", "add course", "drop course"],
        "response": "Course registration is handled on the student portal within the approved registration window.",
    },
    "results_records": {
        "label": "Results & Records",
        "office": "Exams and Records Office",
        "keywords": ["result", "grade", "transcript", "gpa", "record"],
        "response": "You can check results from the student portal results section. For missing results, contact Exams and Records.",
    },
    "admissions": {
        "label": "Admissions",
        "office": "Admissions Office",
        "keywords": ["admission", "admitted", "clearance", "acceptance", "screening"],
        "response": "Admission status and acceptance procedures are managed via the admissions portal and office.",
    },
    "hostel": {
        "label": "Hostel Allocation",
        "office": "Student Affairs Office",
        "keywords": ["hostel", "accommodation", "room", "bedspace"],
        "response": "Hostel requests are processed through the accommodation portal during the allocation period.",
    },
    "travel_permission": {
        "label": "Travel Permission",
        "office": "Student Affairs Office",
        "keywords": ["travel", "permission", "leave school", "travel approval"],
        "response": "If you need permission to travel, follow the Student Affairs approval process and submit a short request letter.",
    },
    "academic_schedule": {
        "label": "Academic Schedule",
        "office": "Academic Planning Unit",
        "keywords": ["calendar", "schedule", "semester", "lecture", "exam timetable", "resumption"],
        "response": "Academic calendar and timetable updates are released by Academic Planning and published on official channels.",
    },
    "department": {
        "label": "Departmental Inquiries",
        "office": "Department Office",
        "keywords": ["department", "hod", "advisor", "project supervisor"],
        "response": "For department-specific issues, contact your department office with your matric number and level.",
    },
    "examinations": {
        "label": "Examinations",
        "office": "Exams and Records Office",
        "keywords": ["exam", "examination", "test", "assessment", "timetable", "schedule"],
        "response": "Examination schedules and procedures are available on the student portal and Exams office.",
    },
    "student_services": {
        "label": "Student Services",
        "office": "Student Affairs Office",
        "keywords": ["counseling", "health", "library", "sports", "clubs", "orientation"],
        "response": "Student services including counseling, health, and extracurricular activities are coordinated by Student Affairs.",
    },
    "graduation": {
        "label": "Graduation",
        "office": "Academic Affairs Office",
        "keywords": ["graduation", "convocation", "certificate", "diploma", "gown"],
        "response": "Graduation requirements and convocation details are managed by Academic Affairs.",
    },
}

_VAGUE_FOLLOWUP_PHRASES = {
    "also",
    "and",
    "what about that",
    "what about it",
    "what about hostel",
    "what about mentor",
    "mentor",
    "another thing",
    "also hostel",
    "and hostel",
}


def _normalize(text):
    cleaned = re.sub(r"[^a-zA-Z0-9\s]", " ", (text or "").lower())
    return " ".join(cleaned.split())


def _normalize_history(history):
    normalized = []
    for item in history or []:
        if isinstance(item, dict):
            role = str(item.get("role") or "").strip().lower() or "user"
            content = str(item.get("content") or item.get("message") or "").strip()
        else:
            role = "user"
            content = str(item or "").strip()

        if content:
            normalized.append({"role": role, "content": content})
    return normalized


def _classify_from_text(question):
    normalized = _normalize(question)
    tokens = set(normalized.split())

    best = None
    best_score = 0.0

    for intent_key, payload in INTENT_RULES.items():
        keywords = set(payload["keywords"])
        if not keywords:
            continue

        overlap = len(tokens & keywords)
        score = overlap / len(keywords)

        if score > best_score:
            best_score = score
            best = (intent_key, payload)

    if best and best_score > 0:
        intent_key, payload = best
        return {
            "matched": True,
            "intent_key": intent_key,
            "intent_label": payload["label"],
            "office": payload["office"],
            "response": payload["response"],
            "confidence": round(best_score, 3),
        }

    return {
        "matched": False,
        "intent_key": None,
        "intent_label": None,
        "office": None,
        "response": (
            "That's an interesting one. Let me try to help.\n\n"
            "If this is related to Godfrey Okoye University, I can guide you properly. "
            "If not, I can still give general advice."
        ),
            "confidence": 0.0,
        }


def _is_vague_followup(question):
    normalized = _normalize(question)
    if not normalized:
        return False

    if normalized in _VAGUE_FOLLOWUP_PHRASES:
        return True

    tokens = normalized.split()
    if len(tokens) <= 2 and any(token in {"also", "and", "mentor", "hostel", "that", "it"} for token in tokens):
        return True

    return any(phrase in normalized for phrase in _VAGUE_FOLLOWUP_PHRASES)


def _last_relevant_intent_from_history(history):
    history_items = _normalize_history(history)
    if not history_items:
        return None

    user_messages = [item["content"] for item in history_items if item["role"] == "user" and item["content"]]
    for message in reversed(user_messages):
        candidate = _classify_from_text(message)
        if candidate.get("matched"):
            return candidate

    return None


def _last_intent_key_from_history(history):
    candidate = _last_relevant_intent_from_history(history)
    if not candidate:
        return None
    return candidate.get("intent_key")


def classify_intent(question, history=None):
    direct = _classify_from_text(question)
    if direct.get("matched"):
        direct["contextual"] = False
        direct["topic_shift"] = False
        previous_intent_key = _last_intent_key_from_history(history)
        if previous_intent_key and previous_intent_key != direct.get("intent_key"):
            direct["topic_shift"] = True
        return direct

    if not history or not _is_vague_followup(question):
        direct["contextual"] = False
        direct["topic_shift"] = False
        return direct

    contextual = _last_relevant_intent_from_history(history)
    if not contextual:
        direct["contextual"] = False
        direct["topic_shift"] = False
        return direct

    contextual["contextual"] = True
    contextual["topic_shift"] = False
    contextual["followup_from_history"] = True
    contextual["confidence"] = max(0.25, contextual.get("confidence", 0.0) * 0.75)
    return contextual


def get_rules():
    """Return the current intent rules dictionary."""

    return INTENT_RULES


def update_rules(new_rules):
    """Replace the module-level INTENT_RULES with ``new_rules``.

    This is a very simple in-memory adjustment used by the admin interface in the
    prototype.  ``classify_intent`` reads from the module variable directly so
    updates take effect immediately for new queries.
    """

    global INTENT_RULES
    INTENT_RULES = new_rules
    return INTENT_RULES
