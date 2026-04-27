from app.services.store import add_log, QUERY_LOGS, get_stats, get_system_insights


def test_add_log_and_stats():
    # clear any previous logs
    QUERY_LOGS.clear()
    entry = add_log("What is the fee?", "Fees & Payment", "Here you go", 0.5)
    assert entry in QUERY_LOGS
    stats = get_stats()
    assert stats["total"] == 1
    assert stats["matched"] == 1
    assert stats["fallback"] == 0
    assert stats["per_intent"]["Fees & Payment"] == 1

    keywords = get_stats()
    # ensure keyword_counts works even with a single entry
    from app.services.store import keyword_counts
    kws = keyword_counts()
    assert isinstance(kws, list)


def test_system_insights_flags_and_counts():
    QUERY_LOGS.clear()
    add_log("I don't understand", None, "Try again", 0.0, status="unanswered", is_fallback=True)
    add_log("I don't understand", None, "Try again", 0.0, status="unanswered", is_fallback=True)
    add_log("Hostel booking", "book_hostel", "Step 1", 1.0, status="task_in_progress", workflow_type="book_hostel")

    insights = get_system_insights(limit=10)

    assert insights["failed_responses"] == 2
    assert insights["signal_counts"]["confused_queries"] == 2
    assert insights["signal_counts"]["repeated_queries"] == 1
    assert insights["most_requested_services"][0]["service"] == "book_hostel"
    assert insights["top_queries"][0]["count"] == 2
