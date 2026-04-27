import random
import re


_STEP_INTROS = [
    "Here's what you need to do:",
    "You can follow these steps:",
    "Try this process:",
]

_BULLET_INTROS = [
    "Here are the key points:",
    "Quick breakdown:",
    "Key items to note:",
]

_PARA_INTROS = [
    "Here's a quick answer:",
    "Sure - here's the gist:",
    "Got it. Here's the short answer:",
]

_GUIDANCE_LINES = [
    "If you can, share your level/department and the exact issue so I can be more specific.",
    "If anything is unclear, tell me your level and the exact situation, and I'll guide you more precisely.",
    "If you want, add your level/department and the specific issue so I can narrow it down.",
]

_FALLBACK_RESPONSE = (
    "That's an interesting one. Let me try to help.\n\n"
    "If this is related to Godfrey Okoye University, I can guide you properly. "
    "If not, I can still give general advice."
)


def _normalize(text):
    cleaned = re.sub(r"[^a-zA-Z0-9\\s]", " ", (text or "").lower())
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

    if prefix:
        prefix = prefix.rstrip(",")
        intro = f"Here's what you need to do {prefix.lower()}:"
    else:
        intro = random.choice(_STEP_INTROS)

    return intro, items


def _extract_bullets(answer):
    match = re.search(r"\bincluding\b", answer, flags=re.IGNORECASE)
    if not match:
        return None

    prefix = answer[: match.start()].strip().rstrip(",")
    rest = answer[match.end() :].strip().strip(".")
    items = _split_list(rest)
    if len(items) < 2:
        return None

    if prefix:
        intro = f"{prefix}:"
    else:
        intro = random.choice(_BULLET_INTROS)

    return intro, items


def format_response(answer, user_input=None, category=None):
    base = _humanize_subject(answer)
    base = base.strip()
    if not base:
        base = _FALLBACK_RESPONSE

    if category and str(category).lower() == "conversational":
        return base
    if base.startswith("I\u2019m Governor AI for Godfrey Okoye University."):
        return base

    steps = _extract_steps(base)
    if steps:
        intro, items = steps
        formatted = intro + "\n" + "\n".join(f"- {item}" for item in items)
    else:
        bullets = _extract_bullets(base)
        if bullets:
            intro, items = bullets
            formatted = intro + "\n" + "\n".join(f"- {item}" for item in items)
        else:
            intro = random.choice(_PARA_INTROS)
            formatted = f"{intro} {base}"

    if _needs_guidance(user_input):
        formatted = formatted + "\n" + random.choice(_GUIDANCE_LINES)

    return formatted
