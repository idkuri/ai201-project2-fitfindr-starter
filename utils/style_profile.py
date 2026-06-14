"""Persist user style preferences across FitFindr sessions."""

import json
from datetime import datetime, timezone
from pathlib import Path

_PROFILE_PATH = Path(__file__).resolve().parent.parent / "data" / "style_profile.json"


def load_style_profile() -> dict:
    """Load saved style preferences, or return an empty profile."""
    if not _PROFILE_PATH.exists():
        return {"style_hints": None, "preferred_size": None, "updated_at": None}

    with open(_PROFILE_PATH, encoding="utf-8") as handle:
        data = json.load(handle)

    return {
        "style_hints": data.get("style_hints"),
        "preferred_size": data.get("preferred_size"),
        "updated_at": data.get("updated_at"),
    }


def save_style_profile(profile: dict) -> None:
    """Write style preferences to disk."""
    payload = {
        "style_hints": profile.get("style_hints"),
        "preferred_size": profile.get("preferred_size"),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    _PROFILE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(_PROFILE_PATH, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)


def merge_style_hints(existing: str | None, new: str) -> str:
    """Combine saved and newly stated style preferences without duplication."""
    new = new.strip()
    if not new:
        return existing or ""
    if not existing:
        return new
    if new.lower() in existing.lower():
        return existing
    return f"{existing}; {new}"


def update_style_profile(
    style_hints: str | None = None,
    preferred_size: str | None = None,
) -> dict:
    """Merge new hints into the saved profile and persist."""
    profile = load_style_profile()

    if style_hints:
        profile["style_hints"] = merge_style_hints(profile.get("style_hints"), style_hints)
    if preferred_size:
        profile["preferred_size"] = preferred_size

    save_style_profile(profile)
    return profile
