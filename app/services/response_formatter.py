import re


_FALLBACK_RESPONSE = (
    "I am not fully sure yet.\n\n"
    "If this is related to Godfrey Okoye University, I can help more precisely. "
    "If not, I can still give general guidance."
)

_GREETING_PHRASES = {
    "hi",
    "hello",
    "hey",
    "good morning",
    "good afternoon",
    "good evening",
    "thanks",
    "thank you",
}

_CASUAL_MARKERS = {
    "lol",
    "lmao",
    "bro",
    "boss",
    "fam",
    "pls",
    "please",
    "okay",
    "ok",
    "cool",
    "nice",
}

_SERIOUS_MARKERS = {
    "urgent",
    "asap",
    "important",
    "deadline",
    "exam",
    "registration",
    "issue",
    "problem",
    "need help",
    "need guidance",
}

_STRESSED_MARKERS = {
    "confused",
    "not sure",
    "dont understand",
    "don't understand",
    "no idea",
    "stuck",
    "help me",
    "what do i do",
    "what should i do",
    "unclear",
    "dont know",
    "don't know",
    "worried",
}

_FILLER_PREFIXES = [
    r"^here(?:'s| is) a quick answer[:\-\s]*",
    r"^here(?:'s| is) what you need to do[:\-\s]*",
    r"^here(?:'s| is) the answer[:\-\s]*",
    r"^here(?:'s| is) the gist[:\-\s]*",
    r"^sure[, ]+here(?:'s| is)[:\-\s]*",
    r"^alright[, ]+here(?:'s| is)[:\-\s]*",
    r"^i(?:'m| am) not sure[, ]+but[:\-\s]*",
    r"^i think[, ]*",
    r"^big boy[, ]*",
    r"^i like that energy[.! ]*",
    r"^go and eat o[.! ]*",
]

_GUIDANCE_LINES = {
    "casual": "If you want, I can keep this brief.",
    "serious": "If you want, I can expand on any part.",
    "stressed": "If it helps, I can break it down gently.",
    "neutral": "If anything is unclear, I can clarify it.",
}

_INCOMPLETE_ENDINGS = {
    "a",
    "an",
    "the",
    "to",
    "for",
    "of",
    "with",
    "about",
    "in",
    "on",
    "at",
    "from",
    "and",
    "or",
    "but",
    "because",
    "if",
    "then",
    "need",
    "want",
    "tell",
    "show",
    "give",
    "send",
    "share",
    "ask",
}

_INCOMPLETE_PHRASES = {
    "i need",
    "i want",
    "help me",
    "tell me",
    "show me",
    "can you",
    "could you",
    "what about",
    "how about",
    "i am",
    "im",
    "i m",
}


def _normalize(text):
    cleaned = re.sub(r"[^a-zA-Z0-9\s]", " ", (text or "").lower())
    return " ".join(cleaned.split())


def detect_user_tone(user_input):
    normalized = _normalize(user_input)
    if not normalized:
        return "neutral"

    if normalized in _GREETING_PHRASES:
        return "neutral"

    if any(_normalize(marker) in normalized for marker in _STRESSED_MARKERS):
        return "stressed"

    if any(_normalize(marker) in normalized for marker in _SERIOUS_MARKERS):
        return "serious"

    if any(_normalize(marker) in normalized for marker in _CASUAL_MARKERS):
        return "casual"

    if len(normalized.split()) <= 3 and "?" not in str(user_input):
        return "serious"

    return "neutral"


def detect_incomplete_message(user_input):
    text = str(user_input or "").strip()
    if not text:
        return False

    normalized = _normalize(text)
    if not normalized or normalized in _GREETING_PHRASES:
        return False

    lowered = text.lower().strip()
    if lowered.endswith(("...", "…")):
        return True

    if normalized in _INCOMPLETE_PHRASES:
        return True

    tokens = normalized.split()
    if len(tokens) == 1:
        return tokens[0] in _INCOMPLETE_ENDINGS

    if tokens[-1] in _INCOMPLETE_ENDINGS:
        return True

    if re.search(
        r"\b(?:the|a|an|to|for|of|with|about|in|on|at|from|and|or|but|because|if|then|need|want|tell|show|give|send|share|ask)$",
        lowered,
    ):
        return True

    return False


def _needs_guidance(user_input):
    if not user_input:
        return False

    normalized = _normalize(user_input)
    if normalized in _GREETING_PHRASES:
        return False

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
    if any(_normalize(phrase) in normalized for phrase in confusion_phrases):
        return True

    return str(user_input).count("?") >= 2 or any(_normalize(phrase) in normalized for phrase in _STRESSED_MARKERS)


def _clean_opening(text):
    cleaned = (text or "").strip()
    if not cleaned:
        return cleaned

    changed = True
    while changed:
        changed = False
        for pattern in _FILLER_PREFIXES:
            updated = re.sub(pattern, "", cleaned, flags=re.IGNORECASE)
            if updated != cleaned:
                cleaned = updated.lstrip(" \t-:").strip()
                changed = True

    cleaned = re.sub(r"^[\-\:\,\s]+", "", cleaned)
    cleaned = re.sub(r"[!?]{2,}", ".", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


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


def polish_response_text(text):
    response = str(text or "").replace("\r\n", "\n").strip()
    if not response:
        return ""

    response = re.sub(r"\n{3,}", "\n\n", response)
    blocks = []
    seen = set()

    for block in re.split(r"\n\s*\n", response):
        cleaned_block = block.strip()
        if not cleaned_block:
            continue

        cleaned_block = "\n".join(line.rstrip() for line in cleaned_block.splitlines()).strip()
        normalized = _normalize(cleaned_block)
        if normalized and normalized in seen:
            continue
        if normalized:
            seen.add(normalized)
        blocks.append(cleaned_block)

    return "\n\n".join(blocks).strip()


def _guidance_for_tone(tone):
    return _GUIDANCE_LINES.get(tone, _GUIDANCE_LINES["neutral"])


def build_incomplete_message_reply():
    return "Looks like your message got cut off — what do you need?"


def format_response(answer, user_input=None, category=None, profile=None):
    tone = detect_user_tone(user_input)
    base = _humanize_subject(answer)
    base = _clean_opening(base)
    base = base.strip()
    if not base:
        base = _FALLBACK_RESPONSE

    if _should_inject_memory(user_input, profile, category=category):
        base = inject_confident_context(base, profile)

    category_key = str(category or "").strip().lower()
    if category_key in {"conversational", "contact_directory", "memory", "conversation_clarity", "task_workflow"}:
        return polish_response_text(_clean_opening(base))

    if base.startswith("I\u2019m Governor AI for Godfrey Okoye University."):
        return polish_response_text(base)

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
        guidance = _guidance_for_tone(tone)
        formatted = f"{formatted}\n\n{guidance}" if formatted else guidance

    response = trim_response(_clean_opening(formatted))
    return polish_response_text(response)
