import json
import os

BASE_DIR = os.path.dirname(os.path.dirname(__file__))
DATA_PATH = os.path.join(BASE_DIR, "data", "contact_directory.json")


def load_directory():
    try:
        with open(DATA_PATH, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except FileNotFoundError:
        return {}


def get_vc_contact():
    data = load_directory()
    return data.get("vc", {})


def get_student_affairs():
    data = load_directory()
    return data.get("student_affairs", {})


def get_ict():
    data = load_directory()
    return data.get("ict", {})


def get_hostel(name=None):
    data = load_directory()
    hostels = data.get("hostels", {})

    if name:
        return hostels.get(name.lower(), {})

    return hostels
