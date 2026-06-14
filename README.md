# FitFindr

FitFindr is a thrift-shopping assistant that searches mock secondhand listings, suggests outfits using the user's wardrobe, and generates a shareable fit card caption.

## Setup

```bash
pip install -r requirements.txt
```

Set your Groq API key in a `.env` file ([console.groq.com](https://console.groq.com)):

```
GROQ_API_KEY=your_key_here
```

Run the Gradio UI:

```bash
python app.py
```

Run tests:

```bash
python -m pytest tests/ -v
```

Run the agent CLI:

```bash
python agent.py
```

## Project structure

```
├── agent.py          # Planning loop (run_agent)
├── app.py            # Gradio UI
├── tools.py          # search_listings, suggest_outfit, create_fit_card
├── planning.md       # Spec, diagram, and AI tool plan
├── data/             # Mock listings and wardrobe schema
├── utils/            # Data loader helpers
└── tests/            # pytest tests for tools and agent
```

---

## Tool inventory

### 1. `search_listings`

**Purpose:** Search the mock listings dataset for items matching keywords, with optional size and price filters.

| Parameter | Type | Description |
|-----------|------|-------------|
| `description` | `str` | Keywords to match against title, description, and style tags |
| `size` | `str \| None` | Size filter (case-insensitive partial match). `None` skips filtering |
| `max_price` | `float \| None` | Maximum price in dollars, inclusive. `None` skips filtering |

**Returns:** `list[dict]` of listing dicts sorted by relevance (best first). Each dict has: `id`, `title`, `description`, `category`, `style_tags`, `size`, `condition`, `price`, `colors`, `brand`, `platform`. Returns `[]` if nothing matches.

**Implementation notes:** Uses `load_listings()` from `utils/data_loader.py`. Scores keyword overlap, filters by price/size, drops zero-score matches.

---

### 2. `suggest_outfit`

**Purpose:** Use Groq (`llama-3.3-70b-versatile`) to suggest 1–2 outfits combining a listing with the user's wardrobe.

| Parameter | Type | Description |
|-----------|------|-------------|
| `new_item` | `dict` | A listing dict from `search_listings` |
| `wardrobe` | `dict` | Wardrobe with an `items` list (from `get_example_wardrobe()` or `get_empty_wardrobe()`) |
| `alternatives` | `list[dict] \| None` | Other top-K results when the top pick is not an exact match |
| `user_style` | `str \| None` | What the user said they usually wear, extracted from the query (empty wardrobe) |

**Returns:** `str` with outfit suggestions. Names specific wardrobe pieces when items exist; gives general styling advice when the wardrobe is empty.

---

### 3. `create_fit_card`

**Purpose:** Use Groq to generate a casual 2–4 sentence Instagram/TikTok caption for the thrift find.

| Parameter | Type | Description |
|-----------|------|-------------|
| `outfit` | `str` | Outfit suggestion string from `suggest_outfit` |
| `new_item` | `dict` | The same listing dict passed into `suggest_outfit` |

**Returns:** `str` caption mentioning item name, price, and platform once each. Returns an error message string (not an exception) if `outfit` is empty or whitespace.

---

### 4. `compare_price` *(extra credit)*

**Purpose:** Estimate whether a listing's price is fair vs comparable items in the dataset (same category, overlapping tags/title keywords). Condition-adjusted median comparison.

| Parameter | Type | Description |
|-----------|------|-------------|
| `item` | `dict` | Listing dict (typically the top search result) |

**Returns:** `dict` with `verdict` (`fair` / `below_market` / `above_market` / `insufficient_data`), `median_price`, `comparable_count`, and `summary`.

---

### 5. `check_trends` *(extra credit)*

**Purpose:** Surface popular style tags from a mock public fashion feed (`data/trending_tags.json`), filtered by the user's size bucket.

| Parameter | Type | Description |
|-----------|------|-------------|
| `size` | `str \| None` | Parsed size from the query |

**Returns:** `dict` with `trending_tags`, `size_bucket`, `platform`, and `summary`. Passed into `suggest_outfit` and shown in the listings panel.

---

## Planning loop

`run_agent(query, wardrobe, remember_style=True)` uses a **while-loop planner** — the next tool depends on what the previous step returned.

```
step = "search"
while step != "done":
    if step == "search":
        call search_listings with current strategy
        if no results → try next broader strategy (drop size, raise budget, shorter keywords)
        if all strategies fail → set error, return
        else → step = "price_check"

    elif step == "price_check":
        compare_price(top pick) + check_trends(size) → step = "suggest"

    elif step == "suggest":
        if top pick is not an exact match → pass top-K alternatives into suggest_outfit
        if outfit empty → set error, return
        else → step = "fit_card"

    elif step == "fit_card":
        if fit card fails → set error but keep listing + outfit (partial success)
        else → step = "done"
```

### Decision branches

| After | Condition | Next action |
|-------|-----------|-------------|
| `search_listings` | empty results, more strategies left | Loop back to `search` with broader filters |
| `search_listings` | empty results, strategies exhausted | Set `session["error"]`, return |
| `search_listings` | results found | `compare_price` + `check_trends`, then `suggest_outfit` |
| `search_listings` | results found after retry | Same, plus `session["search_note"]` explaining relaxed filters |
| `suggest_outfit` | empty string | Set error, return (skip fit card) |
| `suggest_outfit` | non-empty | Call `create_fit_card` |
| `suggest_outfit` | top pick not exact match | Pass `alternatives=search_results` for comparison |
| `create_fit_card` | failure | Set error, return listing + outfit without fit card |
| `create_fit_card` | success | Save style profile if opted in; done |

Each run also records `session["plan_log"]` — a list of which tools were called and why (useful for debugging and demo narration).

---

## Extra credit

| Feature | Status | How it works |
|---------|--------|--------------|
| **Retry with fallback** | Done | Search loop retries with dropped size, raised budget, broader keywords; `search_note` explains adjustments |
| **Price comparison** | Done | `compare_price()` after search; 💰 line in listings panel |
| **Style profile memory** | Done | `data/style_profile.json`; "Remember my style" checkbox; loads saved hints when query omits them |
| **Trend awareness** | Done | `check_trends()` reads mock Depop feed; 📈 line in listings panel + trend context in outfit prompt |

`app.py` calls `run_agent()` and maps the session to three UI panels: top listings, outfit suggestion, and fit card.

---

## State management

All state for one interaction lives in a single **session dict**:

| Field | Set when | Used by |
|-------|----------|---------|
| `query` | Session init | Reference (original user input) |
| `parsed` | After regex parse | Inputs to `search_listings` |
| `search_results` | After search | Top K listings; pick `selected_item = results[0]` |
| `selected_item` | Top search result | Passed to `suggest_outfit` and `create_fit_card` |
| `price_analysis` | After compare_price | Shown in listing panel |
| `trends` | After check_trends | Outfit prompt + listing panel |
| `parsed.effective_style` | Parse + profile load | `suggest_outfit` when wardrobe empty |
| `wardrobe` | Session init | Passed to `suggest_outfit` |
| `outfit_suggestion` | After suggest | Passed to `create_fit_card` |
| `fit_card` | After fit card | Returned to UI on success |
| `error` | On early exit | Shown to user; check this first |

**Data flow:** `parsed` → `search_results` → `selected_item` → `outfit_suggestion` → `fit_card`

The same `selected_item` dict object is passed to both `suggest_outfit` and `create_fit_card`. The exact `outfit_suggestion` string from `suggest_outfit` is passed to `create_fit_card` with no re-prompting or hardcoded values between steps.

---

## Error handling

### `search_listings` — no results

**Behavior:** Returns `[]` without raising. The agent **retries with broader filters** (drop size, raise budget, shorter keywords). Only after all strategies fail does it set `session["error"]` and return without calling downstream tools.

**Example:**

```
No listings matched 'designer ballgown' in size xxs under $5. Try broadening your search, raising your budget above $5, removing the size filter. The agent already tried relaxing your filters automatically.
```

---

### `search_listings` — broadened search succeeds

**Behavior:** Not an error. User sees `Broadened search: …` at the top of the listings panel. Agent continues through price check, criteria check, outfit, and fit card.

---

### `compare_price` — insufficient comparables

**Behavior:** Not an error. Returns `verdict: "insufficient_data"` with an explanatory summary. Agent continues.

---

### `check_trends` — feed unavailable

**Behavior:** Not an error. Returns empty tags and a short unavailable message. Agent continues without trend context.

---

### Criteria mismatch — top pick doesn't meet original request

**Behavior:** Not a hard failure. When size, price, keywords, or broadened search leave gaps, the agent sets `criteria_mismatches` and passes `criteria_note` to `suggest_outfit`. The listings panel shows ⚠️ bullets; the outfit panel must **admit nothing fully matches**, then still suggest 1–2 outfits from the closest available listing(s).

**Example query:** `vintage tee size XXS under $5`

---

### `suggest_outfit` — empty wardrobe

**Behavior:** Not treated as an error. Returns general styling advice, or uses `user_style` from the query / saved profile. Agent continues to `create_fit_card`.

---

### `suggest_outfit` — LLM returns empty string

**Behavior:** Agent sets `session["error"] = "Couldn't generate a styling suggestion. Try again."` and returns without calling `create_fit_card`.

---

### `create_fit_card` — empty outfit input

**Behavior:** Tool returns a descriptive error string without calling Groq or raising an exception.

```
Could not generate a fit card for Y2K Baby Tee — Butterfly Print ($18.00 on depop) because the outfit suggestion was missing. Try running the styling step again.
```

---

### `create_fit_card` — LLM failure after valid outfit

**Behavior:** **Partial success.** Listings and outfit panels stay populated; fit card panel is empty. Listings panel appends ⚠️ with the error message including item title, price, and platform.

## Spec reflection

### What matched the spec

- All three tools implemented in `tools.py` using `load_listings()` and Groq as specified
- Planning loop follows the diagram in `planning.md`: search first, early exit on empty results, session dict passes state between tools
- Empty wardrobe handled gracefully in `suggest_outfit`
- Empty outfit guarded in `create_fit_card`
- Error messages echo what was searched and suggest concrete next steps (not just "no results found")
- Criteria mismatches warn without stopping; fit-card failures return partial results
- pytest covers failure modes for tools and agent branching

### What changed during implementation

- **Query parsing:** Used regex instead of LLM parsing to keep search deterministic and avoid extra API calls
- **Style hints:** Extracts "I mostly wear…" from the query for empty-wardrobe styling
- **Top-K listings:** Shows top 3 results; passes alternatives when no exact match
- **Planning loop:** While-loop retries search with relaxed filters before giving up; branches on exact match and fit-card failure
- **Fit card temperature:** Set to `0.9` so captions vary between runs (verified with 4 identical inputs)
- **Partial success:** If fit card fails but listing and outfit exist, UI still shows those panels

### What I would improve next

- LLM-based query parsing for ambiguous requests
- Let the user confirm before accepting a broadened search
- Cache Groq responses during development to reduce API calls while testing

---

## Data

**Listings:** `data/listings.json` — 40 mock secondhand listings.

**Wardrobe:** `data/wardrobe_schema.json` — load with `get_example_wardrobe()` or `get_empty_wardrobe()` from `utils/data_loader.py`.

See `planning.md` for the full spec, architecture diagram, and AI tool plan.
