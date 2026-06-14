"""
tools.py

The three required FitFindr tools. Each tool is a standalone function that
can be called and tested independently before being wired into the agent loop.

Complete and test each tool before moving to agent.py.

Tools:
    search_listings(description, size, max_price)  → list[dict]
    suggest_outfit(new_item, wardrobe, ...)         → str
    create_fit_card(outfit, new_item)               → str
    compare_price(item)                             → dict
    check_trends(size)                              → dict
"""

import json
import os
import re
from pathlib import Path

from dotenv import load_dotenv
from groq import Groq

from utils.data_loader import load_listings

load_dotenv()

_GROQ_MODEL = "llama-3.3-70b-versatile"
TOP_K = 3
_TRENDS_PATH = Path(__file__).resolve().parent / "data" / "trending_tags.json"
_CONDITION_FACTORS = {"excellent": 1.1, "good": 1.0, "fair": 0.85}


# ── Groq client ───────────────────────────────────────────────────────────────

def _get_groq_client():
    """Initialize and return a Groq client using GROQ_API_KEY from .env."""
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise ValueError(
            "GROQ_API_KEY not set. Add it to a .env file in the project root."
        )
    return Groq(api_key=api_key)


def _call_groq(prompt: str, temperature: float = 0.7) -> str:
    """Send a prompt to Groq and return the assistant's text response."""
    client = _get_groq_client()
    completion = client.chat.completions.create(
        model=_GROQ_MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=temperature,
    )
    content = completion.choices[0].message.content
    return content.strip() if content else ""


def _format_new_item(item: dict) -> str:
    """Format a listing dict for an LLM prompt."""
    tags = ", ".join(item.get("style_tags") or [])
    colors = ", ".join(item.get("colors") or [])
    brand = item.get("brand") or "unknown brand"
    return (
        f"Title: {item['title']}\n"
        f"Category: {item['category']}\n"
        f"Price: ${item['price']:.2f}\n"
        f"Platform: {item['platform']}\n"
        f"Condition: {item['condition']}\n"
        f"Size: {item['size']}\n"
        f"Colors: {colors}\n"
        f"Style tags: {tags}\n"
        f"Brand: {brand}\n"
        f"Description: {item['description']}"
    )


def _format_wardrobe_items(items: list[dict]) -> str:
    """Format wardrobe items for an LLM prompt."""
    lines = []
    for item in items:
        colors = ", ".join(item.get("colors") or [])
        tags = ", ".join(item.get("style_tags") or [])
        notes = item.get("notes")
        line = f"- {item['name']} ({item['category']}, colors: {colors}, tags: {tags})"
        if notes:
            line += f" — {notes}"
        lines.append(line)
    return "\n".join(lines)


def _matches_size(listing_size: str, requested_size: str) -> bool:
    """Case-insensitive partial match (e.g. 'M' matches 'S/M')."""
    return requested_size.lower() in listing_size.lower()


def _listing_search_text(listing: dict) -> str:
    """Build a lowercase searchable string from a listing's text fields."""
    tags = " ".join(listing.get("style_tags") or [])
    return f"{listing.get('title', '')} {listing.get('description', '')} {tags}".lower()


def _keyword_score(listing: dict, description: str) -> int:
    """Score a listing by how many description keywords appear in its text."""
    keywords = get_search_keywords(description)
    if not keywords:
        return 0

    searchable = _listing_search_text(listing)
    score = sum(1 for keyword in keywords if keyword in searchable)

    desc_lower = description.lower()
    tags_text = " ".join(listing.get("style_tags") or []).lower()
    if "graphic tee" in desc_lower and "graphic tee" in tags_text:
        score += 3
    for tag in listing.get("style_tags") or []:
        tag_lower = tag.lower()
        if tag_lower in desc_lower:
            score += 2

    return score


def _format_listing_summary(item: dict) -> str:
    """One-line listing summary for alternative options in prompts."""
    tags = ", ".join(item.get("style_tags") or [])
    return (
        f"{item['title']} — ${item['price']:.2f}, {item['platform']}, "
        f"{item['condition']} condition, size {item['size']}, tags: {tags}"
    )


_SEARCH_STOPWORDS = {"vintage", "retro", "classic", "used", "a", "an", "the", "style"}


def _significant_keywords(description: str) -> list[str]:
    """Keywords used for exact-match checks, with common thrift terms removed."""
    keywords = get_search_keywords(description)
    significant = [word for word in keywords if word not in _SEARCH_STOPWORDS]
    return significant or keywords


def _title_and_tags_text(listing: dict) -> str:
    tags = " ".join(listing.get("style_tags") or [])
    return f"{listing.get('title', '')} {tags}".lower()


def get_search_keywords(description: str) -> list[str]:
    """Tokenize a search description into keywords for relevance checks."""
    return [word for word in re.split(r"\W+", description.lower()) if word]


def listing_match_score(listing: dict, description: str) -> int:
    """Return how many description keywords appear in a listing."""
    return _keyword_score(listing, description)


def is_exact_listing_match(listing: dict, description: str) -> bool:
    """True when significant query terms appear in the listing title or tags."""
    keywords = _significant_keywords(description)
    if not keywords:
        return True

    title_tags = _title_and_tags_text(listing)
    return all(keyword in title_tags for keyword in keywords)


def get_criteria_mismatches(
    listing: dict,
    description: str,
    size: str | None = None,
    max_price: float | None = None,
) -> list[str]:
    """List ways a listing fails the user's original search criteria."""
    mismatches: list[str] = []

    if size and not _matches_size(listing["size"], size):
        mismatches.append(
            f"size is {listing['size']}, not your requested {size.upper()}"
        )
    if max_price is not None and listing["price"] > max_price:
        mismatches.append(
            f"price is ${listing['price']:.2f}, above your ${max_price:g} max"
        )
    if not is_exact_listing_match(listing, description):
        mismatches.append(
            f"'{listing['title']}' is not a close match for '{description}'"
        )

    return mismatches


def build_criteria_note(
    listing: dict,
    description: str,
    size: str | None = None,
    max_price: float | None = None,
    search_broadened: bool = False,
) -> str | None:
    """Prompt section when results do not fully meet the user's request."""
    lines: list[str] = []
    if search_broadened:
        lines.append(
            "No listings matched your exact filters — the search was automatically broadened"
        )
    lines.extend(get_criteria_mismatches(listing, description, size, max_price))

    if not lines:
        return None

    bullet_list = "\n".join(f"- {line}" for line in lines)
    return (
        "IMPORTANT — ORIGINAL REQUEST NOT FULLY MET:\n"
        f"{bullet_list}\n\n"
        "Your response MUST start by telling the user clearly that nothing fully meets "
        "their criteria and explain what is off about the top pick (size, price, or style). "
        "Then still offer 1-2 outfit ideas for the closest available option, or recommend "
        "a different listing from the alternatives if one fits better. "
        "Do not pretend the item is a perfect match.\n\n"
    )


# ── Tool 1: search_listings ───────────────────────────────────────────────────

def search_listings(
    description: str,
    size: str | None = None,
    max_price: float | None = None,
) -> list[dict]:
    """
    Search the mock listings dataset for items matching the description,
    optional size, and optional price ceiling.

    Args:
        description: Keywords describing what the user is looking for
                     (e.g., "vintage graphic tee").
        size:        Size string to filter by, or None to skip size filtering.
                     Matching is case-insensitive (e.g., "M" matches "S/M").
        max_price:   Maximum price (inclusive), or None to skip price filtering.

    Returns:
        A list of matching listing dicts, sorted by relevance (best match first).
        Returns an empty list if nothing matches — does NOT raise an exception.

    Each listing dict has the following fields:
        id, title, description, category, style_tags (list), size,
        condition, price (float), colors (list), brand, platform

    TODO:
        1. Load all listings with load_listings().
        2. Filter by max_price and size (if provided).
        3. Score each remaining listing by keyword overlap with `description`.
        4. Drop any listings with a score of 0 (no relevant matches).
        5. Sort by score, highest first, and return the listing dicts.

    Before writing code, fill in the Tool 1 section of planning.md.
    """
    listings = load_listings()
    scored: list[tuple[int, dict]] = []

    for listing in listings:
        if max_price is not None and listing["price"] > max_price:
            continue
        if size is not None and not _matches_size(listing["size"], size):
            continue

        score = _keyword_score(listing, description)
        if score > 0:
            scored.append((score, listing))

    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [listing for _, listing in scored]


# ── Tool 2: suggest_outfit ────────────────────────────────────────────────────

def suggest_outfit(
    new_item: dict,
    wardrobe: dict,
    alternatives: list[dict] | None = None,
    user_style: str | None = None,
    trend_context: str | None = None,
    criteria_note: str | None = None,
) -> str:
    """
    Given a thrifted item and the user's wardrobe, suggest 1–2 complete outfits.

    Args:
        new_item: A listing dict (the item the user is considering buying).
        wardrobe: A wardrobe dict with an 'items' key containing a list of
                  wardrobe item dicts. May be empty — handle this gracefully.
        alternatives: Other top search results when the top pick is not an exact
                        match. Used to suggest which listing fits best.
        user_style: What the user said they usually wear, extracted from their
                    query or saved style profile. Used when the wardrobe is empty.
        trend_context: Summary of trending tags for the user's size (from check_trends).
        criteria_note: When the listing does not meet size, price, or keyword criteria.

    Returns:
        A non-empty string with outfit suggestions.
        If the wardrobe is empty, offer general styling advice for the item
        rather than raising an exception or returning an empty string.

    TODO:
        1. Check whether wardrobe['items'] is empty.
        2. If empty: call the LLM with a prompt for general styling ideas
           (what kinds of items pair well, what vibe it suits, etc.).
        3. If not empty: format the wardrobe items into a prompt and ask
           the LLM to suggest specific outfit combinations using the new item
           and named pieces from the wardrobe.
        4. Return the LLM's response as a string.

    Before writing code, fill in the Tool 2 section of planning.md.
    """
    item_details = _format_new_item(new_item)
    wardrobe_items = wardrobe.get("items") or []

    criteria_section = criteria_note or ""

    alternatives_section = ""
    if alternatives:
        alt_lines = "\n".join(
            f"- {'(top pick) ' if item['id'] == new_item['id'] else ''}"
            f"{_format_listing_summary(item)}"
            for item in alternatives
        )
        alternatives_section = (
            "TOP SEARCH RESULTS (pick the closest to what the user asked for):\n"
            f"{alt_lines}\n\n"
            "Compare these listings against the user's original request. "
            "Recommend the best fit, then suggest 1-2 outfits styling that pick.\n\n"
        )

    trend_section = ""
    if trend_context:
        trend_section = (
            "CURRENT TRENDS (mock platform feed for their size):\n"
            f"{trend_context}\n\n"
            "Mention if the item fits or contrasts with a trending look.\n\n"
        )

    if not wardrobe_items:
        style_section = ""
        if user_style:
            style_section = (
                "USER'S USUAL STYLE (from their message — no saved wardrobe yet):\n"
                f"{user_style}\n\n"
                "Build outfit ideas around what they said they usually wear. "
                "Name those pieces directly in your suggestions.\n\n"
            )
        prompt = (
            "You are a thrift fashion stylist. The user is considering buying "
            "this secondhand item but has not added any wardrobe pieces yet.\n\n"
            f"{criteria_section}"
            f"{style_section}"
            f"{trend_section}"
            f"{alternatives_section}"
            f"PRIMARY ITEM:\n{item_details}\n\n"
            "Suggest 1-2 complete outfit ideas. "
            + (
                "Center the outfits on the user's usual pieces above."
                if user_style
                else "Use general item types (not specific owned pieces). "
                "Mention what vibes, colors, and silhouettes pair well."
            )
            + " Include one practical styling tip."
        )
    else:
        wardrobe_text = _format_wardrobe_items(wardrobe_items)
        prompt = (
            "You are a thrift fashion stylist. Suggest 1–2 complete outfits "
            "combining the new item with pieces the user already owns.\n\n"
            f"{criteria_section}"
            f"{trend_section}"
            f"{alternatives_section}"
            f"PRIMARY ITEM:\n{item_details}\n\n"
            f"USER'S WARDROBE:\n{wardrobe_text}\n\n"
            "Name specific wardrobe pieces from the list above. Explain why "
            "they work together. Include one practical styling tip."
        )

    return _call_groq(prompt)


# ── Tool 3: create_fit_card ───────────────────────────────────────────────────

def create_fit_card(outfit: str, new_item: dict) -> str:
    """
    Generate a short, shareable outfit caption for the thrifted find.

    Args:
        outfit:   The outfit suggestion string from suggest_outfit().
        new_item: The listing dict for the thrifted item.

    Returns:
        A 2-4 sentence string usable as an Instagram/TikTok caption.
        If outfit is empty or missing, return a descriptive error message
        string — do NOT raise an exception.

    The caption should:
    - Feel casual and authentic (like a real OOTD post, not a product description)
    - Mention the item name, price, and platform naturally (once each)
    - Capture the outfit vibe in specific terms
    - Sound different each time for different inputs (use higher LLM temperature)

    TODO:
        1. Guard against an empty or whitespace-only outfit string.
        2. Build a prompt that gives the LLM the item details and the outfit,
           and asks for a caption matching the style guidelines above.
        3. Call the LLM and return the response.

    Before writing code, fill in the Tool 3 section of planning.md.
    """
    if not outfit or not outfit.strip():
        title = new_item.get("title", "this item")
        price = new_item.get("price")
        platform = new_item.get("platform", "the platform")
        price_text = f"${price:.2f}" if price is not None else "unknown price"
        return (
            f"Could not generate a fit card for {title} ({price_text} on {platform}) "
            "because the outfit suggestion was missing. Try running the styling step again."
        )

    item_details = _format_new_item(new_item)
    prompt = (
        "Write a casual Instagram/TikTok outfit caption for a thrift find. "
        "Sound like a real person posting an OOTD, not a product listing.\n\n"
        f"ITEM:\n{item_details}\n\n"
        f"OUTFIT STYLING:\n{outfit.strip()}\n\n"
        "Rules:\n"
        "- 2-4 sentences only\n"
        "- Mention the item name, price, and platform naturally once each\n"
        "- Capture the outfit vibe in specific terms\n"
        "- Return only the caption text, no quotes or labels"
    )

    return _call_groq(prompt, temperature=0.9)


# ── Tool 4: compare_price ─────────────────────────────────────────────────────

def _normalized_price(price: float, condition: str) -> float:
    """Adjust price to a 'good condition' baseline for fair comparison."""
    factor = _CONDITION_FACTORS.get(condition, 1.0)
    return price / factor


def _find_comparables(item: dict) -> list[dict]:
    """Find similar listings in the dataset for price comparison."""
    comparables: list[dict] = []
    item_tags = {tag.lower() for tag in item.get("style_tags") or []}
    title_words = {
        word
        for word in get_search_keywords(item.get("title", ""))
        if word not in _SEARCH_STOPWORDS and len(word) > 2
    }

    for listing in load_listings():
        if listing["id"] == item["id"]:
            continue
        if listing["category"] != item["category"]:
            continue

        listing_tags = {tag.lower() for tag in listing.get("style_tags") or []}
        tag_overlap = len(item_tags & listing_tags)
        title_overlap = sum(
            1 for word in title_words if word in listing.get("title", "").lower()
        )

        if tag_overlap >= 1 or title_overlap >= 2:
            comparables.append(listing)

    return comparables


def compare_price(item: dict) -> dict:
    """
    Estimate whether a listing's price is fair vs comparable items in the dataset.

    Args:
        item: A listing dict with at least id, category, price, condition, style_tags.

    Returns:
        A dict with verdict, item_price, median_price, comparable_count, and summary.
        Never raises — returns insufficient_data when there are too few comps.
    """
    item_price = float(item["price"])
    comparables = _find_comparables(item)

    if len(comparables) < 2:
        return {
            "verdict": "insufficient_data",
            "item_price": item_price,
            "median_price": None,
            "comparable_count": len(comparables),
            "summary": (
                f"Not enough similar {item['category']} listings in the dataset to "
                "judge whether this price is fair."
            ),
        }

    normalized_prices = sorted(
        _normalized_price(comp["price"], comp["condition"]) for comp in comparables
    )
    mid = len(normalized_prices) // 2
    median_price = (
        normalized_prices[mid]
        if len(normalized_prices) % 2
        else (normalized_prices[mid - 1] + normalized_prices[mid]) / 2
    )
    item_normalized = _normalized_price(item_price, item.get("condition", "good"))
    ratio = item_normalized / median_price if median_price else 1.0

    if ratio <= 0.85:
        verdict = "below_market"
        summary = (
            f"${item_price:.2f} looks like a deal — about {100 - int(ratio * 100)}% "
            f"below similar items (median ~${median_price:.2f}, {len(comparables)} comps)."
        )
    elif ratio >= 1.15:
        verdict = "above_market"
        summary = (
            f"${item_price:.2f} is above typical for similar items "
            f"(median ~${median_price:.2f}, {len(comparables)} comps)."
        )
    else:
        verdict = "fair"
        summary = (
            f"${item_price:.2f} is in line with similar items "
            f"(median ~${median_price:.2f}, {len(comparables)} comps)."
        )

    return {
        "verdict": verdict,
        "item_price": item_price,
        "median_price": round(median_price, 2),
        "comparable_count": len(comparables),
        "summary": summary,
    }


# ── Tool 5: check_trends ──────────────────────────────────────────────────────

def _size_bucket(size: str | None) -> str:
    """Map a free-form size string to a trends bucket."""
    if not size:
        return "default"

    upper = size.upper()
    for bucket in ("XXS", "XS", "XL", "XXL"):
        if bucket in upper:
            return bucket if bucket in {"XS", "XL"} else "default"
    for bucket in ("XS", "S", "M", "L", "XL"):
        if bucket in upper.split("/") or f" {bucket} " in f" {upper} ":
            return bucket
    if upper in {"XS", "S", "M", "L", "XL"}:
        return upper
    return "default"


def check_trends(size: str | None = None) -> dict:
    """
    Surface popular style tags from a mock public fashion feed.

    Args:
        size: Optional size from the user's query for size-filtered trends.

    Returns:
        A dict with trending_tags, size_bucket, platform, and summary.
        Never raises — returns empty tags if the feed file is unavailable.
    """
    if not _TRENDS_PATH.exists():
        return {
            "trending_tags": [],
            "size_bucket": _size_bucket(size),
            "platform": "unknown",
            "summary": "Trend data is unavailable right now.",
        }

    with open(_TRENDS_PATH, encoding="utf-8") as handle:
        feed = json.load(handle)

    bucket = _size_bucket(size)
    by_size = feed.get("by_size") or {}
    tags = by_size.get(bucket) or by_size.get("default") or []
    platform = feed.get("platform", "depop")

    if tags:
        summary = (
            f"Trending in size {bucket} on {platform}: "
            + ", ".join(tags[:4])
            + "."
        )
    else:
        summary = f"No trend tags found for size {bucket}."

    return {
        "trending_tags": tags,
        "size_bucket": bucket,
        "platform": platform,
        "updated": feed.get("updated"),
        "summary": summary,
    }
