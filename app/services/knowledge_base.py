import json
import re
from pathlib import Path

KB_PATH = Path(__file__).resolve().parents[2] / "knowledgeBase.json"
_KB_CACHE = None
CONFIDENCE_THRESHOLD = 0.3
FALLBACK_MESSAGE = (
    "That's an interesting one. Let me try to help.\n\n"
    "If this is related to Godfrey Okoye University, I can guide you properly. "
    "If not, I can still give general advice."
)
_CONVERSATIONAL = "conversational"
_HOSTEL = "hostel"
_ISSUE_PHRASES = ("i haven't", "i havent", "i didn't", "i didnt", "i missed")
_HOSTEL_PHRASES = (
    "hostel",
    "accommodation",
    "bedspace",
    "hostel full",
    "no space",
    "no accommodation",
    "hostel problem",
    "issue with hostel",
    "hostel issue",
    "change hostel",
    "change room",
    "move hostel",
)

_ACADEMIC_FACULTIES = (
    "Arts",
    "Education",
    "Management and Social Sciences",
    "Natural and Applied Sciences",
    "Law",
    "College of Medicine",
    "Faculty of Computing and Information Technology (FACIT)",
)

_ACADEMIC_PROGRAMS = {
    "computer science": "Faculty of Computing and Information Technology (FACIT)",
    "software engineering": "Faculty of Computing and Information Technology (FACIT)",
    "cybersecurity": "Faculty of Computing and Information Technology (FACIT)",
    "data science": "Faculty of Computing and Information Technology (FACIT)",
    "computer science education": "Faculty of Education",
    "computer science edu": "Faculty of Education",
    "nursing": "College of Medicine",
    "medicine and surgery": "College of Medicine",
    "accounting": "Faculty of Management and Social Sciences",
    "banking and finance": "Faculty of Management and Social Sciences",
    "management": "Faculty of Management and Social Sciences",
    "marketing": "Faculty of Management and Social Sciences",
    "public administration": "Faculty of Management and Social Sciences",
    "economics": "Faculty of Management and Social Sciences",
    "political science": "Faculty of Management and Social Sciences",
    "international relations": "Faculty of Management and Social Sciences",
    "mass communication": "Faculty of Management and Social Sciences",
    "mass communications": "Faculty of Management and Social Sciences",
    "philosophy": "Faculty of Management and Social Sciences",
    "psychology": "Faculty of Management and Social Sciences",
    "religious studies": "Faculty of Management and Social Sciences",
    "sociology": "Faculty of Management and Social Sciences",
    "history and international studies": "Faculty of Arts",
    "history, international studies": "Faculty of Arts",
    "music": "Faculty of Arts",
    "english and lit studies": "Faculty of Arts",
    "applied biology": "Faculty of Natural and Applied Sciences",
    "biotechnology": "Faculty of Natural and Applied Sciences",
    "microbiology": "Faculty of Natural and Applied Sciences",
    "chemistry": "Faculty of Natural and Applied Sciences",
    "biochemistry": "Faculty of Natural and Applied Sciences",
    "industrial chemistry": "Faculty of Natural and Applied Sciences",
    "mathematics": "Faculty of Natural and Applied Sciences",
    "physics": "Faculty of Natural and Applied Sciences",
    "architecture": "Faculty of Natural and Applied Sciences",
    "law": "Faculty of Law",
    "juris and intl law": "Faculty of Law",
    "public law": "Faculty of Law",
    "private and biz law": "Faculty of Law",
}

_ACADEMIC_QUERY_PHRASES = (
    "which faculty",
    "what faculty",
    "which department",
    "what department",
    "faculty of",
    "department of",
    "school structure",
    "school faculties",
    "faculty list",
    "course list",
    "where is",
    "where does",
    "what courses",
    "which courses",
    "program structure",
    "university structure",
)


def _normalize(text):
    cleaned = re.sub(r"[^a-zA-Z0-9\\s]", " ", (text or "").lower())
    return " ".join(cleaned.split())


def _tokenize(text):
    normalized = _normalize(text)
    return set(normalized.split()) if normalized else set()


def _is_conversational(entry):
    return str(entry.get("category", "")).lower() == _CONVERSATIONAL


def _is_hostel(entry):
    return str(entry.get("category", "")).lower() == _HOSTEL


def _is_issue_entry(entry):
    return "issue" in str(entry.get("intent", "")).lower()


def _get_keywords(entry):
    keywords = entry.get("keywords") or []
    return {_normalize(k) for k in keywords if k}


def _is_issue_signal(normalized_input):
    return any(phrase in normalized_input for phrase in _ISSUE_PHRASES)


def _is_hostel_signal(normalized_input):
    if not normalized_input:
        return False
    if any(phrase in normalized_input for phrase in _HOSTEL_PHRASES):
        return True
    tokens = set(normalized_input.split())
    return bool(tokens & {"hostel", "accommodation", "bedspace"})


def load_knowledge_base():
    global _KB_CACHE
    if _KB_CACHE is not None:
        return _KB_CACHE

    if not KB_PATH.exists():
        _KB_CACHE = []
        return _KB_CACHE

    with KB_PATH.open("r", encoding="utf-8-sig") as handle:
        _KB_CACHE = json.load(handle)
    return _KB_CACHE


def _result(entry, confidence, matched_question):
    return {
        "matched": True,
        "intent": entry.get("intent"),
        "category": entry.get("category"),
        "answer": entry.get("answer"),
        "matched_question": matched_question,
        "confidence": round(confidence, 3),
    }


def _no_match():
    return {
        "matched": False,
        "intent": None,
        "category": None,
        "answer": FALLBACK_MESSAGE,
        "matched_question": None,
        "confidence": 0.0,
    }


def match_conversational(user_input):
    entries = load_knowledge_base()
    normalized_input = _normalize(user_input)
    if not normalized_input:
        return _no_match()

    ordered_entries = [entry for entry in entries if _is_hostel(entry)]
    ordered_entries.extend(entry for entry in entries if _is_conversational(entry))

    for entry in ordered_entries:
        keywords = _get_keywords(entry)
        for question in entry.get("questions", []):
            if _normalize(question) == normalized_input:
                return _result(entry, 1.0, question)

        if normalized_input in keywords:
            return _result(entry, 1.0, None)

    return _no_match()


def detect_hostel_context(user_input, kb_entries=None):
    normalized_input = _normalize(user_input)
    if not normalized_input:
        return False

    if _is_hostel_signal(normalized_input):
        return True

    if kb_entries:
        return any(str(entry.get("category", "")).lower() == _HOSTEL for entry in kb_entries)

    return False


def match_academic(user_input):
    entries = load_knowledge_base()
    normalized_input = _normalize(user_input)
    user_tokens = _tokenize(user_input)
    if not user_tokens:
        return _no_match()

    short_input = len(normalized_input) < 15
    issue_signal = _is_issue_signal(normalized_input)

    if short_input:
        for entry in entries:
            if _is_conversational(entry):
                continue
            keywords = _get_keywords(entry)
            if normalized_input in keywords:
                return _result(entry, 1.0, None)
            if issue_signal and _is_issue_entry(entry):
                if any(kw and kw in normalized_input for kw in keywords):
                    return _result(entry, 0.7, None)
        return _no_match()

    best = None
    best_score = 0.0
    best_question = None
    hostel_signal = _is_hostel_signal(normalized_input)

    for entry in entries:
        if _is_conversational(entry):
            continue

        keywords = _get_keywords(entry)
        keyword_hit = any(kw and kw in normalized_input for kw in keywords)

        for question in entry.get("questions", []):
            question_tokens = _tokenize(question)
            if not question_tokens:
                continue

            intersection = user_tokens & question_tokens
            if len(intersection) < 1 and not keyword_hit:
                continue

            score = len(intersection) / len(question_tokens)
            if keyword_hit:
                score = min(1.0, score + 0.2)
            if issue_signal and _is_issue_entry(entry):
                score = min(1.0, score + 0.2)
            if hostel_signal and _is_hostel(entry):
                score = min(1.0, score + 0.2)

            if len(intersection) < 2 and not keyword_hit:
                continue

            if score > best_score:
                best_score = score
                best = entry
                best_question = question

    if best and best_score >= CONFIDENCE_THRESHOLD:
        return _result(best, best_score, best_question)

    return _no_match()


def _entry_relevance(entry, normalized_input, user_tokens):
    best_score = 0.0
    best_question = None

    keywords = _get_keywords(entry)
    keyword_hits = sum(1 for kw in keywords if kw and kw in normalized_input)
    if keywords and keyword_hits:
        best_score = max(best_score, min(1.0, (keyword_hits / len(keywords)) + 0.25))

    category_tokens = _tokenize(entry.get("category", ""))
    category_overlap = len(category_tokens & user_tokens)
    if category_overlap:
        best_score = max(best_score, min(1.0, 0.2 + (category_overlap / max(1, len(category_tokens)))))

    if _is_hostel_signal(normalized_input) and _is_hostel(entry):
        best_score = max(best_score, min(1.0, best_score + 0.2))

    for question in entry.get("questions", []):
        normalized_question = _normalize(question)
        if normalized_question == normalized_input:
            return 1.0, question

        question_tokens = _tokenize(question)
        if not question_tokens:
            continue

        overlap = len(user_tokens & question_tokens)
        if overlap <= 0:
            continue

        score = overlap / len(question_tokens)
        if keyword_hits:
            score = min(1.0, score + 0.2)

        if score > best_score:
            best_score = score
            best_question = question

    return best_score, best_question


def find_relevant_entries(user_input, limit=3, min_confidence=0.3):
    normalized_input = _normalize(user_input)
    user_tokens = _tokenize(user_input)
    if not normalized_input or not user_tokens:
        return []

    candidates = []
    for entry in load_knowledge_base():
        score, matched_question = _entry_relevance(entry, normalized_input, user_tokens)
        if score < min_confidence:
            continue
        candidates.append(
            {
                "intent": entry.get("intent"),
                "category": entry.get("category"),
                "answer": entry.get("answer"),
                "matched_question": matched_question,
                "confidence": round(score, 3),
            }
        )

    candidates.sort(key=lambda item: item["confidence"], reverse=True)
    return candidates[:limit]


def _academic_program_match(normalized_input):
    for program, faculty in sorted(_ACADEMIC_PROGRAMS.items(), key=lambda item: len(item[0]), reverse=True):
        if program in normalized_input:
            return program, faculty
    return None, None


def _academic_reply_for_program(program, faculty, wants_department=False):
    label = " ".join(part.capitalize() for part in program.split())
    if wants_department:
        return f"{label} is a department in the {faculty} at Godfrey Okoye University."
    return f"{label} is under the {faculty} at Godfrey Okoye University."


def _academic_structure_overview():
    return (
        "Godfrey Okoye University currently lists these main faculties: "
        f"{', '.join(_ACADEMIC_FACULTIES[:-1])}, and {_ACADEMIC_FACULTIES[-1]}. "
        "If you want, I can point you to the faculty for a specific course."
    )


def resolve_academic_structure_query(user_input):
    normalized_input = _normalize(user_input)
    if not normalized_input:
        return {"handled": False}

    if any(phrase in normalized_input for phrase in _ACADEMIC_QUERY_PHRASES):
        program, faculty = _academic_program_match(normalized_input)
        if program and faculty:
            wants_department = "department" in normalized_input and "faculty" not in normalized_input
            reply = _academic_reply_for_program(program, faculty, wants_department=wants_department)
            return {
                "handled": True,
                "source": "academic_structure",
                "intent": f"{program.replace(' ', '_')}_{'department' if wants_department else 'faculty'}",
                "category": "academic_structure",
                "reply": reply,
                "confidence": 1.0,
                "matched_question": None,
                "fallback": False,
                "use_llm": False,
            }

        if any(phrase in normalized_input for phrase in ("school structure", "school faculties", "faculty list", "course list", "university structure")):
            return {
                "handled": True,
                "source": "academic_structure",
                "intent": "university_structure_overview",
                "category": "academic_structure",
                "reply": _academic_structure_overview(),
                "confidence": 1.0,
                "matched_question": None,
                "fallback": False,
                "use_llm": False,
            }

    program, faculty = _academic_program_match(normalized_input)
    if program and faculty and (normalized_input == program or any(phrase in normalized_input for phrase in _ACADEMIC_QUERY_PHRASES)):
        reply = _academic_reply_for_program(program, faculty, wants_department="department" in normalized_input)
        return {
            "handled": True,
            "source": "academic_structure",
            "intent": f"{program.replace(' ', '_')}_{'department' if 'department' in normalized_input else 'faculty'}",
            "category": "academic_structure",
            "reply": reply,
            "confidence": 1.0,
            "matched_question": None,
            "fallback": False,
            "use_llm": False,
        }

    if any(phrase in normalized_input for phrase in ("school structure", "school faculties", "faculty list", "course list", "university structure")):
        return {
            "handled": True,
            "source": "academic_structure",
            "intent": "university_structure_overview",
            "category": "academic_structure",
            "reply": _academic_structure_overview(),
            "confidence": 1.0,
            "matched_question": None,
            "fallback": False,
            "use_llm": False,
        }

    return {"handled": False}
