import os
import re

from dotenv import load_dotenv
from flask import current_app
from openai import OpenAI

_SYSTEM_PROMPT = (
    "You are Governor AI for Godfrey Okoye University. "
    "Always respond naturally like a human assistant. "
    "If the query is unrelated, respond conversationally but gently guide back to university context when appropriate. "
    "Use clean plain text only. Avoid markdown symbols such as *, #, -, or backticks. "
    "Use short paragraphs with natural spacing."
)

LLM_FALLBACK_MESSAGE = (
    "That's an interesting one. Let me try to help.\n\n"
    "If this is related to Godfrey Okoye University, I can guide you properly. "
    "If not, I can still give general advice."
)


def clean_response(text):
    text = (text or "").replace("\r\n", "\n")

    # Remove markdown symbols and common bullet prefixes.
    text = re.sub(r"[#*`>]", "", text)
    text = re.sub(r"^\s*[-\u2022]\s*", "", text, flags=re.MULTILINE)
    text = re.sub(r"^\s*\d+\.\s*", "", text, flags=re.MULTILINE)

    # Keep readable paragraph spacing.
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)

    return text.strip()


def _get_client():
    load_dotenv()
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not set.")
    return OpenAI(api_key=api_key)


def call_llm(user_input, timeout=25):
    client = _get_client()
    response = client.with_options(timeout=timeout).responses.create(
        model=current_app.config["OPENAI_MODEL"],
        input=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": user_input},
        ],
        temperature=0.7,
    )
    response_text = (response.output_text or "").strip()
    return clean_response(response_text)


def call_llm_with_retry(user_input, timeout=25, retries=1):
    attempts = max(0, retries) + 1
    for attempt in range(attempts):
        try:
            response = call_llm(user_input, timeout=timeout)
        except Exception as error:
            current_app.logger.warning(
                "LLM call failed on attempt %s/%s: %s", attempt + 1, attempts, error
            )
            response = None

        if response:
            return response

    return None


def call_llm_with_timeout(user_input, timeout=25):
    return call_llm_with_retry(user_input, timeout=timeout, retries=0)
