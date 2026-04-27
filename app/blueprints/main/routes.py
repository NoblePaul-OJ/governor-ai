from flask import Blueprint, render_template

main_bp = Blueprint("main", __name__)


@main_bp.get("/")
def landing_page():
    return render_template("chat.html")


@main_bp.get("/chat")
def chat_page():
    return render_template("chat.html")
