"""Tests for FitFindr tools."""

from unittest.mock import patch

import pytest

from tools import create_fit_card, search_listings, suggest_outfit
from utils.data_loader import get_empty_wardrobe, get_example_wardrobe, load_listings


@pytest.fixture
def sample_listing() -> dict:
    return load_listings()[0]


# ── search_listings ───────────────────────────────────────────────────────────


def test_search_listings_returns_empty_list_when_no_match():
    """Failure mode: no results — returns [] without raising."""
    results = search_listings("designer ballgown", size="XXS", max_price=5.0)
    assert results == []


def test_search_listings_returns_matching_listings_sorted_by_relevance():
    results = search_listings("flannel")
    assert len(results) >= 1
    assert "flannel" in results[0]["title"].lower() or any(
        "flannel" in tag.lower() for tag in results[0]["style_tags"]
    )


def test_search_listings_respects_max_price_and_size():
    results = search_listings("vintage", size="M", max_price=30.0)
    for listing in results:
        assert listing["price"] <= 30.0
        assert "m" in listing["size"].lower()


def test_search_listings_listing_shape():
    results = search_listings("denim")
    assert results
    listing = results[0]
    for field in (
        "id",
        "title",
        "description",
        "category",
        "style_tags",
        "size",
        "condition",
        "price",
        "colors",
        "brand",
        "platform",
    ):
        assert field in listing


# ── suggest_outfit ────────────────────────────────────────────────────────────


@patch("tools._call_groq", return_value="Pair with wide-leg denim and chunky sneakers.")
def test_suggest_outfit_empty_wardrobe_does_not_crash(mock_groq, sample_listing):
    """Failure mode: empty wardrobe — returns general advice, no crash."""
    result = suggest_outfit(sample_listing, get_empty_wardrobe())

    assert isinstance(result, str)
    assert result.strip()
    mock_groq.assert_called_once()
    prompt = mock_groq.call_args[0][0]
    assert "has not added any wardrobe pieces yet" in prompt
    assert "USER'S WARDROBE" not in prompt


@patch("tools._call_groq", return_value="Pair with your baggy straight-leg jeans and chunky white sneakers.")
def test_suggest_outfit_with_wardrobe_uses_wardrobe_prompt(mock_groq, sample_listing):
    result = suggest_outfit(sample_listing, get_example_wardrobe())

    assert result.strip()
    prompt = mock_groq.call_args[0][0]
    assert "USER'S WARDROBE" in prompt
    assert "Baggy straight-leg jeans" in prompt


# ── create_fit_card ───────────────────────────────────────────────────────────


def test_create_fit_card_empty_outfit_returns_error_message(sample_listing):
    """Failure mode: missing outfit — error string, no exception."""
    result = create_fit_card("", sample_listing)

    assert "Could not generate a fit card" in result
    assert sample_listing["title"] in result
    assert sample_listing["platform"] in result


def test_create_fit_card_whitespace_outfit_returns_error_message(sample_listing):
    result = create_fit_card("   ", sample_listing)

    assert "Could not generate a fit card" in result
    assert "outfit suggestion was missing" in result


@patch("tools._call_groq", return_value="thrifted this tee off depop for $18, full fit in my stories")
def test_create_fit_card_valid_outfit_returns_caption(mock_groq, sample_listing):
    outfit = "Pair with baggy jeans and chunky sneakers."
    result = create_fit_card(outfit, sample_listing)

    assert result.strip()
    mock_groq.assert_called_once()
    prompt = mock_groq.call_args[0][0]
    assert outfit in prompt
    assert sample_listing["title"] in prompt
    assert mock_groq.call_args[1]["temperature"] == 0.9
