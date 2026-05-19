from app.services.store import get_user_profile, set_user_profile, update_user


def update_user_memory(user_id, key, value):
    key = str(key or "").strip()
    if not user_id or not key:
        return get_user_profile(user_id)

    if key in {"name", "department", "level", "notes"}:
        updated = update_user(user_id, key, value)
        return {
            item_key: item_value
            for item_key, item_value in updated.items()
            if item_key in {"name", "department", "level", "notes"} and item_value
        }

    profile = get_user_profile(user_id)
    preferences = profile.get("preferences") if isinstance(profile.get("preferences"), dict) else {}
    preferences[key] = value
    profile["preferences"] = preferences
    return set_user_profile(user_id, profile)


def forget_user_memory(user_id, key):
    key = str(key or "").strip()
    if not user_id or not key:
        return get_user_profile(user_id)

    if key in {"name", "department", "level"}:
        update_user(user_id, key, None)
        return get_user_profile(user_id)

    profile = get_user_profile(user_id)
    if key in profile:
        profile.pop(key, None)
        return set_user_profile(user_id, profile)

    preferences = profile.get("preferences") if isinstance(profile.get("preferences"), dict) else {}
    if key in preferences:
        preferences.pop(key, None)
        profile["preferences"] = preferences
        return set_user_profile(user_id, profile)

    return profile
