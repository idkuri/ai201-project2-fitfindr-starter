"""Tests for persisted style profile."""

from utils.style_profile import load_style_profile, merge_style_hints, update_style_profile


def test_merge_style_hints_avoids_duplicates():
    merged = merge_style_hints("baggy jeans", "baggy jeans and sneakers")

    assert "baggy jeans" in merged
    assert "sneakers" in merged


def test_update_style_profile_persists_hints(tmp_path, monkeypatch):
    profile_file = tmp_path / "style_profile.json"
    monkeypatch.setattr(
        "utils.style_profile._PROFILE_PATH",
        profile_file,
    )

    update_style_profile(style_hints="chunky sneakers", preferred_size="M")
    saved = load_style_profile()

    assert saved["style_hints"] == "chunky sneakers"
    assert saved["preferred_size"] == "M"
    assert saved["updated_at"]
