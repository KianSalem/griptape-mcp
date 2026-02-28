"""Scrape Griptape Nodes documentation from docs.griptapenodes.com."""

import asyncio
import json
import re
import sqlite3
import sys
from pathlib import Path

from scrape_common import extract_mkdocs_content, fetch_pages, fetch_sitemap

SITEMAP_URL = "https://docs.griptapenodes.com/en/stable/sitemap.xml"
BASE_URL = "https://docs.griptapenodes.com"
STABLE_PREFIX = "/en/stable/"
SOURCE = "nodes"

# Only skip truly irrelevant pages
SKIP_PATTERNS = ["/search.html", "/404.html"]

# Node documentation pages live under /nodes/
NODE_URL_PATTERN = re.compile(r"/nodes/(\w+)/(\w+)/?$")

# Map URL path segments to display categories
CATEGORY_MAP = {
    "agents": "Agents",
    "audio": "Audio",
    "config": "Config",
    "convert": "Convert",
    "dict": "Dict",
    "execution": "Execution",
    "image": "Image",
    "json": "JSON",
    "lists": "Lists",
    "misc": "Misc",
    "number": "Number",
    "rules": "Rules",
    "text": "Text",
    "three_d": "3D",
    "tools": "Tools",
    "video": "Video",
    "advanced_media_library": "Advanced Media Library",
}


def should_skip(url: str) -> bool:
    return any(pattern in url for pattern in SKIP_PATTERNS)


def extract_node_info(url: str, title: str) -> dict | None:
    """If this URL is a node documentation page, extract structured info."""
    match = NODE_URL_PATTERN.search(url)
    if not match:
        return None

    category_slug = match.group(1)
    category = CATEGORY_MAP.get(category_slug, category_slug.replace("_", " ").title())

    return {
        "name": title,
        "display_name": title,
        "category": category,
    }


async def scrape(db_path: Path) -> dict:
    """Scrape the Griptape Nodes docs into the given SQLite database.

    Returns stats dict with counts.
    """
    print(f"[nodes] Fetching sitemap: {SITEMAP_URL}")
    entries = await fetch_sitemap(SITEMAP_URL)

    # Normalize URLs: sitemap may return URLs without /en/stable/ prefix
    def normalize_url(url: str) -> str:
        from urllib.parse import urlparse
        parsed = urlparse(url)
        path = parsed.path
        if not path.startswith(STABLE_PREFIX):
            path = STABLE_PREFIX + path.lstrip("/")
        return f"{BASE_URL}{path}"

    urls = [normalize_url(e["url"]) for e in entries if not should_skip(e["url"])]
    # Deduplicate while preserving order
    urls = list(dict.fromkeys(urls))
    lastmod_map = {normalize_url(e["url"]): e["lastmod"] for e in entries}

    print(f"[nodes] Found {len(urls)} pages to scrape (filtered from {len(entries)} sitemap entries)")

    print("[nodes] Fetching pages...")
    pages = await fetch_pages(urls)

    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")

    stats = {"pages": 0, "sections": 0, "code_examples": 0, "nodes": 0, "errors": 0}

    for page in pages:
        if page["error"]:
            print(f"  [ERROR] {page['url']}: {page['error']}")
            stats["errors"] += 1
            continue

        data = extract_mkdocs_content(page["html"])
        if not data["title"]:
            continue

        try:
            cursor = conn.execute(
                """
                INSERT OR REPLACE INTO pages (url, source, title, content, content_html, breadcrumbs, last_modified)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    page["url"],
                    SOURCE,
                    data["title"],
                    data["content_text"],
                    data["content_html"],
                    json.dumps(data["breadcrumbs"]),
                    lastmod_map.get(page["url"]),
                ),
            )
            page_id = cursor.lastrowid
            stats["pages"] += 1

            for section in data["sections"]:
                conn.execute(
                    "INSERT INTO sections (page_id, heading, level, content, anchor) VALUES (?, ?, ?, ?, ?)",
                    (page_id, section["heading"], section["level"], section["content"], section["anchor"]),
                )
                stats["sections"] += 1

            for ex in data["code_examples"]:
                section_id = None
                if ex.get("context"):
                    row = conn.execute(
                        "SELECT id FROM sections WHERE page_id = ? AND heading = ? LIMIT 1",
                        (page_id, ex["context"]),
                    ).fetchone()
                    if row:
                        section_id = row[0]

                conn.execute(
                    "INSERT INTO code_examples (page_id, section_id, language, code, context) VALUES (?, ?, ?, ?, ?)",
                    (page_id, section_id, ex["language"], ex["code"], ex["context"]),
                )
                stats["code_examples"] += 1

            # Extract node info if this is a node documentation page
            node_info = extract_node_info(page["url"], data["title"])
            if node_info:
                conn.execute(
                    "INSERT INTO nodes (name, display_name, category, description, page_id) VALUES (?, ?, ?, ?, ?)",
                    (
                        node_info["name"],
                        node_info["display_name"],
                        node_info["category"],
                        data["content_text"][:500] if data["content_text"] else None,
                        page_id,
                    ),
                )
                stats["nodes"] += 1

        except sqlite3.IntegrityError as e:
            print(f"  [SKIP] {page['url']}: {e}")

    conn.commit()
    conn.close()

    print(
        f"[nodes] Done: {stats['pages']} pages, {stats['nodes']} nodes, "
        f"{stats['sections']} sections, {stats['code_examples']} code examples, "
        f"{stats['errors']} errors"
    )
    return stats


if __name__ == "__main__":
    db_path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("griptape.db")
    asyncio.run(scrape(db_path))
