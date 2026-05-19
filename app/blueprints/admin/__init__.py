import os

from flask import Blueprint


def _admin_prefix():
    prefix = str(os.getenv("ADMIN_ROUTE_PREFIX") or "/admin").strip()
    if not prefix.startswith("/"):
        prefix = "/" + prefix
    return prefix.rstrip("/") or "/admin"


admin_bp = Blueprint("admin", __name__, url_prefix=_admin_prefix())

from app.blueprints.admin import routes  # noqa: F401
