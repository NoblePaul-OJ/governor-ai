import json
import os
import re
from copy import deepcopy


BASE_DIR = os.path.dirname(os.path.dirname(__file__))
DATA_PATH = os.path.join(BASE_DIR, "data", "contact_directory.json")

_PLACEHOLDERS = {
    "",
    "n/a",
    "na",
    "none",
    "not available",
    "not available yet",
    "unavailable",
    "unavailable yet",
    "unknown",
}

_UNIT_ALIASES = {
    "ict": "ict",
    "ict support": "ict",
    "ict department": "ict",
    "information and communication technology": "ict",
    "bursary": "bursary",
    "bursary unit": "bursary",
    "bursary office": "bursary",
    "admissions": "admissions",
    "admissions office": "admissions",
    "admission office": "admissions",
    "student affairs": "student_affairs",
    "student affairs office": "student_affairs",
    "vc": "vc",
    "vice chancellor": "vc",
    "vice chancellor office": "vc",
    "registrar": "registrar",
    "registrar office": "registrar",
    "academic affairs": "academic_affairs",
    "academic affairs office": "academic_affairs",
    "exams and records": "records",
    "exams and records office": "records",
}

_UNIT_NAMES = {
    "vc": "Vice Chancellor's Office",
    "student_affairs": "Student Affairs Office",
    "ict": "ICT Support",
    "bursary": "Bursary Unit",
    "admissions": "Admissions Office",
    "registrar": "Registrar's Office",
    "academic_affairs": "Academic Affairs Office",
    "records": "Exams and Records Office",
}

def _normalize(text):
    cleaned = re.sub(r"[^a-zA-Z0-9\s]", " ", (text or "").lower())
    return " ".join(cleaned.split())


def _clean_value(value):
    text = str(value or "").strip()
    if not text:
        return None
    if _normalize(text) in _PLACEHOLDERS:
        return None
    return text


def _clean_list(value):
    if not isinstance(value, list):
        value = [value] if value not in (None, "") else []

    cleaned = []
    for item in value:
        text = _clean_value(item)
        if text and text not in cleaned:
            cleaned.append(text)
    return cleaned


def _first_value(values):
    return values[0] if values else None


def _normalize_contact_values(raw, list_key, scalar_key):
    values = _clean_list(raw.get(list_key))
    scalar_value = _clean_value(raw.get(scalar_key))
    if scalar_value and scalar_value not in values:
        values.insert(0, scalar_value)
    return values


def _section_label(section_key):
    return _UNIT_NAMES.get(section_key, section_key.replace("_", " ").title())


def _resolve_section_key(unit_name):
    normalized = _normalize(unit_name)
    if not normalized:
        return None

    if normalized in _UNIT_ALIASES:
        return _UNIT_ALIASES[normalized]

    for key, label in _UNIT_NAMES.items():
        if normalized == _normalize(key) or normalized == _normalize(label):
            return key

    return None


def _normalize_contact(section_key, raw):
    raw = raw if isinstance(raw, dict) else {}
    unit_name = _clean_value(raw.get("unit_name") or raw.get("office_name") or _section_label(section_key))
    office_location = _clean_value(raw.get("office_location") or raw.get("office") or raw.get("location"))
    phones = _normalize_contact_values(raw, "phones", "phone")
    emails = _normalize_contact_values(raw, "emails", "email")
    handles = _clean_list(raw.get("handles"))
    common_issues = _clean_list(raw.get("common_issues") or raw.get("common_issue_types"))
    combined_issues = []
    for item in common_issues + handles:
        if item and item not in combined_issues:
            combined_issues.append(item)

    return {
        "unit_key": section_key,
        "unit_name": unit_name,
        "office_name": unit_name,
        "phones": phones,
        "phone": _first_value(phones),
        "whatsapp": _clean_value(raw.get("whatsapp")),
        "emails": emails,
        "email": _first_value(emails),
        "handles": handles,
        "office_location": office_location,
        "office": office_location,
        "location": office_location,
        "office_hours": _clean_value(raw.get("office_hours")),
        "preferred_contact_method": _clean_value(raw.get("preferred_contact_method")),
        "common_issues": combined_issues,
        "common_issue_types": combined_issues,
        "description": _clean_value(raw.get("description")),
        "note": _clean_value(raw.get("note")),
    }


def load_directory():
    try:
        with open(DATA_PATH, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except FileNotFoundError:
        data = {}
    except (OSError, json.JSONDecodeError):
        data = {}

    return deepcopy(data if isinstance(data, dict) else {})


def get_unit_contacts(unit_name):
    directory = load_directory()
    section_key = _resolve_section_key(unit_name)
    if not section_key:
        return {}

    contact = _normalize_contact(section_key, directory.get(section_key, {}))
    if not contact.get("unit_name"):
        return {}
    return contact


def get_contact(unit_name):
    return get_unit_contacts(unit_name)


def get_vc_contact():
    return get_contact("vc")


def get_student_affairs():
    return get_contact("student_affairs")


def get_ict():
    return get_contact("ict")


def get_bursary():
    return get_contact("bursary")


def get_admissions():
    return get_contact("admissions")


def get_hostel(name=None):
    directory = load_directory()
    hostels = directory.get("hostels", {})
    if not isinstance(hostels, dict):
        return {} if name else {}

    if not name:
        return deepcopy(hostels)

    return deepcopy(hostels.get(name.lower(), {}))
