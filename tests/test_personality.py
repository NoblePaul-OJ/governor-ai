"""
Tests for personality module - emotional detection and context-aware responses.
"""

from app.services.personality import (
    EMOTIONAL_STATES,
    get_emoji_for_state,
    get_guidance_for_state,
    get_warmth_for_context,
    should_mention_founder,
    should_use_emoji,
)


def test_emotional_states_configuration():
    """Verify emotional states are properly configured."""
    assert "stressed" in EMOTIONAL_STATES
    assert "frustrated" in EMOTIONAL_STATES
    assert "excited" in EMOTIONAL_STATES
    assert "urgent" in EMOTIONAL_STATES


def test_emoji_for_stressed_state():
    """Test emoji retrieval for stressed emotional state."""
    assert get_emoji_for_state("stressed") == "\U0001f605"


def test_emoji_for_excited_state():
    """Test emoji retrieval for excited emotional state."""
    assert get_emoji_for_state("excited") == "\U0001f642"


def test_emoji_for_urgent_state():
    """Test emoji retrieval for urgent emotional state."""
    assert get_emoji_for_state("urgent") == "\U0001f44d"


def test_guidance_for_stressed_state():
    """Test guidance line for stressed emotional state."""
    guidance = get_guidance_for_state("stressed")
    assert guidance == "Take it one step at a time."


def test_guidance_for_frustrated_state():
    """Test guidance line for frustrated emotional state."""
    guidance = get_guidance_for_state("frustrated")
    assert guidance is not None


def test_warmth_for_context_hostel():
    """Test warmth level for hostel context."""
    warmth = get_warmth_for_context("hostel")
    assert warmth == "warm"


def test_warmth_for_context_academic():
    """Test warmth level for academic context."""
    warmth = get_warmth_for_context("academic")
    assert warmth == "composed"


def test_warmth_for_context_conversational():
    """Test warmth level for conversational context."""
    warmth = get_warmth_for_context("conversational")
    assert warmth == "warm"


def test_should_use_emoji_stressed():
    """Test emoji usage decision for stressed tone."""
    assert should_use_emoji("stressed", response_length="short")
    assert should_use_emoji("stressed", response_length="detailed")


def test_should_use_emoji_neutral():
    """Test emoji usage decision for neutral tone."""
    assert not should_use_emoji("neutral")


def test_should_use_emoji_max_once_per_response():
    """Test that emoji configuration limits to one per response."""
    from app.services.personality import EMOJI_USAGE

    assert EMOJI_USAGE["max_per_response"] == 1


def test_founder_mentions_are_origin_gated():
    assert should_mention_founder("who developed Governor AI")
    assert should_mention_founder("is Governor AI a real university project")
    assert not should_mention_founder("who is the bursar")
