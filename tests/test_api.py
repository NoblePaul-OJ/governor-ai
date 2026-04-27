import json
import sqlite3

from app import create_app
from app.services.store import QUERY_LOGS, reset_conversation_state


def test_chat_endpoint(monkeypatch):
    app = create_app()
    client = app.test_client()
    QUERY_LOGS.clear()
    reset_conversation_state()

    from app.blueprints.chat import routes as chat_routes

    monkeypatch.setattr(
        chat_routes,
        "call_llm_with_retry",
        lambda *_args, **_kwargs: "Test assistant reply",
    )

    # empty message should return error
    resp = client.post("/api/chat", json={})
    assert resp.status_code == 400

    # valid question
    resp = client.post("/api/chat", json={"message": "What about fees?"})
    assert resp.status_code == 200
    data = resp.get_json()
    assert "reply" in data
    assert "intent" in data
    assert "confidence" in data
    assert data["reply"] == "Test assistant reply"
    assert data["source"] == "llm_primary"
    assert data["fallback"] is False

    # logs endpoint
    resp = client.get("/api/logs")
    assert resp.status_code == 200
    logs = resp.get_json()
    assert isinstance(logs, list)

    # admin interface should be reachable
    resp = client.get("/admin/")
    assert resp.status_code == 200

    # ensure we can fetch and update intents via admin API
    resp = client.get("/admin/intents.json")
    assert resp.status_code == 200
    rules = resp.get_json()
    assert isinstance(rules, dict)

    # post the same rules back (should succeed)
    resp = client.post(
        "/admin/intents",
        data={"rules": json.dumps(rules)},
        content_type="application/x-www-form-urlencoded",
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert b"Intent rules updated successfully" in resp.data


def test_task_flow_and_db_storage(monkeypatch, tmp_path):
    app = create_app()
    app.config["TASK_DB_ENABLED"] = True
    app.config["TASK_DB_PATH"] = str(tmp_path / "task_requests_test.db")
    client = app.test_client()
    QUERY_LOGS.clear()
    reset_conversation_state()

    from app.blueprints.chat import routes as chat_routes

    # Task flows should not call the LLM path.
    monkeypatch.setattr(
        chat_routes,
        "call_llm_with_retry",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("LLM should not be called")),
    )

    sequence = [
        "I want hostel booking",
        "yes",
        "Paul Ojimadu",
        "GOU/22/1234",
        "Computer Science 400 Level",
        "St. Francis Hostel",
        "08012345678",
        "not yet",
    ]

    final_data = None
    responses = []
    for message in sequence:
        resp = client.post("/api/chat", json={"message": message})
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["source"] == "task_flow"
        responses.append(data)
        final_data = data

    assert final_data is not None
    assert final_data["task"]["completed"] is True
    assert "Step 3" in final_data["reply"]
    assert "Final summary for Hostel Booking" in final_data["reply"]
    assert "Next actions:" in final_data["reply"]
    assert any(item["task"]["current_step"] == "step_2" for item in responses[:-1])
    assert any("Step 2" in item["reply"] for item in responses[:-1])

    db_path = tmp_path / "task_requests_test.db"
    assert db_path.exists()
    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT task_key, output_type FROM task_requests ORDER BY id DESC LIMIT 1"
        ).fetchone()

    assert row is not None
    assert row[0] == "book_hostel"
    assert row[1] == "request_summary"

    html_resp = client.get("/admin/task-requests")
    assert html_resp.status_code == 200
    assert b"Saved Task Requests" in html_resp.data
    assert b"Hostel Booking" in html_resp.data

    json_resp = client.get("/admin/task-requests.json")
    assert json_resp.status_code == 200
    payload = json_resp.get_json()
    assert payload["enabled"] is True
    assert payload["count"] >= 1
    assert payload["requests"][0]["task_key"] == "book_hostel"


def test_task_intent_detection_paths(monkeypatch):
    app = create_app()
    client = app.test_client()
    QUERY_LOGS.clear()
    reset_conversation_state()

    from app.blueprints.chat import routes as chat_routes

    monkeypatch.setattr(
        chat_routes,
        "call_llm_with_retry",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("LLM should not be called")),
    )

    probes = {
        "hostel booking": "book_hostel",
        "see the VC": "vc_appointment",
        "VC appointment": "vc_appointment",
        "contact request": "contact_request",
        "report issue": "report_issue",
    }

    for message, expected in probes.items():
        reset_conversation_state()
        resp = client.post("/api/chat", json={"message": f"I want to {message}"})
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["source"] == "task_flow"
        assert data["intent"] == expected
        assert data["task"]["active"] is True
        assert data["task"]["current_step"] == "step_1"
        assert "Step 1" in data["reply"]

    reset_conversation_state()
    resp = client.post("/api/chat", json={"message": "I want hostel"})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["source"] == "task_flow"
    assert data["intent"] == "book_hostel"
    assert data["task"]["current_step"] == "step_1"
    assert "Step 1" in data["reply"]


def test_hostel_kb_matching_and_response(monkeypatch):
    app = create_app()
    client = app.test_client()
    QUERY_LOGS.clear()
    reset_conversation_state()

    from app.blueprints.chat import routes as chat_routes
    from app.services.knowledge_base import match_conversational

    direct_cases = {
        "how to apply for hostel": "hostel_application",
        "hostel full": "hostel_full",
        "change hostel": "hostel_change",
        "my room has issues": "hostel_issue",
    }

    for message, expected_intent in direct_cases.items():
        result = match_conversational(message)
        assert result["matched"] is True
        assert result["category"] == "hostel"
        assert result["intent"] == expected_intent

    monkeypatch.setattr(
        chat_routes,
        "call_llm_with_retry",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("LLM should not be called")),
    )

    for message, expected_intent in {
        "hostel full": "hostel_full",
        "change hostel": "hostel_change",
        "my room has issues": "hostel_issue",
    }.items():
        reset_conversation_state()
        resp = client.post("/api/chat", json={"message": message})
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["source"] == "knowledge_base"
        assert data["category"] == "hostel"
        assert data["intent"] == expected_intent
        assert data["fallback"] is False
        assert data["reply"]


def test_hostel_llm_prompt_enhancement(monkeypatch):
    app = create_app()
    client = app.test_client()
    QUERY_LOGS.clear()
    reset_conversation_state()

    from app.blueprints.chat import routes as chat_routes

    captured = {}

    def fake_llm(prompt, timeout=25, retries=1):
        captured["prompt"] = prompt
        return "Please go to the hostel office.\n- Bring your receipt."

    monkeypatch.setattr(chat_routes, "call_llm_with_retry", fake_llm)

    client.post("/api/chat", json={"message": "I have not registered courses"})
    captured.clear()

    resp = client.post("/api/chat", json={"message": "Explain hostel allocation rules"})
    assert resp.status_code == 200
    data = resp.get_json()

    assert data["source"] == "llm_primary"
    assert "You are Governor AI for Godfrey Okoye University. The user is asking about hostel or accommodation." in captured["prompt"]
    assert "course registration and fees" in captured["prompt"]
    assert "Also, make sure your course registration and fees are sorted, as they can affect hostel allocation." in data["reply"]
    assert "- Bring your receipt." not in data["reply"]
    assert "*" not in data["reply"]
    assert "#" not in data["reply"]


def test_vc_appointment_workflow_and_pause_resume(monkeypatch, tmp_path):
    app = create_app()
    app.config["TASK_DB_ENABLED"] = True
    app.config["TASK_DB_PATH"] = str(tmp_path / "vc_task_requests.db")
    app.config["QUERY_LOG_DB_PATH"] = str(tmp_path / "vc_chat_logs.db")
    client = app.test_client()
    QUERY_LOGS.clear()
    reset_conversation_state()

    from app.blueprints.chat import routes as chat_routes

    monkeypatch.setattr(
        chat_routes,
        "call_llm_with_retry",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("LLM should not be called")),
    )

    resp = client.post("/api/chat", json={"message": "see the VC"})
    data = resp.get_json()
    assert data["source"] == "task_flow"
    assert data["intent"] == "vc_appointment"
    assert data["task"]["current_step"] == "step_1"
    assert "full name" in data["reply"].lower()

    resp = client.post("/api/chat", json={"message": "John Doe"})
    data = resp.get_json()
    assert data["task"]["current_step"] == "step_2"
    assert "matric number and department" in data["reply"].lower()

    resp = client.post("/api/chat", json={"message": "I want hostel booking"})
    data = resp.get_json()
    assert data["source"] == "task_flow"
    assert data["intent"] == "book_hostel"
    assert data["task"]["current_step"] == "step_1"
    assert "hostel application" in data["reply"].lower()

    resp = client.post("/api/chat", json={"message": "continue vc appointment"})
    data = resp.get_json()
    assert data["source"] == "task_flow"
    assert data["intent"] == "vc_appointment"
    assert data["task"]["current_step"] == "step_2"
    assert "matric number and department" in data["reply"].lower()

    resp = client.post("/api/chat", json={"message": "GOU/22/1234, Computer Science"})
    data = resp.get_json()
    assert data["task"]["current_step"] == "step_3"
    assert "reason for the appointment" in data["reply"].lower()

    resp = client.post("/api/chat", json={"message": "I need clarification on my academic status"})
    data = resp.get_json()
    assert data["task"]["current_step"] == "step_4"
    assert "how urgent" in data["reply"].lower()

    resp = client.post("/api/chat", json={"message": "urgent"})
    data = resp.get_json()
    assert data["task"]["current_step"] == "step_5"
    assert "preferred time" in data["reply"].lower()

    resp = client.post("/api/chat", json={"message": "tomorrow morning"})
    data = resp.get_json()
    assert data["task"]["current_step"] == "step_6"
    assert "vc appointment summary" in data["reply"].lower()
    assert "reply yes to confirm" in data["reply"].lower()

    resp = client.post("/api/chat", json={"message": "yes"})
    data = resp.get_json()
    assert data["task"]["completed"] is True
    assert data["task"]["current_step"] is None
    assert "formal appointment letter" in data["reply"].lower()
    assert "dear vice chancellor" in data["reply"].lower()


def test_contact_directory_lookup(monkeypatch):
    app = create_app()
    client = app.test_client()
    QUERY_LOGS.clear()
    reset_conversation_state()

    from app.blueprints.chat import routes as chat_routes

    monkeypatch.setattr(
        chat_routes,
        "call_llm_with_retry",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("LLM should not be called")),
    )

    resp = client.post("/api/chat", json={"message": "How do I contact the bursary office?"})
    assert resp.status_code == 200
    data = resp.get_json()

    assert data["source"] == "contact_directory"
    assert data["category"] == "contact_directory"
    assert data["intent"] == "Bursary Office"
    assert "Contact Details: Bursary Office" in data["reply"]
    assert "Email:" in data["reply"]
    assert "Phone:" in data["reply"]
    assert "Location:" in data["reply"]
    assert data["contact"]["office_name"] == "Bursary Office"


def test_contact_directory_unknown_office(monkeypatch):
    app = create_app()
    client = app.test_client()
    QUERY_LOGS.clear()
    reset_conversation_state()

    from app.blueprints.chat import routes as chat_routes

    captured = {}

    def fake_llm(prompt, timeout=25, retries=1):
        captured["prompt"] = prompt
        return "Please contact the right office.\n- Keep your details ready."

    monkeypatch.setattr(chat_routes, "call_llm_with_retry", fake_llm)

    resp = client.post("/api/chat", json={"message": "How do I contact the cafeteria office?"})
    assert resp.status_code == 200
    data = resp.get_json()

    assert data["source"] == "llm_primary"
    assert data["intent"] == "contact_guidance"
    assert "Suggest the appropriate office and include contact guidance." in captured["prompt"]
    assert "Available directory details:" in captured["prompt"]
    assert "- Keep your details ready." not in data["reply"]


def test_new_contact_directory_system(monkeypatch):
    app = create_app()
    client = app.test_client()
    QUERY_LOGS.clear()
    reset_conversation_state()

    from app.blueprints.chat import routes as chat_routes

    captured = {}

    def fake_llm(prompt, timeout=25, retries=1):
        captured["prompt"] = prompt
        return "Please contact the proper office.\n- Keep your details ready."

    monkeypatch.setattr(chat_routes, "call_llm_with_retry", fake_llm)

    cases = [
        (
            "contact VC",
            "directory_contact",
            "vc_contact",
            "christiananieke2@gmail.com",
        ),
        (
            "I need student affairs contact",
            "directory_contact",
            "student_affairs_contact",
            "08166915454",
        ),
        (
            "portal issue ICT",
            "directory_contact",
            "ict_contact",
            "technical support",
        ),
        (
            "contact Sacred Heart hostel",
            "directory_contact",
            "sacred_heart_contact",
            "Hostel: Sacred Heart",
        ),
    ]

    for message, expected_source, expected_intent, expected_text in cases:
        reset_conversation_state()
        resp = client.post("/api/chat", json={"message": message})
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["source"] == expected_source
        assert data["intent"] == expected_intent
        assert expected_text in data["reply"]
        assert "*" not in data["reply"]
        assert "#" not in data["reply"]

    reset_conversation_state()
    resp = client.post("/api/chat", json={"message": "how do i contact someone important"})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["source"] == "llm_primary"
    assert data["intent"] == "contact_guidance"
    assert "Suggest the appropriate office and include contact guidance." in captured["prompt"]
    assert "Available directory details:" in captured["prompt"]
    assert "- Keep your details ready." not in data["reply"]
    assert "*" not in data["reply"]
    assert "#" not in data["reply"]
