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

from tools import (
    TOP_K,
    _significant_keywords,
    build_criteria_note,
    check_trends,
    compare_price,
    create_fit_card,
    get_criteria_mismatches,
    is_exact_listing_match,
    search_listings,
    suggest_outfit,
)
from utils.style_profile import load_style_profile, update_style_profile


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
        "search_results": [],        # top K matching listing dicts
        "selected_item": None,       # top result, passed into suggest_outfit
        "exact_match": None,         # whether top result matches all search keywords
        "wardrobe": wardrobe,        # user's wardrobe dict
        "outfit_suggestion": None,   # string returned by suggest_outfit
        "fit_card": None,            # string returned by create_fit_card
        "error": None,               # set if the interaction ended early
        "plan_log": [],              # which tools were called and why
        "search_broadened": False,   # True when a fallback search found results
        "price_analysis": None,      # compare_price result for top pick
        "trends": None,              # check_trends result for user's size
        "criteria_mismatches": [],   # unmet filters for the top pick
        "style_profile_saved": False,
    }


def _extract_style_hints(query: str) -> str | None:
    """Pull what the user says they usually wear from a natural language query."""
    patterns = [
        r"I mostly wear\s+(.+?)(?:\.\s|\.\s*$|\s+what'?s|\s+how would|\s+how do)",
        r"I usually wear\s+(.+?)(?:\.\s|\.\s*$|\s+what'?s|\s+how would|\s+how do)",
        r"I typically wear\s+(.+?)(?:\.\s|\.\s*$|\s+what'?s|\s+how would|\s+how do)",
        r"my style is\s+(.+?)(?:\.\s|\.\s*$|\s+what'?s|\s+how would|\s+how do)",
    ]
    for pattern in patterns:
        match = re.search(pattern, query, re.IGNORECASE)
        if match:
            return match.group(1).strip(" .,;")
    return None


def _extract_item_description(text: str) -> str:
    """Pull the core item phrase from a natural language query."""
    match = re.search(
        r"(?:looking for|searching for|want)\s+(?:a|an|the)?\s*(.+?)"
        r"(?:\.\s|\s+I mostly|\s+what'?s out there|\s+how would|$)",
        text,
        re.IGNORECASE,
    )
    if match:
        return match.group(1).strip(" .,;")
    return text


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
    description = _extract_item_description(description)
    if not description:
        description = text

    return {
        "description": description,
        "size": size,
        "max_price": max_price,
        "style_hints": _extract_style_hints(text),
    }


def _search_strategies(parsed: dict) -> list[dict]:
    """Ordered search attempts from strict filters to progressively broader ones."""
    desc = parsed["description"]
    size = parsed.get("size")
    max_price = parsed.get("max_price")
    strategies: list[dict] = []
    seen: set[tuple] = set()

    def add(description: str, attempt_size, attempt_price, note: str) -> None:
        key = (description, attempt_size, attempt_price)
        if key in seen:
            return
        seen.add(key)
        strategies.append(
            {
                "description": description,
                "size": attempt_size,
                "max_price": attempt_price,
                "note": note,
            }
        )

    add(desc, size, max_price, "original filters")
    add(desc, None, max_price, "dropped size filter")

    if max_price is not None:
        add(desc, None, max_price * 1.5, "raised budget 50% and dropped size")
        add(desc, None, None, "dropped size and price filter")

    sig_keywords = _significant_keywords(desc)
    broad_desc = " ".join(sig_keywords[:3]) if sig_keywords else desc
    if broad_desc != desc:
        add(
            broad_desc,
            None,
            max_price * 1.5 if max_price is not None else None,
            "broader keywords with relaxed filters",
        )

    return strategies


def _broadened_search_note(strategy: dict) -> str:
    """Explain to the user how the agent relaxed their search."""
    parts = [strategy["note"]]
    if strategy["size"] is None and strategy.get("note") != "original filters":
        parts.append("no size filter")
    if strategy["max_price"] is None:
        parts.append("no price cap")
    elif "raised budget" in strategy["note"]:
        parts.append(f"budget up to ${strategy['max_price']:g}")
    return "Broadened search: " + ", ".join(parts) + "."


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
    message += " The agent already tried relaxing your filters automatically."
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

def _resolve_user_style(parsed: dict, remember_style: bool) -> str | None:
    """Use style hints from the query, or fall back to a saved profile."""
    if parsed.get("style_hints"):
        return parsed["style_hints"]
    if remember_style:
        profile = load_style_profile()
        saved = profile.get("style_hints")
        if saved:
            parsed["style_from_profile"] = True
        return saved
    return None


def run_agent(query: str, wardrobe: dict, remember_style: bool = False) -> dict:
    """
    Main agent entry point. Runs the FitFindr planning loop for a single
    user interaction and returns the completed session dict.

    The loop picks the next tool based on what the previous step returned —
    it is not a blind fixed sequence. Search retries with broader filters
    when nothing matches; styling and fit-card steps run only after a listing
    is found; each step can exit early on failure.
    """
    session = _new_session(query, wardrobe)
    session["parsed"] = _parse_query(query)
    session["parsed"]["effective_style"] = _resolve_user_style(
        session["parsed"], remember_style
    )

    step = "search"
    search_attempt = 0
    search_strategies = _search_strategies(session["parsed"])

    while step != "done":
        if step == "search":
            if search_attempt >= len(search_strategies):
                session["plan_log"].append("search exhausted — no listings found")
                session["error"] = _no_results_message(session["parsed"])
                return session

            strategy = search_strategies[search_attempt]
            session["plan_log"].append(
                f"search_listings attempt {search_attempt + 1}: {strategy['note']}"
            )

            results = search_listings(
                description=strategy["description"],
                size=strategy["size"],
                max_price=strategy["max_price"],
            )

            if not results:
                search_attempt += 1
                continue

            session["search_results"] = results[:TOP_K]
            session["search_broadened"] = search_attempt > 0
            if session["search_broadened"]:
                session["search_note"] = _broadened_search_note(strategy)
            step = "price_check"

        elif step == "price_check":
            session["selected_item"] = session["search_results"][0]
            session["price_analysis"] = compare_price(session["selected_item"])
            session["trends"] = check_trends(session["parsed"].get("size"))
            session["plan_log"].append("compare_price on top pick")
            session["plan_log"].append(
                f"check_trends for size bucket {session['trends'].get('size_bucket', 'default')}"
            )
            step = "suggest"

        elif step == "suggest":
            parsed = session["parsed"]
            session["exact_match"] = is_exact_listing_match(
                session["selected_item"],
                parsed["description"],
            )
            session["criteria_mismatches"] = get_criteria_mismatches(
                session["selected_item"],
                parsed["description"],
                parsed.get("size"),
                parsed.get("max_price"),
            )
            if session["search_broadened"]:
                session["criteria_mismatches"].insert(
                    0,
                    "No listings matched your exact filters (search was broadened)",
                )

            criteria_note = build_criteria_note(
                session["selected_item"],
                parsed["description"],
                parsed.get("size"),
                parsed.get("max_price"),
                search_broadened=session["search_broadened"],
            )
            needs_alternatives = bool(criteria_note) or not session["exact_match"]
            alternatives = session["search_results"] if needs_alternatives else None

            if criteria_note:
                session["plan_log"].append(
                    "suggest_outfit with criteria mismatch note + alternatives"
                )
            elif not session["exact_match"]:
                session["plan_log"].append(
                    "suggest_outfit with top-K alternatives (no exact match)"
                )
            else:
                session["plan_log"].append("suggest_outfit with top pick")

            outfit = suggest_outfit(
                new_item=session["selected_item"],
                wardrobe=session["wardrobe"],
                alternatives=alternatives,
                user_style=parsed.get("effective_style"),
                trend_context=(session.get("trends") or {}).get("summary"),
                criteria_note=criteria_note,
            )
            session["outfit_suggestion"] = outfit

            if not outfit or not outfit.strip():
                session["plan_log"].append("suggest_outfit returned empty — stopping")
                session["error"] = "Couldn't generate a styling suggestion. Try again."
                return session

            step = "fit_card"

        elif step == "fit_card":
            session["plan_log"].append("create_fit_card")

            fit_card = create_fit_card(
                outfit=session["outfit_suggestion"],
                new_item=session["selected_item"],
            )
            session["fit_card"] = fit_card

            if _is_fit_card_failure(fit_card):
                session["plan_log"].append("create_fit_card failed — returning partial results")
                session["error"] = _fit_card_failure_message(session["selected_item"])
                session["fit_card"] = None
                return session

            session["plan_log"].append("done — listing, outfit, and fit card ready")
            if remember_style and session["parsed"].get("style_hints"):
                update_style_profile(
                    style_hints=session["parsed"]["style_hints"],
                    preferred_size=session["parsed"].get("size"),
                )
                session["style_profile_saved"] = True
                session["plan_log"].append("saved style hints to profile")
            step = "done"

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
