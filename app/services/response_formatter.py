import re


_GUIDANCE_LINES = [
    "If you want, send the exact issue and I can narrow it down.",
]

_FALLBACK_RESPONSE = (
    "I'm not fully sure yet.\n\n"
    "If this is related to Godfrey Okoye University, I can help more precisely. "
    "If not, I can still give general advice."
)


def _normalize(text):
    cleaned = re.sub(r"[^a-zA-Z0-9\s]", " ", (text or "").lower())
    return " ".join(cleaned.split())


def _needs_guidance(user_input):
    if not user_input:
        return False
    normalized = _normalize(user_input)
    tokens = normalized.split()
    if len(tokens) <= 3:
        return True
    confusion_phrases = [
        "not sure",
        "confused",
        "dont understand",
        "don't understand",
        "no idea",
        "help",
        "what do i do",
        "what should i do",
        "not clear",
        "unclear",
    ]
    return any(phrase in normalized for phrase in confusion_phrases) or user_input.count("?") >= 2


def _humanize_subject(answer):
    text = (answer or "").strip()
    if not text:
        return text

    replacements = [
        (r"^Students have the right to ", "You have the right to "),
        (r"^Students have rights including ", "You have rights, including "),
        (r"^Students have rights ", "You have rights "),
        (r"^Students have ", "You have "),
        (r"^All students have ", "You have "),
        (r"^Students can ", "You can "),
        (r"^Students must ", "You must "),
        (r"^Students are required to ", "You are required to "),
        (r"^Students are ", "You are "),
        (r"^After admission, students must ", "After admission, you must "),
        (r"^To change course, a student must ", "To change course, you must "),
    ]

    subject_changed = False
    for pattern, replacement in replacements:
        if re.match(pattern, text, flags=re.IGNORECASE):
            text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
            subject_changed = True
            break

    if subject_changed:
        text = re.sub(r"\btheir\b", "your", text, flags=re.IGNORECASE)

    return text


def _should_inject_memory(user_input, profile, category=None):
    if not profile:
        return False

    return False


def inject_confident_context(response, profile):
    return response


def _split_list(text):
    parts = [p.strip() for p in re.split(r",|;", text) if p.strip()]
    if len(parts) >= 2:
        last = parts[-1]
        if " and " in last:
            tail = [p.strip() for p in last.split(" and ") if p.strip()]
            parts = parts[:-1] + tail
    return parts


def _extract_steps(answer):
    lower = answer.lower()
    trigger = None
    for token in [" must ", " should ", " required to "]:
        if token in lower:
            trigger = token.strip()
            break

    if not trigger:
        return None

    idx = lower.find(trigger)
    prefix = answer[:idx].strip()
    rest = answer[idx + len(trigger) :].strip()
    if rest.lower().startswith("to "):
        rest = rest[3:].strip()

    rest = rest.rstrip(".")
    items = _split_list(rest)
    if len(items) < 2:
        return None

    return prefix, items


def _extract_bullets(answer):
    match = re.search(r"\bincluding\b", answer, flags=re.IGNORECASE)
    if not match:
        return None

    prefix = answer[: match.start()].strip().rstrip(",")
    rest = answer[match.end() :].strip().strip(".")
    items = _split_list(rest)
    if len(items) < 2:
        return None

    return prefix, items


def trim_response(response):
    # Remove excessive questions
    lines = str(response or "").split("\n")

    cleaned = []
    question_count = 0

    for line in lines:
        if "?" in line:
            question_count += 1
            if question_count > 2:
                continue
        cleaned.append(line)

    return "\n".join(cleaned)


def format_response(answer, user_input=None, category=None, profile=None):
    base = _humanize_subject(answer)
    base = base.strip()
    if not base:
        base = _FALLBACK_RESPONSE

    if _should_inject_memory(user_input, profile, category=category):
        base = inject_confident_context(base, profile)

    if category and str(category).lower() == "conversational":
        return trim_response(base)
    if base.startswith("I\u2019m Governor AI for Godfrey Okoye University."):
        return trim_response(base)

    steps = _extract_steps(base)
    if steps:
        prefix, items = steps
        lines = []
        if prefix:
            lines.append(prefix.rstrip(" ,:"))
            lines.append("")
        lines.extend(f"{index}. {item}" for index, item in enumerate(items, start=1))
        formatted = "\n".join(lines)
    else:
        bullets = _extract_bullets(base)
        if bullets:
            prefix, items = bullets
            lines = []
            if prefix:
                lines.append(prefix.rstrip(" ,:"))
                lines.append("")
            lines.extend(f"{index}. {item}" for index, item in enumerate(items, start=1))
            formatted = "\n".join(lines)
        else:
            formatted = base

    if _needs_guidance(user_input):
        guidance = _GUIDANCE_LINES[0]
        formatted = f"{formatted}\n\n{guidance}" if formatted else guidance

    response = trim_response(formatted)
    return response


