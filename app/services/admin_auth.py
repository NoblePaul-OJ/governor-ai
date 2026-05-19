import hmac

from flask import current_app, jsonify, redirect, request, session, url_for


ADMIN_SESSION_KEY = "_governor_admin_authenticated"


def get_admin_secret():
    return str(current_app.config.get("ADMIN_ACCESS_KEY") or "").strip()


def is_admin_authenticated():
    return bool(session.get(ADMIN_SESSION_KEY))


def authenticate_admin_key(value):
    secret = get_admin_secret()
    candidate = str(value or "").strip()
    if not secret or not candidate:
        return False

    if hmac.compare_digest(candidate, secret):
        session[ADMIN_SESSION_KEY] = True
        session.modified = True
        return True

    return False


def clear_admin_session():
    session.pop(ADMIN_SESSION_KEY, None)
    session.modified = True


def admin_key_from_request():
    return (
        request.headers.get("X-Admin-Key")
        or request.args.get("admin_key")
        or request.form.get("admin_key")
        or request.form.get("password")
    )


def wants_json_response():
    if request.path.endswith(".json") or request.path.startswith("/api/"):
        return True
    best = request.accept_mimetypes.best_match(["application/json", "text/html"])
    if not best:
        return False
    return best == "application/json" and request.accept_mimetypes[best] > request.accept_mimetypes["text/html"]


def require_admin_access():
    if is_admin_authenticated() or authenticate_admin_key(admin_key_from_request()):
        return None

    if wants_json_response():
        return jsonify({"error": "Admin access required"}), 401

    next_url = request.full_path if request.query_string else request.path
    return redirect(url_for("admin.login", next=next_url))
