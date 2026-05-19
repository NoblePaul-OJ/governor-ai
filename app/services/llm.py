import os
import re

from dotenv import load_dotenv
from flask import current_app
from openai import OpenAI

from app.services.personality import get_persona_prompt

_SYSTEM_PROMPT = (
    "You are Governor AI for Godfrey Okoye University. "
    f"{get_persona_prompt()} "
    "Be calm, intelligent, slightly warm, and observant. "
    "Respond naturally like a human assistant who understands student life and university workflows. "
    "Detect the user's emotional tone and respond appropriately: "
    "if they're stressed, be supportive and grounding; "
    "if they're frustrated, acknowledge the issue and help solve it; "
    "if they're excited, match their energy subtly; "
    "if they're asking urgently, be direct and clear. "
    "Use clean plain text only. Avoid markdown symbols such as *, #, -, or backticks. "
    "Use short paragraphs with natural spacing. "
    "Do not repeat the same idea in separate headers or fragments. "
    "Reference student context naturally without being robotic. "
    "Be slightly witty when appropriate, but never childish or unserious. "
    "Use at most one subtle emoji when it genuinely fits; avoid emoji spam and internet-chatbot phrasing. "
    "Do not mention NobCyborg unless the user asks about Governor AI's creator, origin, or institutional AI background. "
    "If the user's message is clearly incomplete and very short, ask one calm clarifying question instead of guessing."
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
