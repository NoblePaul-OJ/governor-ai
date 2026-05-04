import re


_SUMMARY_PHRASES = (
    "what do you know about me",
    "tell me what you know about me",
    "what have you saved about me",
    "remember about me",
    "who am i to you",
    "who am i",
)

_CLARIFY_PHRASES = {
    "name": ("change my name", "update my name", "set my name"),
    "department": ("change my department", "update my department", "set my department"),
    "level": ("change my level", "update my level", "set my level"),
}


def _normalize_text(text):
    cleaned = re.sub(r"[^a-zA-Z0-9\s]", " ", (text or "").lower())
    return " ".join(cleaned.split())


def _clean_value(field, value):
    text = str(value or "").strip()
    text = re.sub(r"^[\s,;:.-]+", "", text)
    text = text.strip(" .")

    if field == "level":
        lowered = text.lower()
        if "final year" in lowered or "last year" in lowered:
            return "400"

        match = re.search(r"(?P<value>\d{3})\s*(?:level|l)?$", text, flags=re.IGNORECASE)
        if match:
            return match.group("value")

        match = re.search(r"(?P<value>\d{2,3})", text)
        if match:
            return match.group("value")

    if field in {"name", "department"}:
        text = " ".join(part.capitalize() for part in text.split())

    return text


def detect_user_memory_message(message):
    text = str(message or "").strip()
    if not text:
        return None

    normalized = _normalize_text(text)
    if not normalized:
        return None

    if any(phrase in normalized for phrase in _SUMMARY_PHRASES):
        return {"action": "recall", "field": "summary"}

    for field, phrases in _CLARIFY_PHRASES.items():
        if normalized in phrases:
            return {
                "action": "clarify",
                "field": field,
                "prompt": "What would you like me to change it to?",
            }

    data = {}

    level_patterns = [
        r"\b(?:i am now|i'm now|i m now|im now|i am|i'm|i m|im)\s+(?P<value>\d{3}\s*(?:level|l)?)\b",
        r"\b(?P<value>\d{3})\s*level\b",
        r"\b(?P<value>\d{3})\s*l\b",
        r"\b(?P<value>final year|last year)\b",
        r"\b(?:i am now|i'm now|i m now|im now)\s+(?P<value>final year|last year)\b",
    ]
    for pattern in level_patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            value = _clean_value("level", match.group("value"))
            if value:
                data["level"] = value
                break

    department_patterns = [
        r"\b(?:i am in|i'm in|i m in|im in)\s+(?P<value>.+?)(?:\s+department)?$",
        r"\b(?:i study|i'm studying|i m studying|im studying)\s+(?P<value>.+?)$",
        r"\b(?:i changed department to|change my department to|update my department to|set my department to)\s+(?P<value>.+?)$",
        r"\b(?:my|the)\s+department\s+is\s+(?P<value>.+?)$",
    ]
    for pattern in department_patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if not match:
            continue

        value = _clean_value("department", match.group("value"))
        lowered = _normalize_text(value)
        if not value or "level" in lowered or lowered in {"final year", "last year"}:
            continue

        data["department"] = value
        break

    name_patterns = [
        r"\b(?:my name is|call me)\s+(?P<value>.+?)$",
        r"\b(?:change my name to|update my name to|set my name to)\s+(?P<value>.+?)$",
        r"\b(?:i am|i'm|i m|im)\s+(?P<value>[A-Za-z][A-Za-z\s'.-]{1,50})$",
    ]
    for pattern in name_patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if not match:
            continue

        value = _clean_value("name", match.group("value"))
        lowered = _normalize_text(value)
        if not value or lowered in {"in", "studying", "study"} or any(
            term in lowered for term in {"level", "department", "student"}
        ):
            continue

        data["name"] = value
        break

    note_patterns = [
        r"\b(?:i prefer)\s+(?P<value>.+?)$",
        r"\b(?:i stay in|i live in|i stay at|i reside in)\s+(?P<value>.+?)$",
    ]
    for pattern in note_patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if not match:
            continue

        value = str(match.group("value") or "").strip().strip(" .")
        if value:
            data.setdefault("notes", []).append(value)

    if data:
        return {"action": "update", "data": data}

    return None

