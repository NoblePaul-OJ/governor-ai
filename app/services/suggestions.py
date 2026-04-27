import json
from pathlib import Path

from app.services.llm import call_llm_with_timeout
from app.services.store import get_unanswered_counts

SUGGESTED_INTENTS_PATH = Path(__file__).resolve().parents[2] / "suggested_intents.json"

PROMPT_TEMPLATE = (
    "We are improving the chatbot learning system.\n\n"
    "I already have a query_logs table (or JSON) that stores user questions with status \"unanswered\".\n\n"
    "Your task:\n\n"
    "1. Fetch all unanswered queries\n\n"
    "2. Group similar questions together (based on meaning, not exact words)\n\n"
    "3. For each group:\n"
    "   - Create a new intent name (short and meaningful)\n"
    "   - Generate 5 different question variations from the grouped queries\n"
    "   - Generate ONE clear, concise answer suitable for Godfrey Okoye University students\n"
    "   - Assign an appropriate category (e.g., Academics, Hostel, Admissions, Student Life)\n\n"
    "4. Output the result in this format:\n\n"
    "{\n"
    "  \"intent\": \"intent_name\",\n"
    "  \"questions\": [\n"
    "    \"question 1\",\n"
    "    \"question 2\",\n"
    "    \"question 3\",\n"
    "    \"question 4\",\n"
    "    \"question 5\"\n"
    "  ],\n"
    "  \"answer\": \"clear answer tailored to Godfrey Okoye University\",\n"
    "  \"category\": \"category_name\"\n"
    "}\n\n"
    "5. Do NOT overwrite the existing knowledge base.\n\n"
    "6. Instead:\n"
    "   - Return all generated intents\n"
    "   - OR append them to a separate file called:\n"
    "     \"suggested_intents.json\"\n\n"
    "7. Keep answers:\n"
    "   - Short (2\u20134 lines)\n"
    "   - Practical\n"
    "   - Specific to Godfrey Okoye University\n\n"
    "8. Ignore irrelevant or nonsense queries.\n\n"
    "Goal:\n"
    "Transform real user questions into structured chatbot knowledge.\n\n"
    "Add frequency tracking:\n\n"
    "{\n"
    "  \"question\": \"hostel\",\n"
    "  \"count\": 17\n"
    "}\n\n"
    "Auto-suggest new intents\n\n"
    "Example:\n\n"
    "if similar_questions_detected:\n"
    "    suggest_new_intent()\n"
)


def build_suggestion_prompt():
    unanswered = get_unanswered_counts()
    payload = json.dumps(unanswered, ensure_ascii=False, indent=2)
    return f"{PROMPT_TEMPLATE}\n\nUnanswered queries (with frequency):\n{payload}\n"


def _extract_json(text):
    if not text:
        return None

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    start = text.find("[")
    end = text.rfind("]")
    if start != -1 and end != -1 and end > start:
        snippet = text[start : end + 1]
        try:
            return json.loads(snippet)
        except json.JSONDecodeError:
            return None

    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        snippet = text[start : end + 1]
        try:
            return json.loads(snippet)
        except json.JSONDecodeError:
            return None

    return None


def _append_suggestions(suggestions):
    if not suggestions:
        return []

    items = suggestions if isinstance(suggestions, list) else [suggestions]
    existing = []
    if SUGGESTED_INTENTS_PATH.exists():
        try:
            existing = json.loads(SUGGESTED_INTENTS_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            existing = []

    combined = existing + items
    SUGGESTED_INTENTS_PATH.write_text(json.dumps(combined, ensure_ascii=False, indent=2), encoding="utf-8")
    return combined


def generate_suggested_intents(write_to_file=True):
    prompt = build_suggestion_prompt()
    response = call_llm_with_timeout(prompt)
    if not response:
        return None

    suggestions = _extract_json(response)
    if write_to_file and suggestions:
        return _append_suggestions(suggestions)

    return suggestions or response
