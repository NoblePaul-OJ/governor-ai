import json

from app import create_app
from app.services import admin_store
from app.services.task_requests_db import save_task_request


def test_admin_dashboard_crud(monkeypatch, tmp_path):
    kb_path = tmp_path / "knowledgeBase.json"
    directory_path = tmp_path / "contact_directory.json"
    task_requests_path = tmp_path / "task_requests_db.json"

    kb_path.write_text(
        json.dumps(
            [
                {
                    "intent": "welcome",
                    "questions": ["Hello"],
                    "answer": "Hello there.",
                    "category": "General",
                }
            ],
            indent=2,
        ),
        encoding="utf-8",
    )

    directory_path.write_text(
        json.dumps(
            {
                "vc": {"phone": "", "email": "", "office": ""},
                "student_affairs": {"phone": "", "email": "", "office": ""},
                "ict": {"phone": "", "email": "", "office": ""},
                "hostels": {"sacred_heart": {"phone": "", "office": ""}},
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    task_requests_path.write_text(
        json.dumps(
            [
                {
                    "id": 1,
                    "task_key": "vc_appointment",
                    "task_label": "VC Appointment",
                    "output_type": "appointment_letter",
                    "user_message": "I want to meet the VC",
                    "intent": "vc_appointment",
                    "timestamp": "2026-05-04T00:00:00+00:00",
                    "status": "pending",
                    "payload": {},
                }
            ],
            indent=2,
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(admin_store, "KB_PATH", kb_path)
    monkeypatch.setattr(admin_store, "DIRECTORY_PATH", directory_path)
    monkeypatch.setattr(admin_store, "TASK_REQUESTS_JSON_PATH", task_requests_path)

    app = create_app()
    app.config["ADMIN_ACCESS_KEY"] = "test-admin-key"
    app.config["TASK_REQUESTS_JSON_PATH"] = str(task_requests_path)
    client = app.test_client()
    admin_headers = {"X-Admin-Key": "test-admin-key"}

    resp = client.get("/admin/")
    assert resp.status_code == 302

    resp = client.get("/admin/", headers=admin_headers)
    assert resp.status_code == 200
    assert b"Knowledge Base Manager" in resp.data
    assert b"Contact Directory Manager" in resp.data
    assert b"Task Requests Viewer" in resp.data

    resp = client.post(
        "/admin/",
        data={
            "action": "kb_add",
            "question": "Where is the ICT office?",
            "answer": "Go to the ICT support desk.",
        },
        headers=admin_headers,
        follow_redirects=True,
    )
    assert resp.status_code == 200

    kb_data = json.loads(kb_path.read_text(encoding="utf-8"))
    assert len(kb_data) == 2
    assert kb_data[-1]["questions"] == ["Where is the ICT office?"]
    assert kb_data[-1]["answer"] == "Go to the ICT support desk."

    resp = client.post(
        "/admin/",
        data={
            "action": "kb_update",
            "index": "0",
            "question": "Hello there",
            "answer": "Welcome back.",
        },
        headers=admin_headers,
        follow_redirects=True,
    )
    assert resp.status_code == 200

    kb_data = json.loads(kb_path.read_text(encoding="utf-8"))
    assert kb_data[0]["questions"] == ["Hello there"]
    assert kb_data[0]["answer"] == "Welcome back."

    resp = client.post(
        "/admin/",
        data={
            "action": "kb_delete",
            "index": "1",
        },
        headers=admin_headers,
        follow_redirects=True,
    )
    assert resp.status_code == 200

    kb_data = json.loads(kb_path.read_text(encoding="utf-8"))
    assert len(kb_data) == 1
    assert kb_data[0]["answer"] == "Welcome back."

    resp = client.post(
        "/admin/",
        data={
            "action": "directory_update",
            "section": "vc",
            "phone": "08000000000",
            "email": "vc@example.com",
            "office": "Main Campus",
        },
        headers=admin_headers,
        follow_redirects=True,
    )
    assert resp.status_code == 200

    directory_data = json.loads(directory_path.read_text(encoding="utf-8"))
    assert directory_data["vc"]["phone"] == "08000000000"
    assert directory_data["vc"]["email"] == "vc@example.com"
    assert directory_data["vc"]["office"] == "Main Campus"

    resp = client.post(
        "/admin/",
        data={
            "action": "request_resolved",
            "request_id": "1",
        },
        headers=admin_headers,
        follow_redirects=True,
    )
    assert resp.status_code == 200

    task_requests_data = json.loads(task_requests_path.read_text(encoding="utf-8"))
    assert task_requests_data[0]["status"] == "resolved"


def test_task_request_mirrors_to_json(monkeypatch, tmp_path):
    app = create_app()
    app.config["TASK_DB_ENABLED"] = True
    app.config["TASK_DB_PATH"] = str(tmp_path / "task_requests_test.db")
    app.config["TASK_REQUESTS_JSON_PATH"] = str(tmp_path / "task_requests_db.json")

    with app.app_context():
        request_id = save_task_request(
            task_key="vc_appointment",
            task_label="VC Appointment",
            output_type="appointment_letter",
            payload={"name": "Ada Lovelace"},
            user_message="I want to meet the VC",
            intent="vc_appointment",
        )

    assert request_id == 1

    data = json.loads((tmp_path / "task_requests_db.json").read_text(encoding="utf-8"))
    assert data[0]["id"] == 1
    assert data[0]["user_message"] == "I want to meet the VC"
    assert data[0]["intent"] == "vc_appointment"
    assert data[0]["status"] == "pending"
