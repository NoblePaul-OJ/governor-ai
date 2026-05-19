import re
from app.services.personality import (
    EMOTIONAL_STATES,
    EMOJI_USAGE,
    get_founder_context,
    get_emoji_for_state,
    get_guidance_for_state,
    get_response_length_hint,
    should_use_emoji,
    should_mention_founder,
)


_FALLBACK_RESPONSE = (
    "The current university information available to me does not include that detail yet."
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

_FRUSTRATED_MARKERS = {
    "frustrated",
    "annoyed",
    "fed up",
    "tired of",
    "ridiculous",
    "this is ridiculous",
    "why is this",
    "can't do",
    "impossible",
    "not working",
    "keeps failing",
    "wasting my time",
    "i am tired of this",
    "i'm tired of this",
}

_TIRED_MARKERS = {
    "tired",
    "exhausted",
    "drained",
    "worn out",
    "long day",
    "i am weak",
    "i'm weak",
}

_EXCITED_MARKERS = {
    "awesome",
    "amazing",
    "fantastic",
    "great",
    "love it",
    "can't wait",
    "eager",
    "hungry for",
    "excited",
}

_HUMOR_MARKERS = {
    "haha",
    "funny",
    "joke",
    "joking",
    "hungry for knowledge",
    "dangerous level of motivation",
}

_SARCASM_MARKERS = {
    "yeah right",
    "sure",
    "of course",
    "obviously",
    "naturally",
    "wow great",
    "just perfect",
}

_STRESS_MARKERS = {
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
    "anxious",
    "panic",
    "lost",
    "overwhelmed",
    "stress",
    "stressing",
    "stressed",
}

_STRESSED_MARKERS = _STRESS_MARKERS

_FILLER_PREFIXES = [
    r"^here(?:'s| is) a quick answer[:\-\s]*",
    r"^here(?:'s| is) what you need to do[:\-\s]*",
    r"^here(?:'s| is) the answer[:\-\s]*",
    r"^here(?:'s| is) the gist[:\-\s]*",
    r"^sure[, ]+here(?:'s| is)[:\-\s]*",
    r"^alright[, ]+here(?:'s| is)[:\-\s]*",
    r"^i(?:'m| am) not sure[, ]+but[:\-\s]*",
    r"^i understand[,.\s]*",
    r"^i can help you with that[,.\s]*",
    r"^to guide you correctly[,.\s]*",
    r"^please provide[,.\s]*",
    r"^i apologize[,.\s]*",
    r"^to avoid giving incorrect details[,.\s]*",
    r"^i don't want to guess(?: and misstate)?[,.\s]*",
    r"^i currently do not have(?: verified| authoritative)?[,.\s]*",
    r"^i think[, ]*",
    r"^big boy[, ]*",
    r"^i like that energy[.! ]*",
    r"^go and eat o[.! ]*",
]

_GUIDANCE_LINES = {
    "casual": "",
    "serious": "",
    "stressed": "Take it one step at a time.",
    "frustrated": "This is solvable; let me break it down.",
    "tired": "Rest a little if you can; then we can handle one thing at a time.",
    "neutral": "",
}

_INSTITUTIONAL_TERMS = {
    "registration",
    "register",
    "fees",
    "fee",
    "hostel",
    "admission",
    "admissions",
    "portal",
    "result",
    "transcript",
    "bursary",
    "ict",
    "department",
    "faculty",
    "course",
    "clearance",
    "matric",
    "exam",
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

_AMBIGUOUS_CUTOFF_PHRASES = {
    "and",
    "because",
    "but",
    "wait",
    "so",
    "then",
    "i need",
    "help me",
    "help me with",
}

_QUESTION_STARTERS = (
    "what ",
    "who ",
    "where ",
    "when ",
    "why ",
    "how ",
    "which ",
    "is ",
    "are ",
    "do ",
    "does ",
    "can ",
    "could ",
    "should ",
    "would ",
    "may ",
    "will ",
)


def _normalize(text):
    cleaned = re.sub(r"[^a-zA-Z0-9\s]", " ", (text or "").lower())
    return " ".join(cleaned.split())


def normalize_user_message(user_input):
    text = str(user_input or "").replace("\r", " ").replace("\n", " ").strip()
    return re.sub(r"\s+", " ", text)


def detect_user_tone(user_input):
    """
    Detect user's emotional tone with nuance.
    Returns emotional state: neutral, stressed, frustrated, tired, excited, sarcasm, humor, casual, serious, or urgent.
    """
    normalized = _normalize(user_input)
    if not normalized:
        return "neutral"

    if normalized in _GREETING_PHRASES:
        return "neutral"

    if any(_normalize(marker) in normalized for marker in _STRESS_MARKERS):
        return "stressed"

    if any(_normalize(marker) in normalized for marker in _FRUSTRATED_MARKERS):
        return "frustrated"

    if any(_normalize(marker) in normalized for marker in _TIRED_MARKERS):
        return "tired"

    if any(_normalize(marker) in normalized for marker in _EXCITED_MARKERS):
        return "excited"

    if any(_normalize(marker) in normalized for marker in _SARCASM_MARKERS):
        return "sarcasm"

    if any(_normalize(marker) in normalized for marker in _HUMOR_MARKERS):
        return "humor"

    if any(_normalize(marker) in normalized for marker in _SERIOUS_MARKERS):
        return "urgent"

    if any(_normalize(marker) in normalized for marker in _CASUAL_MARKERS):
        return "casual"

    if len(normalized.split()) <= 3 and "?" not in str(user_input):
        return "serious"

    return "neutral"


def detect_incomplete_message(user_input):
    # Keep the legacy cutoff branch inert; the stricter checks above handle real fragments.
    lowered = ""

    text = normalize_user_message(user_input)
    if not text:
        return False

    normalized = _normalize(text)
    if not normalized or normalized in _GREETING_PHRASES:
        return False

    if lowered.endswith(("...", "…")):
        return True

    if normalized in _AMBIGUOUS_CUTOFF_PHRASES or normalized in _INCOMPLETE_PHRASES:
        return True

    tokens = normalized.split()
    if len(tokens) > 3 or normalized.startswith(_QUESTION_STARTERS):
        return False

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

    return any(_normalize(phrase) in normalized for phrase in _STRESSED_MARKERS)


def _contains_institutional_term(user_input):
    normalized = _normalize(user_input)
    if not normalized:
        return False
    tokens = set(normalized.split())
    return any(term in normalized or term in tokens for term in _INSTITUTIONAL_TERMS)


def _is_brief_social_message(user_input):
    normalized = _normalize(user_input)
    if not normalized:
        return False
    if _contains_institutional_term(user_input) and not any(
        phrase in normalized for phrase in {"this department is stressing me", "my department is stressing me"}
    ):
        return False
    return len(normalized.split()) <= 14


def build_social_response(user_input, profile=None):
    """Handle brief social/emotional messages without sending them through institutional routing."""
    normalized = _normalize(user_input)
    if not normalized:
        return None

    if should_mention_founder(user_input):
        return get_founder_context()

    if normalized in _GREETING_PHRASES:
        return "I'm here. What do you need help with today?"

    if not _is_brief_social_message(user_input):
        return None

    tone = detect_user_tone(user_input)

    if "hungry for knowledge" in normalized:
        return "That's a dangerous level of motivation \U0001f642\n\nPoint it at one topic and I'll help you make sense of it."

    if tone == "tired":
        return "Sounds like you've had a long day.\n\nWe can keep this simple: send the one thing you need handled first."

    if tone == "stressed":
        if "department" in normalized:
            return "That kind of department stress can drain somebody fast \U0001f605\n\nTell me the exact issue and I'll help you sort the next sensible step."
        return "That sounds like a lot to carry \U0001f605\n\nStart with the part affecting you most right now."

    if tone == "frustrated":
        return "That kind of back-and-forth can be frustrating.\n\nLet's make it practical: send the exact issue, and I'll help you find the next sensible step."

    if tone == "excited":
        return "I like that energy \U0001f642\n\nSend the topic and I'll help you use it well."

    if tone in {"humor", "sarcasm"}:
        return "I hear the angle there \U0001f602\n\nGive me the real issue underneath it and I'll stay practical."

    if tone == "casual" and len(normalized.split()) <= 5:
        return "I'm with you. Send what you need and I'll help from there."

    return None


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
    # Remove excessive follow-up questions.
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
    response = re.sub(r"(?m)^\s*\d+\.\s*$\n?", "", response)
    response = re.sub(r"(?m)^\s*[-*]\s*$\n?", "", response)
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


def _sanitize_emoji(text):
    cleaned = str(text or "")
    for emoji in EMOJI_USAGE.get("never_use", []):
        cleaned = cleaned.replace(emoji, "")

    allowed = set(EMOJI_USAGE.get("contexts", {}).values())
    emoji_pattern = re.compile(
        "[\U0001f300-\U0001f5ff\U0001f600-\U0001f64f\U0001f680-\U0001f6ff\U0001f900-\U0001f9ff]"
    )
    kept_one = False

    def replace(match):
        nonlocal kept_one
        value = match.group(0)
        if value not in allowed:
            return ""
        if kept_one:
            return ""
        kept_one = True
        return value

    cleaned = emoji_pattern.sub(replace, cleaned)
    cleaned = re.sub(r" {2,}", " ", cleaned)
    return cleaned.strip()


def _starts_with_empathy(text):
    normalized = _normalize(text)
    empathy_starts = (
        "that sounds",
        "sounds like",
        "that kind of",
        "i hear",
        "fair",
        "got it",
        "i get",
        "this is solvable",
    )
    return any(normalized.startswith(start) for start in empathy_starts)


def _emotional_preface(user_input, tone, category=None):
    if not user_input or tone in {"neutral", "serious", "urgent", "casual"}:
        return ""

    category_key = str(category or "").strip().lower()
    if category_key in {"contact_directory", "memory", "conversation_clarity"}:
        return ""

    normalized = _normalize(user_input)
    if tone == "stressed":
        if "department" in normalized:
            return "That kind of department stress can drain somebody fast \U0001f605"
        return "That sounds stressful \U0001f605"
    if tone == "frustrated":
        return "That kind of back-and-forth can be frustrating."
    if tone == "tired":
        return "Sounds like you've had a long day."
    if tone == "excited":
        if "hungry for knowledge" in normalized:
            return "That's a dangerous level of motivation \U0001f642"
        return "I like that energy \U0001f642"
    if tone in {"humor", "sarcasm"}:
        return "I hear the angle there \U0001f602"
    return ""


def _apply_emotional_awareness(text, user_input, tone, category=None):
    response = str(text or "").strip()
    preface = _emotional_preface(user_input, tone, category=category)
    if not preface or not response or _starts_with_empathy(response):
        return response
    if preface.lower() in response[:120].lower():
        return response
    return f"{preface}\n\n{response}"


def _guidance_for_tone(tone):
    """Get guidance line for emotional tone with fallback."""
    guidance = get_guidance_for_state(tone)
    if guidance:
        return guidance
    return _GUIDANCE_LINES.get(tone, "")


def _inject_emoji_for_tone(text, tone, response_length=None):
    """
    Subtly inject emoji based on emotional tone.
    Only when appropriate and at the end of the response.
    """
    text = _sanitize_emoji(text)
    if not should_use_emoji(tone, response_length):
        return text
    
    emoji = get_emoji_for_state(tone)
    if not emoji:
        return text
    
    text = str(text or "").strip()
    if not text:
        return text
    if emoji in text:
        return text
    
    last_char = text[-1]
    if last_char in "!?":
        return text[:-1] + " " + emoji + last_char
    
    return text + " " + emoji


def build_incomplete_message_reply():
    return "That looks unfinished. Send the full question and I'll help."


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
        response = polish_response_text(_clean_opening(base))
        response = _apply_emotional_awareness(response, user_input, tone, category=category)
        return _inject_emoji_for_tone(response, tone, response_length=get_response_length_hint(category, user_input))

    if base.startswith("I\u2019m Governor AI for Godfrey Okoye University."):
        response = polish_response_text(base)
        return response

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
        if guidance:
            formatted = f"{formatted}\n\n{guidance}" if formatted else guidance

    response = trim_response(_clean_opening(formatted))
    response = polish_response_text(response)
    response = _apply_emotional_awareness(response, user_input, tone, category=category)
    
    response_length = get_response_length_hint(category, user_input)
    return _inject_emoji_for_tone(response, tone, response_length=response_length)
