"""
app.py

Gradio interface for FitFindr. The layout and wiring are already set up —
your job is to fill in handle_query() so it calls run_agent() and maps
the session results to the three output panels.

Run with:
    python app.py

Then open the localhost URL shown in your terminal (usually http://localhost:7860,
but check your terminal — the port may differ).
"""

import gradio as gr

from agent import run_agent
from utils.data_loader import get_example_wardrobe, get_empty_wardrobe


# ── query handler ─────────────────────────────────────────────────────────────

def _format_listing(item: dict) -> str:
    """Format a listing dict into readable text for the UI."""
    brand = item.get("brand") or "Unknown"
    colors = ", ".join(item.get("colors") or [])
    tags = ", ".join(item.get("style_tags") or [])
    return (
        f"{item['title']}\n"
        f"${item['price']:.2f} on {item['platform']} · {item['condition']} condition\n"
        f"Size: {item['size']} · Brand: {brand}\n"
        f"Colors: {colors}\n"
        f"Tags: {tags}\n\n"
        f"{item['description']}"
    )


def _format_style_memory_note(session: dict, remember_style: bool) -> str | None:
    """Explain style profile load/save state for the UI."""
    if not remember_style:
        return None
    if session.get("style_profile_saved"):
        hints = session["parsed"].get("style_hints", "")
        return f"Style memory: saved \"{hints}\" to your profile for next time."
    if session["parsed"].get("style_from_profile"):
        hints = session["parsed"].get("effective_style", "")
        return f"Style memory: using saved preferences — {hints}"
    if session["parsed"].get("style_hints"):
        return "Style memory: will save your preferences after this run completes."
    return "Style memory: on (include \"I mostly wear...\" in your query to save preferences)"


def _format_trend_awareness(trends: dict | None) -> str | None:
    """Format check_trends output for the UI."""
    if not trends:
        return None

    tags = trends.get("trending_tags") or []
    bucket = trends.get("size_bucket", "default")
    platform = trends.get("platform", "depop")
    updated = trends.get("updated")

    if not tags:
        return f"Trend awareness: {trends.get('summary', 'No trend data available.')}"

    tag_lines = "\n".join(f"  - {tag}" for tag in tags[:6])
    header = f"Trend awareness — popular on {platform} for size {bucket}"
    if updated:
        header += f" (feed updated {updated})"
    return f"{header}:\n{tag_lines}"


def _format_agent_insights(
    session: dict,
    remember_style: bool,
) -> str:
    """Build a visible insights block for price check, trends, and style memory."""
    lines: list[str] = []

    price = session.get("price_analysis") or {}
    if price.get("summary"):
        verdict = str(price.get("verdict", "unknown")).replace("_", " ")
        lines.append(f"Price check ({verdict}): {price['summary']}")

    trend_block = _format_trend_awareness(session.get("trends"))
    if trend_block:
        lines.append(trend_block)

    style_note = _format_style_memory_note(session, remember_style)
    if style_note:
        lines.append(style_note)

    if not lines:
        return "Run a search to see price check, trend awareness, and style memory."

    return "\n\n".join(lines)


def _format_top_listings(
    results: list[dict],
    selected_id: str,
    exact_match: bool,
    search_note: str | None = None,
    criteria_mismatches: list[str] | None = None,
) -> str:
    """Format the top K search results for the listing panel."""
    if not results:
        return ""

    lines = []
    if search_note:
        lines.extend([search_note, ""])
    if criteria_mismatches:
        lines.append("Top pick does not fully match your request:")
        for issue in criteria_mismatches:
            lines.append(f"  - {issue}")
        lines.append("")

    header = f"Top {len(results)} match{'es' if len(results) != 1 else ''}"
    if not exact_match:
        header += " (no exact match — see outfit panel for suggestions)"
    lines.extend([header, ""])

    for index, item in enumerate(results, start=1):
        label = f"#{index}"
        if item["id"] == selected_id:
            label += " ← top pick"
        lines.append(label)
        lines.append(_format_listing(item))
        lines.append("")

    return "\n".join(lines).strip()


def handle_query(
    user_query: str,
    wardrobe_choice: str,
    remember_style: bool,
) -> tuple[str, str, str, str]:
    """
    Called by Gradio when the user submits a query.

    Returns:
        (insights, listing_text, outfit_suggestion, fit_card)
    """
    if not user_query or not user_query.strip():
        return "Please enter a search query.", "", "", ""

    if wardrobe_choice == "Empty wardrobe (new user)":
        wardrobe = get_empty_wardrobe()
    else:
        wardrobe = get_example_wardrobe()

    session = run_agent(user_query.strip(), wardrobe, remember_style=remember_style)

    insights = _format_agent_insights(session, remember_style)
    listing_kwargs = {
        "results": session.get("search_results") or [],
        "selected_id": session["selected_item"]["id"] if session.get("selected_item") else "",
        "exact_match": session.get("exact_match", True),
        "search_note": session.get("search_note"),
        "criteria_mismatches": session.get("criteria_mismatches"),
    }

    if session["error"]:
        if session.get("selected_item") and session.get("outfit_suggestion"):
            listing_text = _format_top_listings(**listing_kwargs)
            return (
                insights,
                f"{listing_text}\n\nNote: {session['error']}",
                session["outfit_suggestion"],
                session.get("fit_card") or "",
            )
        return session["error"], "", "", ""

    return (
        insights,
        _format_top_listings(**listing_kwargs),
        session["outfit_suggestion"],
        session["fit_card"],
    )


# ── interface ─────────────────────────────────────────────────────────────────

EXAMPLE_QUERIES = [
    "vintage graphic tee under $30",
    "90s track jacket in size M",
    "flowy midi skirt under $40",
    "black combat boots size 8",
    "designer ballgown size XXS under $5",   # deliberate no-results test
]

def build_interface():
    with gr.Blocks(title="FitFindr") as demo:
        gr.Markdown("""
# FitFindr 🛍️
Find secondhand pieces and get outfit ideas based on your wardrobe.
Describe what you're looking for — include size and price if you want to filter.
        """)

        with gr.Row(equal_height=False):
            query_input = gr.Textbox(
                label="What are you looking for?",
                placeholder="e.g. vintage graphic tee under $30, size M",
                lines=2,
                scale=3,
            )
            with gr.Column(scale=1, min_width=240):
                wardrobe_choice = gr.Radio(
                    choices=["Example wardrobe", "Empty wardrobe (new user)"],
                    value="Example wardrobe",
                    label="Wardrobe",
                )
                remember_style = gr.Checkbox(
                    label="Remember my style",
                    value=False,
                )

        submit_btn = gr.Button("Find it", variant="primary")

        insights_output = gr.Textbox(
            label="Agent insights — compare_price · check_trends · style memory",
            lines=6,
            interactive=False,
        )

        with gr.Row(equal_height=True):
            listing_output = gr.Textbox(
                label="🛍️ Top listings found",
                lines=12,
                interactive=False,
            )
            outfit_output = gr.Textbox(
                label="👗 Outfit idea",
                lines=12,
                interactive=False,
            )
            fitcard_output = gr.Textbox(
                label="✨ Your fit card",
                lines=12,
                interactive=False,
            )

        gr.Examples(
            examples=[[q, "Example wardrobe", False] for q in EXAMPLE_QUERIES],
            inputs=[query_input, wardrobe_choice, remember_style],
            label="Try these queries",
        )

        submit_btn.click(
            fn=handle_query,
            inputs=[query_input, wardrobe_choice, remember_style],
            outputs=[insights_output, listing_output, outfit_output, fitcard_output],
        )
        query_input.submit(
            fn=handle_query,
            inputs=[query_input, wardrobe_choice, remember_style],
            outputs=[insights_output, listing_output, outfit_output, fitcard_output],
        )

    return demo


if __name__ == "__main__":
    demo = build_interface()
    demo.launch()
