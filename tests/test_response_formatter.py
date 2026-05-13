from app.services.response_formatter import (
    build_incomplete_message_reply,
    detect_incomplete_message,
    detect_user_tone,
    format_response,
)


def test_format_response_stays_direct_without_memory_prefix():
    response = format_response(
        "You should register as soon as possible.",
        user_input="How do I register courses",
        profile={"name": "Ada Lovelace", "department": "Computer Science", "level": "400"},
    )

    assert response == "You should register as soon as possible."
    assert "You are a 400 level" not in response
    assert "Here's a quick answer" not in response
    assert "Sure - here's the gist" not in response


def test_format_response_keeps_casual_queries_simple():
    response = format_response(
        "Have a good meal first.",
        user_input="I want to eat",
        profile={"name": "Ada Lovelace", "department": "Computer Science", "level": "400"},
    )

    assert response == "Have a good meal first."


def test_detect_user_tone_classifies_common_messages():
    assert detect_user_tone("lol thanks") == "casual"
    assert detect_user_tone("I am confused about registration") == "stressed"
    assert detect_user_tone("I need this resolved asap") == "serious"


def test_detect_incomplete_message_flags_cut_off_text():
    assert detect_incomplete_message("i need the") is True
    assert detect_incomplete_message("school fees") is False
    assert build_incomplete_message_reply() == "Looks like your message got cut off — what do you need?"


def test_format_response_removes_robotic_openers():
    response = format_response(
        "Here's what you need to do: First, log into the portal.\nSecond, complete registration.",
        user_input="How do I register?",
    )

    assert response.startswith("First, log into the portal.")
    assert "Here's what you need to do" not in response
