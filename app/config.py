import os


class Config:
    SECRET_KEY = os.getenv("SECRET_KEY") or os.getenv("FLASK_SECRET_KEY")
    FALLBACK_CONTACT = os.getenv("FALLBACK_CONTACT", "Student Affairs Office")
    OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-5.2")
    OPENAI_TIMEOUT = int(os.getenv("OPENAI_TIMEOUT", "25"))
    KB_LLM_THRESHOLD = float(os.getenv("KB_LLM_THRESHOLD", "0.6"))
    TASK_DB_ENABLED = os.getenv("TASK_DB_ENABLED", "0").strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
    }
    TASK_DB_PATH = os.getenv("TASK_DB_PATH", "task_requests.db")
    QUERY_LOG_DB_ENABLED = os.getenv("QUERY_LOG_DB_ENABLED", "1").strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
    }
    QUERY_LOG_DB_PATH = os.getenv("QUERY_LOG_DB_PATH", "chat_query_logs.db")
