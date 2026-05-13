from flask import current_app, flash, jsonify, redirect, render_template, request, url_for

from app.services.admin_store import (
    add_knowledge_entry,
    delete_knowledge_entry,
    load_directory_data,
    load_knowledge_base_entries,
    load_task_requests,
    update_directory_fields,
    update_knowledge_entry,
    update_task_request_status,
)
from app.services.rule_engine import get_rules, update_rules
from app.services.store import QUERY_LOGS, get_stats, get_system_insights
from app.services.task_requests_db import list_chat_logs

from . import admin_bp


@admin_bp.route("/", methods=["GET", "POST"])
def dashboard():
    if request.method == "POST":
        action = (request.form.get("action") or "").strip()
        try:
            if action == "kb_add":
                question = request.form.get("question", "")
                answer = request.form.get("answer", "")
                add_knowledge_entry(question, answer)
                flash("Knowledge base entry added.", "success")
            elif action == "kb_update":
                index = int(request.form.get("index", "-1"))
                question = request.form.get("question", "")
                answer = request.form.get("answer", "")
                update_knowledge_entry(index, question, answer)
                flash("Knowledge base entry updated.", "success")
            elif action == "kb_delete":
                index = int(request.form.get("index", "-1"))
                delete_knowledge_entry(index)
                flash("Knowledge base entry deleted.", "success")
            elif action == "directory_update":
                section = request.form.get("section", "")
                subkey = request.form.get("subkey") or None
                fields = {
                    key: request.form.get(key, "")
                    for key in ("phone", "whatsapp", "email", "office", "office_hours", "preferred_contact_method", "common_issue_types", "common_issues", "description", "note")
                    if key in request.form
                }
                update_directory_fields(section, fields, subkey=subkey)
                flash("Directory entry updated.", "success")
            elif action == "request_resolved":
                request_id = request.form.get("request_id", "")
                if update_task_request_status(request_id, "resolved"):
                    flash("Task request marked as resolved.", "success")
                else:
                    flash("Could not update that task request.", "error")
            else:
                flash("Unknown admin action.", "error")
        except (ValueError, IndexError, KeyError):
            flash("That change could not be saved. Please check the fields and try again.", "error")

        return redirect(url_for("admin.dashboard"))

    stats = get_stats()
    insights = get_system_insights(limit=10)
    from app.services.store import keyword_counts

    keyword_stats = keyword_counts(top_n=12)

    return render_template(
        "admin/dashboard.html",
        stats=stats,
        keyword_stats=keyword_stats,
        insights=insights,
        kb_entries=load_knowledge_base_entries(),
        directory_data=load_directory_data(),
        task_requests=load_task_requests(limit=300),
    )


@admin_bp.get("/logs")
def view_logs():
    logs = list_chat_logs(limit=200)
    if not logs:
        logs = QUERY_LOGS[-200:]
    return render_template("admin/logs.html", logs=logs)


@admin_bp.get("/intents")
def view_intents():
    rules = get_rules()
    return render_template("admin/intents.html", rules=rules)


@admin_bp.post("/intents")
def update_intents():
    data = request.get_json(silent=True)
    if data is None:
        raw = request.form.get("rules", "")
        try:
            import json

            data = json.loads(raw)
        except Exception:
            data = None

    if not isinstance(data, dict):
        flash("Invalid payload, please submit a JSON object.", "error")
        return redirect(url_for("admin.view_intents"))

    good = True
    for key, val in data.items():
        if not isinstance(val, dict) or "response" not in val:
            good = False
            break

    if not good:
        flash("Rules must be a mapping from intent keys to objects containing at least a 'response'.", "error")
        return redirect(url_for("admin.view_intents"))

    update_rules(data)
    flash("Intent rules updated successfully.", "success")
    return redirect(url_for("admin.view_intents"))


@admin_bp.get("/intents.json")
def intents_api():
    rules = get_rules()
    return jsonify(rules)


@admin_bp.get("/task-requests")
def view_task_requests():
    requests = load_task_requests(limit=300)
    db_enabled = bool(current_app.config.get("TASK_DB_ENABLED", False) or requests)
    return render_template(
        "admin/task_requests.html",
        requests=requests,
        db_enabled=db_enabled,
    )


@admin_bp.get("/task-requests.json")
def task_requests_api():
    requests = load_task_requests(limit=300)
    return jsonify(
        {
            "enabled": bool(current_app.config.get("TASK_DB_ENABLED", False) or requests),
            "count": len(requests),
            "requests": requests,
        }
    )


@admin_bp.get("/insights")
def insights_page():
    return jsonify(get_system_insights(limit=10))
