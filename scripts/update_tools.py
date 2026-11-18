"""
Adelogic AI Tools Auto-Updater
Runs weekly via GitHub Actions.
Searches Tavily for newly released AI tools, then injects any new ones into index.html.
"""

import os
import re
import json
import requests
from datetime import datetime

TAVILY_API_KEY = os.environ.get("TAVILY_API_KEY", "")
INDEX_PATH = "index.html"

# ── Category mapping ──────────────────────────────────────────────────────────
CATEGORY_KEYWORDS = {
    "brains":     ["chatbot", "chat", "assistant", "language model", "llm", "reasoning", "research"],
    "makers":     ["image", "video", "audio", "music", "art", "creative", "generate", "design", "photo"],
    "automation": ["automate", "workflow", "agent", "task", "productivity", "schedule", "pipeline"],
    "web":        ["search", "web", "browser", "scrape", "seo", "website"],
    "voice":      ["voice", "speech", "transcribe", "text to speech", "tts"],
    "apps":       ["code", "developer", "app", "plugin", "extension", "api"],
}
FAMILY_MAP = {
    "brains":     "tool-card-family-chat",
    "makers":     "maker",
    "automation": "automation",
    "web":        "web",
    "voice":      "voice",
    "apps":       "apps",
}
BADGE_MAP = {
    "brains":     "AI Brain",
    "makers":     "Creator",
    "automation": "Automation",
    "web":        "Web AI",
    "voice":      "Voice AI",
    "apps":       "Dev Tool",
}

def guess_category(text: str) -> str:
    text_lower = text.lower()
    scores = {cat: 0 for cat in CATEGORY_KEYWORDS}
    for cat, keywords in CATEGORY_KEYWORDS.items():
        for kw in keywords:
            if kw in text_lower:
                scores[cat] += 1
    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else "apps"

def guess_cost(text: str) -> tuple[str, str]:
    text_lower = text.lower()
    if "free" in text_lower and "paid" in text_lower:
        return "Free + Paid plans", "cost-info"
    elif "free" in text_lower:
        return "Free to use", "cost-free"
    elif any(w in text_lower for w in ["subscription", "paid", "pricing", "plan", "$"]):
        return "Paid / subscription", "cost-paid"
    return "Free / Freemium", "cost-free"

def search_new_tools() -> list[dict]:
    """Call Tavily API and return a list of raw result dicts."""
    if not TAVILY_API_KEY:
        print("WARNING: No TAVILY_API_KEY found. Skipping search.")
        return []

    queries = [
        "new AI tools launched 2026",
        "best new artificial intelligence tools released this week",
        "latest AI productivity tools 2026",
    ]
    results = []
    for query in queries:
        try:
            resp = requests.post(
                "https://api.tavily.com/search",
                json={
                    "api_key": TAVILY_API_KEY,
                    "query": query,
                    "search_depth": "basic",
                    "max_results": 8,
                    "include_answer": False,
                },
                timeout=20,
            )
            resp.raise_for_status()
            data = resp.json()
            results.extend(data.get("results", []))
        except Exception as e:
            print(f"Search error for '{query}': {e}")
    return results

def extract_tool_name(title: str) -> str:
    """Clean up a page title to get a reasonable tool name."""
    # Remove common suffixes
    for suffix in [" - Official Site", " | Home", " - AI Tool", " – AI", " | AI", " - New AI"]:
        title = title.replace(suffix, "")
    # Take only the first part before " - " or " | "
    for sep in [" - ", " | ", " – ", " : "]:
        if sep in title:
            title = title.split(sep)[0]
    return title.strip()

def get_existing_names(html: str) -> set[str]:
    """Return lowercase names of all tools already in index.html."""
    pattern = r'name:\s*"([^"]+)"'
    return {m.lower() for m in re.findall(pattern, html)}

def build_tool_entry(name: str, url: str, description: str) -> str:
    """Format a new JS tool object matching the existing array format."""
    cat = guess_category(description)
    cost_text, cost_type = guess_cost(description)
    # Truncate description to ~120 chars
    desc = description.strip().replace('"', "'")
    if len(desc) > 120:
        desc = desc[:117] + "..."
    week_label = datetime.utcnow().strftime("Week of %b %d, %Y")
    entry = (
        f'  {{\n'
        f'    name: "{name}",\n'
        f'    url: "{url}",\n'
        f'    category: "{cat}",\n'
        f'    familyClass: "{FAMILY_MAP[cat]}",\n'
        f'    badge: "{BADGE_MAP[cat]}",\n'
        f'    description: "{desc}",\n'
        f'    cost: "{cost_text}",\n'
        f'    costType: "{cost_type}",\n'
        f'    origin: "{week_label}"\n'
        f'  }},\n'
    )
    return entry

def inject_tools(html: str, new_entries: list[str]) -> str:
    """Insert new tool entries just before the closing `];` of the tools array."""
    marker = "];"
    # Find the closing of the const tools array specifically
    idx = html.find("const tools = [")
    if idx == -1:
        print("ERROR: Could not find 'const tools = [' in index.html")
        return html
    # Find the ]; after that point
    close_idx = html.find("];", idx)
    if close_idx == -1:
        print("ERROR: Could not find closing ']; of tools array'")
        return html
    insertion = "".join(new_entries)
    return html[:close_idx] + insertion + html[close_idx:]

def main():
    print(f"🤖 Adelogic AI Tools Auto-Updater — {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}")

    # Read the HTML file
    with open(INDEX_PATH, "r", encoding="utf-8") as f:
        html = f.read()

    existing_names = get_existing_names(html)
    print(f"📋 Found {len(existing_names)} existing tools in index.html")

    # Search for new tools
    raw_results = search_new_tools()
    print(f"🔍 Got {len(raw_results)} search results from Tavily")

    new_entries = []
    seen_this_run = set()

    for result in raw_results:
        raw_title = result.get("title", "").strip()
        url = result.get("url", "").strip()
        snippet = result.get("content", result.get("snippet", "")).strip()

        if not raw_title or not url:
            continue

        name = extract_tool_name(raw_title)
        name_lower = name.lower()

        # Skip if already in the site or already added this run
        if name_lower in existing_names or name_lower in seen_this_run:
            continue

        # Skip generic/non-tool pages
        skip_words = ["reddit", "twitter", "youtube", "linkedin", "medium", "github.com/trending",
                      "top 10", "best ai tools", "list of", "roundup", "comparison"]
        if any(w in (raw_title + url).lower() for w in skip_words):
            continue

        # Must have a reasonable snippet
        if len(snippet) < 30:
            continue

        seen_this_run.add(name_lower)
        entry = build_tool_entry(name, url, snippet)
        new_entries.append(entry)
        print(f"  ✅ New tool: {name} ({url})")

    if not new_entries:
        print("✨ No new tools to add this week.")
        return

    print(f"\n➕ Adding {len(new_entries)} new tool(s) to index.html...")
    updated_html = inject_tools(html, new_entries)

    with open(INDEX_PATH, "w", encoding="utf-8") as f:
        f.write(updated_html)

    print(f"✅ index.html updated successfully with {len(new_entries)} new tool(s)!")

if __name__ == "__main__":
    main()
