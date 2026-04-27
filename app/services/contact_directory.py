import json
import re
from pathlib import Path


DIRECTORY_PATH = Path(__file__).resolve().parents[2] / "contactDirectory.json"
_DIRECTORY_CACHE = None

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
    "Bursary Office": ["bursary", "fees", "fee", "payment", "invoice", "tuition"],
    "Student Affairs Office": ["student affairs", "hostel", "accommodation", "welfare"],
    "Exams and Records Office": ["records", "result", "results", "transcript", "grade", "gpa"],
    "Academic Affairs Office": ["academic affairs", "course registration", "registration", "graduation"],
    "ICT Support Unit": ["ict", "portal", "password", "login", "technical", "support"],
    "Vice Chancellor's Office": ["vice chancellor", "vc", "chancellor"],
    "Registrar's Office": ["registrar", "registry", "documentation", "policy"],
}


def _normalize(text):
    cleaned = re.sub(r"[^a-zA-Z0-9\s]", " ", (text or "").lower())
    return " ".join(cleaned.split())


def load_contact_directory():
    global _DIRECTORY_CACHE
    if _DIRECTORY_CACHE is not None:
        return _DIRECTORY_CACHE

    if not DIRECTORY_PATH.exists():
        _DIRECTORY_CACHE = []
        return _DIRECTORY_CACHE

    with DIRECTORY_PATH.open("r", encoding="utf-8-sig") as handle:
        data = json.load(handle)

    cleaned = []
    for row in data:
        if not isinstance(row, dict):
            continue
        cleaned.append(
            {
                "office_name": str(row.get("office_name", "")).strip(),
                "description": str(row.get("description", "")).strip(),
                "email": str(row.get("email", "")).strip(),
                "phone": str(row.get("phone", "")).strip(),
                "location": str(row.get("location", "")).strip(),
            }
        )

    _DIRECTORY_CACHE = [r for r in cleaned if r["office_name"]]
    return _DIRECTORY_CACHE


def _is_contact_query(question):
    normalized = _normalize(question)
    if not normalized:
        return False
    if "contact" in normalized and "how" in normalized:
        return True
    return any(phrase in normalized for phrase in CONTACT_INTENT_PHRASES)


def _office_match_score(question, entry):
    normalized = _normalize(question)
    office_name = entry["office_name"]
    score = 0

    office_tokens = [tok for tok in _normalize(office_name).split() if tok not in {"office", "unit", "and", "s"}]
    score += sum(1 for tok in office_tokens if tok and tok in normalized)

    keywords = OFFICE_KEYWORDS.get(office_name, [])
    score += sum(2 for kw in keywords if _normalize(kw) in normalized)

    return score


def _format_contact(entry):
    return (
        f"Contact Details: {entry['office_name']}\n"
        f"Description: {entry['description']}\n"
        f"Email: {entry['email']}\n"
        f"Phone: {entry['phone']}\n"
        f"Location: {entry['location']}"
    )


def _available_offices(entries):
    names = [e["office_name"] for e in entries if e.get("office_name")]
    return ", ".join(names)


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
            "reply": _format_contact(best_entry),
        }

    offices = _available_offices(entries)
    return {
        "handled": True,
        "matched": False,
        "entry": None,
        "reply": (
            "I can provide official contact details, but I need the office name.\n"
            f"Available offices: {offices}"
        ),
    }
