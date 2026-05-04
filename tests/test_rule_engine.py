from app.services.rule_engine import classify_intent, INTENT_RULES


def test_basic_intent_matching():
    # sample questions expected to match each rule based on keywords
    for key, rule in INTENT_RULES.items():
        # pick first keyword and embed it in a sentence
        kw = rule["keywords"][0]
        question = f"Can you tell me about {kw}?" if kw else ""
        result = classify_intent(question)
        assert result["matched"], f"rule {key} should match question '{question}'"
        assert result["intent_key"] == key


def test_unmatched_question():
    result = classify_intent("this is a completely unrelated query")
    assert not result["matched"]
    assert result["confidence"] == 0.0


def test_contextual_followup_uses_history():
    history = [
        {"role": "user", "content": "I have not registered courses"},
        {"role": "assistant", "content": "Here are the steps to register courses."},
    ]

    result = classify_intent("also", history=history)
    assert result["matched"]
    assert result["intent_key"] == "course_registration"
    assert result["contextual"] is True


def test_direct_topic_switch_is_marked():
    history = [
        {"role": "user", "content": "I have not registered courses"},
        {"role": "assistant", "content": "Here are the steps to register courses."},
    ]

    result = classify_intent("hostel", history=history)
    assert result["matched"]
    assert result["intent_key"] == "hostel"
    assert result["topic_shift"] is True
