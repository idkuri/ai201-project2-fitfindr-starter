"""
agent.py

The FitFindr planning loop. Orchestrates the three tools in response to a
natural language user query, passing state between them via a session dict.

Complete tools.py and test each tool in isolation before implementing this file.

Usage (once implemented):
    from agent import run_agent
    from utils.data_loader import get_example_wardrobe

    result = run_agent(
        query="vintage graphic tee under $30, size M",
        wardrobe=get_example_wardrobe(),
    )
    print(result["fit_card"])
    print(result["error"])   # None on success
"""

import re

from tools import search_listings, suggest_outfit, create_fit_card


# ── session state ─────────────────────────────────────────────────────────────

def _new_session(query: str, wardrobe: dict) -> dict:
    """
    Initialize and return a fresh session dict for one user interaction.

    The session dict is the single source of truth for everything that happens
    during a run — it stores the original query, parsed parameters, tool results,
    and any error that caused early termination.

    You may add fields to this dict as needed for your implementation.
    """
    return {
        "query": query,              # original user query
        "parsed": {},                # extracted description / size / max_price
        "search_results": [],        # list of matching listing dicts
        "selected_item": None,       # top result, passed into suggest_outfit
        "wardrobe": wardrobe,        # user's wardrobe dict
        "outfit_suggestion": None,   # string returned by suggest_outfit
        "fit_card": None,            # string returned by create_fit_card
        "error": None,               # set if the interaction ended early
    }


def _parse_query(query: str) -> dict:
    """Extract description, size, and max_price from a natural language query."""
    text = query.strip()
    lower = text.lower()
    max_price = None
    size = None
    description = text

    price_match = re.search(
        r"(?:under|below|max)\s+\$?\s*(\d+(?:\.\d+)?)", lower
    )
    if not price_match:
        price_match = re.search(r"\$\s*(\d+(?:\.\d+)?)", lower)

    if price_match:
        max_price = float(price_match.group(1))
        description = description[: price_match.start()] + description[price_match.end() :]

    desc_lower = description.lower()
    size_match = re.search(r"size\s*:?\s*(\S+)", desc_lower)
    if size_match:
        size = size_match.group(1).strip(".,;")
        description = description[: size_match.start()] + description[size_match.end() :]
    else:
        standalone = re.search(r"\s([sxl]{1}|xs|xxs|xxl|m|l|s)\s", f" {desc_lower} ")
        if standalone:
            size = standalone.group(1)
            start = standalone.start(1)
            end = standalone.end(1)
            description = description[:start] + description[end:]

    description = re.sub(r"\s+", " ", description).strip(" ,.;")
    if not description:
        description = text

    return {
        "description": description,
        "size": size,
        "max_price": max_price,
    }


def _no_results_message(parsed: dict) -> str:
    """Build a helpful error when search_listings returns nothing."""
    desc = parsed["description"]
    size = parsed.get("size")
    max_price = parsed.get("max_price")

    message = f"No listings matched '{desc}'"
    if size or max_price is not None:
        filters = []
        if size:
            filters.append(f"size {size}")
        if max_price is not None:
            filters.append(f"under ${max_price:g}")
        message += " in " + " ".join(filters)

    tips = ["Try broadening your search"]
    if max_price is not None:
        tips.append(f"raising your budget above ${max_price:g}")
    if size:
        tips.append("removing the size filter")
    message += ". " + ", ".join(tips) + "."
    return message


def _fit_card_failure_message(selected_item: dict) -> str:
    """Build an error when create_fit_card fails after a listing was found."""
    title = selected_item["title"]
    price = selected_item["price"]
    platform = selected_item["platform"]
    return (
        f"Found {title} (${price:g} on {platform}) but couldn't generate a fit card caption. "
        "Try your search again, or ask how to style this piece and we'll skip the caption."
    )


def _is_fit_card_failure(fit_card: str) -> bool:
    """True if create_fit_card returned empty output or its error string."""
    if not fit_card or not fit_card.strip():
        return True
    return fit_card.strip().startswith("Could not generate a fit card")


# ── planning loop ─────────────────────────────────────────────────────────────

def run_agent(query: str, wardrobe: dict) -> dict:
    """
    Main agent entry point. Runs the FitFindr planning loop for a single
    user interaction and returns the completed session dict.

    Args:
        query:    Natural language user request
                  (e.g., "vintage graphic tee under $30, size M")
        wardrobe: User's wardrobe dict — use get_example_wardrobe() or
                  get_empty_wardrobe() from utils/data_loader.py

    Returns:
        The session dict after the interaction completes. Check session["error"]
        first — if it is not None, the interaction ended early and the other
        output fields (outfit_suggestion, fit_card) will be None.

    TODO — implement this function using the planning loop you designed in planning.md:

        Step 1: Initialize the session with _new_session().

        Step 2: Parse the user's query to extract a description, size, and
                max_price. You can use regex, string splitting, or ask the LLM
                to parse it — document your choice in planning.md.
                Store the result in session["parsed"].

        Step 3: Call search_listings() with the parsed parameters.
                Store results in session["search_results"].
                If no results: set session["error"] to a helpful message and
                return the session early. Do NOT proceed to suggest_outfit
                with empty input.

        Step 4: Select the item to use (e.g., the top result).
                Store it in session["selected_item"].

        Step 5: Call suggest_outfit() with the selected item and wardrobe.
                Store the result in session["outfit_suggestion"].

        Step 6: Call create_fit_card() with the outfit suggestion and selected item.
                Store the result in session["fit_card"].

        Step 7: Return the session.

    Before writing code, complete the Planning Loop and State Management sections
    of planning.md — your implementation should match what you described there.
    """
    session = _new_session(query, wardrobe)

    session["parsed"] = _parse_query(query)

    results = search_listings(
        description=session["parsed"]["description"],
        size=session["parsed"]["size"],
        max_price=session["parsed"]["max_price"],
    )
    session["search_results"] = results

    if not results:
        session["error"] = _no_results_message(session["parsed"])
        return session

    session["selected_item"] = results[0]

    outfit = suggest_outfit(
        new_item=session["selected_item"],
        wardrobe=session["wardrobe"],
    )
    session["outfit_suggestion"] = outfit

    if not outfit or not outfit.strip():
        session["error"] = "Couldn't generate a styling suggestion. Try again."
        return session

    fit_card = create_fit_card(
        outfit=session["outfit_suggestion"],
        new_item=session["selected_item"],
    )
    session["fit_card"] = fit_card

    if _is_fit_card_failure(fit_card):
        session["error"] = _fit_card_failure_message(session["selected_item"])
        session["fit_card"] = None
        return session

    return session


# ── CLI test ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    from utils.data_loader import get_example_wardrobe, get_empty_wardrobe

    print("=== Happy path: graphic tee ===\n")
    session = run_agent(
        query="looking for a vintage graphic tee under $30",
        wardrobe=get_example_wardrobe(),
    )
    if session["error"]:
        print(f"Error: {session['error']}")
    else:
        print(f"Found: {session['selected_item']['title']}")
        print(f"\nOutfit: {session['outfit_suggestion']}")
        print(f"\nFit card: {session['fit_card']}")

    print("\n\n=== No-results path ===\n")
    session2 = run_agent(
        query="designer ballgown size XXS under $5",
        wardrobe=get_example_wardrobe(),
    )
    print(f"Error message: {session2['error']}")
