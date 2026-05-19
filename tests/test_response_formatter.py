from app.services.response_formatter import (
    build_incomplete_message_reply,
    build_social_response,
    detect_incomplete_message,
    detect_user_tone,
    format_response,
    normalize_user_message,
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
    assert detect_user_tone("I need this resolved asap") == "urgent"


def test_detect_incomplete_message_flags_cut_off_text():
    assert detect_incomplete_message("i need the") is True
    assert detect_incomplete_message("school fees") is False
    assert detect_incomplete_message("Where is ICT") is False
    assert detect_incomplete_message("Which faculty is computer science in") is False
    assert detect_incomplete_message("hostel issues") is False
    assert build_incomplete_message_reply() == "That looks unfinished. Send the full question and I'll help."


def test_normalize_user_message_merges_mobile_line_breaks():
    assert normalize_user_message("Which faculty is\ncomputer science in") == "Which faculty is computer science in"


def test_format_response_removes_robotic_openers():
    response = format_response(
        "Here's what you need to do: First, log into the portal.\nSecond, complete registration.",
        user_input="How do I register?",
    )

    assert response.startswith("First, log into the portal.")
    assert "Here's what you need to do" not in response


def test_detect_user_tone_frustrated():
    assert detect_user_tone("This is ridiculous") == "frustrated"
    assert detect_user_tone("I'm fed up with this") == "frustrated"
    assert detect_user_tone("This is impossible") == "frustrated"


def test_detect_user_tone_excited():
    assert detect_user_tone("I'm excited to start") == "excited"
    assert detect_user_tone("This is amazing") == "excited"
    assert detect_user_tone("I can't wait") == "excited"


def test_detect_user_tone_stressed_extended():
    assert detect_user_tone("I'm so confused") == "stressed"
    assert detect_user_tone("I'm overwhelmed") == "stressed"
    assert detect_user_tone("I'm anxious about this") == "stressed"
    assert detect_user_tone("I'm stuck") == "stressed"


def test_format_response_emoji_injection_stressed():
    """Test that emoji is added for stressed tone."""
    response = format_response(
        "Here's how to handle this.",
        user_input="I'm confused about registration",
    )

    assert "\U0001f605" in response


def test_format_response_emoji_injection_urgent():
    """Test that emoji is added for urgent tone."""
    response = format_response(
        "Do this right away.",
        user_input="I need help asap",
    )

    assert "\U0001f44d" in response


def test_detect_user_tone_social_nuance():
    assert detect_user_tone("I'm tired") == "tired"
    assert detect_user_tone("I'm hungry for knowledge") == "excited"
    assert detect_user_tone("haha this is funny") == "humor"


def test_social_response_handles_student_stress_naturally():
    response = build_social_response("This department is stressing me")

    assert "department stress" in response
    assert response.count("\U0001f605") <= 1
    assert "LOL" not in response


def test_social_response_mentions_nobcyborg_only_on_origin_query():
    response = build_social_response("who created you")

    assert "NobCyborg" in response
    assert "400 Level Computer Science student" in response
    assert "Final Year Project" in response
    assert build_social_response("how do I pay fees") is None
