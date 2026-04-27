import secrets

from flask import Flask
from dotenv import load_dotenv

from app.blueprints.admin import admin_bp
from app.blueprints.chat import chat_bp
from app.blueprints.main import main_bp
from app.services.task_requests_db import initialize_query_log_db, initialize_task_db


def create_app():
    load_dotenv()
    app = Flask(__name__, template_folder="../templates", static_folder="../static")
    app.config.from_object("app.config.Config")
    if not app.config.get("SECRET_KEY"):
        app.config["SECRET_KEY"] = secrets.token_hex(32)
    initialize_task_db(app)
    initialize_query_log_db(app)

    app.register_blueprint(main_bp)
    app.register_blueprint(chat_bp)
    app.register_blueprint(admin_bp)
    return app


app = create_app()
