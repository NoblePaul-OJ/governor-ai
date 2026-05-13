import copy
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from flask import current_app, has_app_context

from app.services.task_requests_db import list_task_requests


REPO_ROOT = Path(__file__).resolve().parents[2]
KB_PATH = REPO_ROOT / "knowledgeBase.json"
DIRECTORY_PATH = REPO_ROOT / "app" / "data" / "contact_directory.json"
TASK_REQUESTS_JSON_PATH = REPO_ROOT / "app" / "data" / "task_requests_db.json"


def _resolve_path(raw_path, default_path):
    path = Path(raw_path or default_path)
    if path.is_absolute():
        return path
    return REPO_ROOT / path


def _kb_path():
    raw_path = None
    if has_app_context():
        raw_path = current_app.config.get("KNOWLEDGE_BASE_PATH")
    return _resolve_path(raw_path, KB_PATH)


def _directory_path():
    raw_path = None
    if has_app_context():
        raw_path = current_app.config.get("CONTACT_DIRECTORY_PATH")
    return _resolve_path(raw_path, DIRECTORY_PATH)


def _task_requests_path():
    raw_path = None
    if has_app_context():
        raw_path = current_app.config.get("TASK_REQUESTS_JSON_PATH")
    return _resolve_path(raw_path, TASK_REQUESTS_JSON_PATH)


def _read_json(path, default):
    if not path.exists():
        return copy.deepcopy(default)

    try:
        with path.open("r", encoding="utf-8-sig") as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return copy.deepcopy(default)

    return data


def _write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    with tmp_path.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
    tmp_path.replace(path)


def _normalize_question_list(value):
    if isinstance(value, list):
        items = [str(item).strip() for item in value if str(item).strip()]
    else:
        raw = str(value or "").strip()
        if not raw:
            return []
        pieces = re.split(r"[\n\r]+|;\s*|\|\s*|,\s*(?=[A-Z0-9])", raw)
        items = [piece.strip() for piece in pieces if piece.strip()]
    return items


def _slugify(text):
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", (text or "").lower()).strip("_")
    return slug or "custom_entry"


def load_knowledge_base_entries():
    entries = _read_json(_kb_path(), [])
    return entries if isinstance(entries, list) else []


def save_knowledge_base_entries(entries):
    normalized = []
    for entry in entries or []:
        if not isinstance(entry, dict):
            continue
        item = dict(entry)
        questions = _normalize_question_list(item.get("questions") or item.get("question"))
        if questions:
            item["questions"] = questions
        else:
            item["questions"] = []
        item["answer"] = str(item.get("answer", "")).strip()
        if "keywords" in item and isinstance(item["keywords"], list):
            item["keywords"] = [str(keyword).strip() for keyword in item["keywords"] if str(keyword).strip()]
        normalized.append(item)

    _write_json(_kb_path(), normalized)
    return normalized


def add_knowledge_entry(question, answer):
    entries = load_knowledge_base_entries()
    question_text = str(question or "").strip()
    answer_text = str(answer or "").strip()
    intent = _slugify(question_text)
    existing_intents = {str(entry.get("intent", "")).strip() for entry in entries}
    base_intent = intent
    suffix = 2
    while intent in existing_intents:
        intent = f"{base_intent}_{suffix}"
        suffix += 1

    entry = {
        "intent": intent,
        "questions": [question_text] if question_text else [],
        "answer": answer_text,
        "category": "Custom",
        "keywords": [question_text] if question_text else [],
    }
    entries.append(entry)
    save_knowledge_base_entries(entries)
    return entry


def update_knowledge_entry(index, question, answer):
    entries = load_knowledge_base_entries()
    if index < 0 or index >= len(entries):
        raise IndexError("Knowledge base entry not found")

    entry = dict(entries[index])
    entry["questions"] = _normalize_question_list(question)
    entry["answer"] = str(answer or "").strip()
    if not entry.get("intent"):
        base_text = entry["questions"][0] if entry["questions"] else entry.get("answer", "")
        entry["intent"] = _slugify(base_text)
    entries[index] = entry
    save_knowledge_base_entries(entries)
    return entry


def delete_knowledge_entry(index):
    entries = load_knowledge_base_entries()
    if index < 0 or index >= len(entries):
        raise IndexError("Knowledge base entry not found")

    removed = entries.pop(index)
    save_knowledge_base_entries(entries)
    return removed


def load_directory_data():
    data = _read_json(_directory_path(), {})
    return data if isinstance(data, dict) else {}


def save_directory_data(data):
    if not isinstance(data, dict):
        raise ValueError("Directory data must be a mapping")
    _write_json(_directory_path(), data)
    return data


def update_directory_value(section, field, value, subkey=None):
    data = load_directory_data()
    section_data = data.get(section)
    if section_data is None:
        raise KeyError(f"Unknown directory section: {section}")

    normalized_value = str(value or "").strip()

    if subkey:
        if not isinstance(section_data, dict):
            raise KeyError(f"Section '{section}' does not support nested updates")
        nested = section_data.get(subkey)
        if not isinstance(nested, dict):
            raise KeyError(f"Unknown directory item: {subkey}")
        nested[field] = normalized_value
    else:
        if not isinstance(section_data, dict):
            raise KeyError(f"Section '{section}' does not support field updates")
        section_data[field] = normalized_value

    data[section] = section_data
    save_directory_data(data)
    return data


def update_directory_fields(section, fields, subkey=None):
    data = load_directory_data()
    section_data = data.get(section)
    if section_data is None:
        raise KeyError(f"Unknown directory section: {section}")

    if subkey:
        if not isinstance(section_data, dict):
            raise KeyError(f"Section '{section}' does not support nested updates")
        nested = section_data.get(subkey)
        if not isinstance(nested, dict):
            raise KeyError(f"Unknown directory item: {subkey}")
        target = nested
    else:
        if not isinstance(section_data, dict):
            raise KeyError(f"Section '{section}' does not support field updates")
        target = section_data

    for field, value in (fields or {}).items():
        text = str(value or "").strip()
        if field in {"common_issue_types", "common_issues"}:
            items = [part.strip() for part in re.split(r"[\n,;]+", text) if part.strip()]
            target[field] = items
        else:
            target[field] = text

    if subkey:
        section_data[subkey] = target
    else:
        section_data = target

    data[section] = section_data
    save_directory_data(data)
    return data


def _extract_task_request_message(entry):
    payload = entry.get("payload") if isinstance(entry.get("payload"), dict) else {}
    return (
        str(entry.get("user_message") or "").strip()
        or str(payload.get("user_message") or "").strip()
        or str(payload.get("message") or "").strip()
        or str(payload.get("question") or "").strip()
        or str(entry.get("task_label") or "").strip()
    )


def _normalize_task_request(entry, fallback_status="pending"):
    payload = entry.get("payload") if isinstance(entry.get("payload"), dict) else {}
    record_id = entry.get("id")
    try:
        record_id = int(record_id)
    except (TypeError, ValueError):
        pass

    return {
        "id": record_id,
        "task_key": str(entry.get("task_key") or "").strip(),
        "task_label": str(entry.get("task_label") or "").strip(),
        "output_type": str(entry.get("output_type") or "").strip(),
        "user_message": _extract_task_request_message(entry),
        "intent": str(entry.get("intent") or entry.get("task_key") or "").strip(),
        "timestamp": str(entry.get("timestamp") or entry.get("created_at") or "").strip(),
        "created_at": str(entry.get("created_at") or entry.get("timestamp") or "").strip(),
        "status": str(entry.get("status") or fallback_status or "pending").strip() or "pending",
        "payload": payload,
    }


def _merge_task_request_sources(sqlite_entries, json_entries):
    json_index = {}
    for entry in json_entries:
        key = entry.get("id")
        if key is not None:
            json_index[str(key)] = entry

    merged = []
    for entry in sqlite_entries:
        normalized = _normalize_task_request(entry)
        json_entry = json_index.get(str(normalized.get("id")))
        if json_entry:
            normalized.update(
                {
                    "user_message": json_entry.get("user_message") or normalized["user_message"],
                    "intent": json_entry.get("intent") or normalized["intent"],
                    "status": json_entry.get("status") or normalized["status"],
                    "timestamp": json_entry.get("timestamp") or normalized["timestamp"],
                }
            )
            if isinstance(json_entry.get("payload"), dict):
                normalized["payload"] = json_entry["payload"]
        merged.append(normalized)

    for entry in json_entries:
        record_id = entry.get("id")
        if record_id is None:
            continue
        if not any(str(item.get("id")) == str(record_id) for item in merged):
            merged.append(_normalize_task_request(entry))

    merged.sort(key=lambda item: (str(item.get("timestamp") or ""), str(item.get("id") or "")), reverse=True)
    return merged


def load_task_requests(limit=300):
    json_entries = _read_json(_task_requests_path(), [])
    if not isinstance(json_entries, list):
        json_entries = []

    try:
        sqlite_entries = list_task_requests(limit=limit)
    except Exception:
        sqlite_entries = []

    merged = _merge_task_request_sources(sqlite_entries, json_entries)
    if merged and merged != json_entries:
        _write_json(_task_requests_path(), merged)
    elif not _task_requests_path().exists():
        _write_json(_task_requests_path(), merged)

    return merged[: max(1, int(limit))]


def save_task_request_json(record):
    if not isinstance(record, dict):
        return None

    path = _task_requests_path()
    records = _read_json(path, [])
    if not isinstance(records, list):
        records = []

    normalized = _normalize_task_request(record)
    updated = False
    for index, existing in enumerate(records):
        if str(existing.get("id")) == str(normalized.get("id")):
            merged = dict(existing)
            merged.update(normalized)
            if not merged.get("status"):
                merged["status"] = "pending"
            records[index] = merged
            updated = True
            break

    if not updated:
        records.append(normalized)

    _write_json(path, records)
    return normalized


def update_task_request_status(request_id, status):
    path = _task_requests_path()
    records = _read_json(path, [])
    if not isinstance(records, list):
        records = []

    updated = False
    for index, record in enumerate(records):
        if str(record.get("id")) == str(request_id):
            merged = dict(record)
            merged["status"] = str(status or "pending").strip() or "pending"
            records[index] = merged
            updated = True
            break

    if updated:
        _write_json(path, records)
        return True

    return False


def export_task_requests_sqlite_snapshot(limit=300):
    try:
        sqlite_entries = list_task_requests(limit=limit)
    except Exception:
        return []

    snapshot = [_normalize_task_request(entry) for entry in sqlite_entries]
    _write_json(_task_requests_path(), snapshot)
    return snapshot
