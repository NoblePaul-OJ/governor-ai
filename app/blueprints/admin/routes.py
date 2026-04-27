from flask import current_app, jsonify, render_template, request, redirect, url_for, flash

from app.services.rule_engine import get_rules, update_rules
from app.services.store import QUERY_LOGS, get_stats, get_system_insights
from app.services.task_requests_db import list_chat_logs, list_task_requests

from . import admin_bp


@admin_bp.get("/")
def dashboard():
    stats = get_stats()
    insights = get_system_insights(limit=10)
    # gather keyword frequency for analysis
    from app.services.store import keyword_counts

    keyword_stats = keyword_counts(top_n=12)
    return render_template(
        "admin/dashboard.html",
        stats=stats,
        keyword_stats=keyword_stats,
        insights=insights,
    )


@admin_bp.get("/logs")
def view_logs():
    # show a simple table of the most recent 200 entries
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
    # expecting JSON body containing the full rules dictionary
    data = request.get_json(silent=True)
    # legacy fallback: textarea submission from HTML form
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

    # Basic validation: each value should be dict with required keys
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
    # helper api for external tooling
    rules = get_rules()
    return jsonify(rules)


@admin_bp.get("/task-requests")
def view_task_requests():
    requests = list_task_requests(limit=300)
    db_enabled = bool(current_app.config.get("TASK_DB_ENABLED", False))
    return render_template(
        "admin/task_requests.html",
        requests=requests,
        db_enabled=db_enabled,
    )


@admin_bp.get("/task-requests.json")
def task_requests_api():
    requests = list_task_requests(limit=300)
    return jsonify(
        {
            "enabled": bool(current_app.config.get("TASK_DB_ENABLED", False)),
            "count": len(requests),
            "requests": requests,
        }
    )


@admin_bp.get("/insights")
def insights_page():
    return jsonify(get_system_insights(limit=10))
