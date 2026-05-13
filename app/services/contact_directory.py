import re

from app.services.directory import get_unit_contacts, load_directory


CONTACT_INTENT_PHRASES = (
    "how do i contact",
    "how can i contact",
    "contact details",
    "email for",
    "phone for",
    "phone number for",
    "reach out to",
    "where is the",
    "where is",
)

OFFICE_KEYWORDS = {
    "Admissions Office": ["admission", "admissions", "screening", "clearance"],
    "Bursary Unit": ["bursary", "fees", "fee", "payment", "invoice", "tuition", "receipt"],
    "Student Affairs Office": ["student affairs", "hostel", "accommodation", "welfare"],
    "Exams and Records Office": ["records", "result", "results", "transcript", "grade", "gpa"],
    "Academic Affairs Office": ["academic affairs", "course registration", "registration", "graduation"],
    "ICT Support": ["ict", "portal", "password", "login", "technical", "support", "result", "registration"],
    "Vice Chancellor's Office": ["vice chancellor", "vc", "chancellor"],
    "Registrar's Office": ["registrar", "registry", "documentation", "policy"],
}

_UNIT_TO_SECTION = {
    "ict": "ict",
    "ict support": "ict",
    "ict department": "ict",
    "bursary": "bursary",
    "bursary unit": "bursary",
    "bursary office": "bursary",
    "admissions": "admissions",
    "admissions office": "admissions",
    "student affairs": "student_affairs",
    "vc": "vc",
    "vice chancellor": "vc",
    "registrar": "registrar",
    "academic affairs": "academic_affairs",
}


def _normalize(text):
    cleaned = re.sub(r"[^a-zA-Z0-9\s]", " ", (text or "").lower())
    return " ".join(cleaned.split())


def _is_contact_query(question):
    normalized = _normalize(question)
    if not normalized:
        return False
    if "contact" in normalized and "how" in normalized:
        return True
    return any(phrase in normalized for phrase in CONTACT_INTENT_PHRASES)


def _office_match_score(question, entry):
    normalized = _normalize(question)
    office_name = entry.get("unit_name") or entry.get("office_name") or ""
    score = 0

    office_tokens = [tok for tok in _normalize(office_name).split() if tok not in {"office", "unit", "and", "s"}]
    score += sum(1 for tok in office_tokens if tok and tok in normalized)

    keywords = OFFICE_KEYWORDS.get(office_name, [])
    score += sum(2 for kw in keywords if _normalize(kw) in normalized)

    common_issues = entry.get("common_issues") or entry.get("common_issue_types") or []
    if isinstance(common_issues, list):
        score += sum(1 for issue in common_issues if _normalize(issue) in normalized)

    handles = entry.get("handles") or []
    if isinstance(handles, list):
        score += sum(1 for issue in handles if _normalize(issue) in normalized)

    return score


def _natural_join(items):
    cleaned = [str(item).strip() for item in items if str(item).strip()]
    if not cleaned:
        return ""
    if len(cleaned) == 1:
        return cleaned[0]
    if len(cleaned) == 2:
        return f"{cleaned[0]} and {cleaned[1]}"
    return f"{', '.join(cleaned[:-1])}, and {cleaned[-1]}"


def _format_contact(entry):
    unit_name = entry.get("unit_name") or entry.get("office_name") or "University Office"
    return f"{unit_name} is the right office for that."


def _available_offices(entries):
    names = [e.get("unit_name") or e.get("office_name") for e in entries if e.get("unit_name") or e.get("office_name")]
    return _natural_join(names)


def _iter_directory_entries():
    directory = load_directory()
    if not isinstance(directory, dict):
        return []

    entries = []
    for key, value in directory.items():
        if key == "hostels" and isinstance(value, dict):
            for hostel_key, hostel_value in value.items():
                if not isinstance(hostel_value, dict):
                    continue
                entries.append(
                    {
                        "unit_key": hostel_key,
                        "unit_name": hostel_value.get("office_name") or hostel_key.replace("_", " ").title(),
                        "office_name": hostel_value.get("office_name") or hostel_key.replace("_", " ").title(),
                        "description": hostel_value.get("description") or hostel_value.get("note"),
                        "phone": hostel_value.get("phone"),
                        "whatsapp": hostel_value.get("whatsapp"),
                        "email": hostel_value.get("email"),
                        "office_location": hostel_value.get("office") or hostel_value.get("location"),
                        "office_hours": hostel_value.get("office_hours"),
                        "preferred_contact_method": hostel_value.get("preferred_contact_method"),
                        "common_issues": hostel_value.get("common_issues") or hostel_value.get("common_issue_types") or [],
                    }
                )
            continue

        section_key = _UNIT_TO_SECTION.get(key, key)
        contact = get_unit_contacts(section_key)
        if contact:
            entries.append(contact)

    return entries


def load_contact_directory():
    return _iter_directory_entries()


def resolve_contact_query(question):
    entries = load_contact_directory()
    if not entries:
        return {"handled": False}

    if not _is_contact_query(question):
        return {"handled": False}

    scored = []
    for entry in entries:
        score = _office_match_score(question, entry)
        if score > 0:
            scored.append((score, entry))

    if scored:
        scored.sort(key=lambda item: item[0], reverse=True)
        best_entry = scored[0][1]
        return {
            "handled": True,
            "matched": True,
            "entry": best_entry,
            "contact": best_entry,
            "reply": _format_contact(best_entry),
        }

    offices = _available_offices(entries)
    return {
        "handled": True,
        "matched": False,
        "entry": None,
        "reply": (
            "I can help with the official contact details, but I need the office name first. "
            f"I can already point you to {offices}."
        ),
    }
