"""Tests for the FitFindr planning loop."""

from unittest.mock import patch

from agent import _parse_query, run_agent
from tools import suggest_outfit
from utils.data_loader import get_empty_wardrobe, get_example_wardrobe, load_listings


def test_parse_query_extracts_style_hints():
    query = (
        "I'm looking for a vintage graphic tee under $30. "
        "I mostly wear baggy jeans and chunky sneakers. "
        "What's out there and how would I style it?"
    )
    parsed = _parse_query(query)

    assert parsed["description"] == "vintage graphic tee"
    assert parsed["max_price"] == 30.0
    assert parsed["style_hints"] == "baggy jeans and chunky sneakers"


def test_run_agent_passes_style_hints_to_suggest_outfit_with_empty_wardrobe():
    listing = load_listings()[0]
    query = (
        "I'm looking for a vintage graphic tee under $30. "
        "I mostly wear baggy jeans and chunky sneakers. "
        "What's out there and how would I style it?"
    )
    with patch("agent.search_listings", return_value=[listing]):
        with patch("agent.suggest_outfit", return_value="styled") as mock_suggest:
            with patch("agent.create_fit_card", return_value="caption"):
                run_agent(query, get_empty_wardrobe())

    assert mock_suggest.call_args.kwargs["user_style"] == "baggy jeans and chunky sneakers"


def test_run_agent_returns_early_when_search_has_no_results():
    with patch("agent.search_listings", return_value=[]):
        session = run_agent("designer ballgown size XXS under $5", get_example_wardrobe())

    assert session["error"]
    assert session["search_results"] == []
    assert session["selected_item"] is None
    assert session["outfit_suggestion"] is None
    assert session["fit_card"] is None
    assert len(session["plan_log"]) >= 2


def test_run_agent_does_not_call_suggest_when_search_empty():
    with patch("agent.search_listings", return_value=[]) as mock_search:
        with patch("agent.suggest_outfit") as mock_suggest:
            run_agent("designer ballgown size XXS under $5", get_example_wardrobe())

    assert mock_search.call_count > 1
    mock_suggest.assert_not_called()


def test_run_agent_broadens_search_when_initial_search_empty():
    listing = load_listings()[0]
    with patch("agent.search_listings", side_effect=[[], [listing]]) as mock_search:
        with patch("agent.suggest_outfit", return_value="styled"):
            with patch("agent.create_fit_card", return_value="caption"):
                session = run_agent("vintage tee size XXS under $5", get_example_wardrobe())

    assert mock_search.call_count == 2
    assert session["error"] is None
    assert session["search_broadened"] is True
    assert session["search_note"]
    assert session["selected_item"] == listing


def test_run_agent_records_plan_log_on_success():
    listing = load_listings()[0]
    with patch("agent.search_listings", return_value=[listing]):
        with patch("agent.suggest_outfit", return_value="styled"):
            with patch("agent.create_fit_card", return_value="caption"):
                session = run_agent("vintage tee", get_example_wardrobe())

    assert "search_listings attempt 1" in session["plan_log"][0]
    assert any("suggest_outfit" in entry for entry in session["plan_log"])
    assert session["plan_log"][-1].startswith("done")


def test_get_criteria_mismatches_flags_size_and_price():
    from tools import get_criteria_mismatches

    listing = {
        "title": "Y2K Baby Tee",
        "size": "S/M",
        "price": 18.0,
        "style_tags": ["y2k", "graphic tee"],
    }
    mismatches = get_criteria_mismatches(
        listing, "vintage tee", size="XXS", max_price=5.0
    )

    assert any("size" in m.lower() for m in mismatches)
    assert any("price" in m.lower() for m in mismatches)


def test_build_criteria_note_instructs_honest_opening():
    from tools import build_criteria_note

    listing = {
        "title": "Y2K Baby Tee",
        "size": "S/M",
        "price": 18.0,
        "style_tags": ["y2k"],
    }
    note = build_criteria_note(
        listing, "vintage tee", size="XXS", max_price=5.0, search_broadened=True
    )

    assert note is not None
    assert "NOT FULLY MET" in note
    assert "Do not pretend" in note


def test_run_agent_passes_criteria_note_when_search_broadened():
    listing = load_listings()[1]
    with patch("agent.search_listings", side_effect=[[], [listing]]):
        with patch("agent.suggest_outfit", return_value="styled") as mock_suggest:
            with patch("agent.create_fit_card", return_value="caption"):
                session = run_agent("vintage tee size XXS under $5", get_example_wardrobe())

    assert session["search_broadened"] is True
    assert session["criteria_mismatches"]
    assert mock_suggest.call_args.kwargs["criteria_note"] is not None
    assert mock_suggest.call_args.kwargs["alternatives"] == session["search_results"]


@patch("tools._call_groq", return_value="No exact match but try this outfit.")
def test_suggest_outfit_includes_criteria_note_in_prompt(mock_groq):
    from tools import build_criteria_note

    sample_listing = load_listings()[1]
    note = build_criteria_note(
        sample_listing, "vintage tee", size="XXS", max_price=5.0, search_broadened=True
    )
    suggest_outfit(
        sample_listing,
        get_example_wardrobe(),
        alternatives=[sample_listing],
        criteria_note=note,
    )

    prompt = mock_groq.call_args[0][0]
    assert "ORIGINAL REQUEST NOT FULLY MET" in prompt
    assert "Do not pretend" in prompt


def test_run_agent_calls_compare_price_and_check_trends():
    listing = load_listings()[0]
    with patch("agent.search_listings", return_value=[listing]):
        with patch("agent.compare_price", return_value={"summary": "fair price"}) as mock_price:
            with patch("agent.check_trends", return_value={"summary": "trending tags"}) as mock_trends:
                with patch("agent.suggest_outfit", return_value="styled"):
                    with patch("agent.create_fit_card", return_value="caption"):
                        session = run_agent("vintage tee size M", get_example_wardrobe())

    mock_price.assert_called_once_with(listing)
    mock_trends.assert_called_once_with("m")
    assert session["price_analysis"]["summary"] == "fair price"
    assert session["trends"]["summary"] == "trending tags"


def test_run_agent_uses_saved_style_profile_when_query_has_no_hints():
    listing = load_listings()[0]
    with patch("agent.load_style_profile", return_value={"style_hints": "cargo pants and hoodies"}):
        with patch("agent.search_listings", return_value=[listing]):
            with patch("agent.suggest_outfit", return_value="styled") as mock_suggest:
                with patch("agent.create_fit_card", return_value="caption"):
                    run_agent(
                        "vintage tee under $30",
                        get_empty_wardrobe(),
                        remember_style=True,
                    )

    assert mock_suggest.call_args.kwargs["user_style"] == "cargo pants and hoodies"


def test_run_agent_stores_results_and_calls_tools_in_order():
    listing = load_listings()[0]
    with patch("agent.search_listings", return_value=[listing]):
        with patch("agent.suggest_outfit", return_value="Pair with baggy jeans.") as mock_suggest:
            with patch("agent.create_fit_card", return_value="thrifted this on depop") as mock_card:
                session = run_agent("vintage tee under $30", get_example_wardrobe())

    assert session["error"] is None
    assert session["selected_item"] == listing
    assert session["search_results"] == [listing]
    assert session["outfit_suggestion"] == "Pair with baggy jeans."
    assert session["fit_card"] == "thrifted this on depop"
    mock_suggest.assert_called_once()
    call_kwargs = mock_suggest.call_args.kwargs
    assert call_kwargs["new_item"] == listing
    assert call_kwargs["wardrobe"] == session["wardrobe"]
    assert call_kwargs["alternatives"] == [listing]
    mock_card.assert_called_once_with(outfit="Pair with baggy jeans.", new_item=listing)


def test_run_agent_limits_search_results_to_top_k():
    listings = load_listings()[:5]
    with patch("agent.search_listings", return_value=listings):
        with patch("agent.suggest_outfit", return_value="styled"):
            with patch("agent.create_fit_card", return_value="caption"):
                session = run_agent("vintage tee", get_example_wardrobe())

    assert len(session["search_results"]) == 3
    assert session["search_results"] == listings[:3]


@patch("tools._call_groq", return_value="Try the band tee instead.")
def test_suggest_outfit_includes_alternatives_in_prompt(mock_groq):
    sample_listing = load_listings()[0]
    alt = load_listings()[1]
    suggest_outfit(sample_listing, get_example_wardrobe(), alternatives=[sample_listing, alt])

    prompt = mock_groq.call_args[0][0]
    assert "TOP SEARCH RESULTS" in prompt
    assert sample_listing["title"] in prompt
    assert alt["title"] in prompt


def test_is_exact_listing_match():
    from tools import is_exact_listing_match

    listing = {
        "title": "Vintage Band Tee",
        "description": "faded graphic",
        "style_tags": ["vintage", "band tee"],
    }
    assert not is_exact_listing_match(listing, "vintage graphic tee")
    assert is_exact_listing_match(
        {"title": "Graphic Tee — Bootleg", "description": "", "style_tags": ["graphic tee"]},
        "vintage graphic tee",
    )


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
    assert session["outfit_suggestion"] == "Pair with baggy jeans."
    assert session["selected_item"] == listing
