"""Tests for the FitFindr planning loop."""

from unittest.mock import patch

from agent import run_agent
from utils.data_loader import get_example_wardrobe, load_listings


def test_run_agent_returns_early_when_search_has_no_results():
    with patch("agent.search_listings", return_value=[]):
        session = run_agent("designer ballgown size XXS under $5", get_example_wardrobe())

    assert session["error"]
    assert session["search_results"] == []
    assert session["selected_item"] is None
    assert session["outfit_suggestion"] is None
    assert session["fit_card"] is None


def test_run_agent_does_not_call_suggest_when_search_empty():
    with patch("agent.search_listings", return_value=[]) as mock_search:
        with patch("agent.suggest_outfit") as mock_suggest:
            run_agent("nothing matches", get_example_wardrobe())

    mock_search.assert_called_once()
    mock_suggest.assert_not_called()


def test_run_agent_stores_results_and_calls_tools_in_order():
    listing = load_listings()[0]
    with patch("agent.search_listings", return_value=[listing]):
        with patch("agent.suggest_outfit", return_value="Pair with baggy jeans.") as mock_suggest:
            with patch("agent.create_fit_card", return_value="thrifted this on depop") as mock_card:
                session = run_agent("vintage tee under $30", get_example_wardrobe())

    assert session["error"] is None
    assert session["selected_item"] == listing
    assert session["outfit_suggestion"] == "Pair with baggy jeans."
    assert session["fit_card"] == "thrifted this on depop"
    mock_suggest.assert_called_once_with(new_item=listing, wardrobe=session["wardrobe"])
    mock_card.assert_called_once_with(outfit="Pair with baggy jeans.", new_item=listing)


def test_run_agent_returns_early_when_outfit_empty():
    listing = load_listings()[0]
    with patch("agent.search_listings", return_value=[listing]):
        with patch("agent.suggest_outfit", return_value=""):
            with patch("agent.create_fit_card") as mock_card:
                session = run_agent("vintage tee", get_example_wardrobe())

    assert session["error"] == "Couldn't generate a styling suggestion. Try again."
    assert session["selected_item"] == listing
    assert session["fit_card"] is None
    mock_card.assert_not_called()


def test_run_agent_returns_early_when_fit_card_fails():
    listing = load_listings()[0]
    with patch("agent.search_listings", return_value=[listing]):
        with patch("agent.suggest_outfit", return_value="Pair with baggy jeans."):
            with patch("agent.create_fit_card", return_value=""):
                session = run_agent("vintage tee", get_example_wardrobe())

    assert session["error"]
    assert listing["title"] in session["error"]
    assert session["fit_card"] is None
