from app.services.response_formatter import format_response


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
