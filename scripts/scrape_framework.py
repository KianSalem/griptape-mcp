"""Scrape Griptape Framework documentation from docs.griptape.ai."""

import asyncio
import json
import sqlite3
import sys
from pathlib import Path

from scrape_common import extract_mkdocs_content, fetch_pages, fetch_sitemap

SITEMAP_URL = "https://docs.griptape.ai/stable/sitemap.xml"
SOURCE = "framework"

# Skip auto-generated API reference pages (too voluminous for v1)
SKIP_PATTERNS = ["/reference/", "/search.html", "/404.html"]


def should_skip(url: str) -> bool:
    return any(pattern in url for pattern in SKIP_PATTERNS)


async def scrape(db_path: Path) -> dict:
    """Scrape the Griptape Framework docs into the given SQLite database.

    Returns stats dict with counts.
    """
    print(f"[framework] Fetching sitemap: {SITEMAP_URL}")
    entries = await fetch_sitemap(SITEMAP_URL)
    urls = [e["url"] for e in entries if not should_skip(e["url"])]
    lastmod_map = {e["url"]: e["lastmod"] for e in entries}

    print(f"[framework] Found {len(urls)} pages to scrape (filtered from {len(entries)} sitemap entries)")

    print("[framework] Fetching pages...")
    pages = await fetch_pages(urls)

    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")

    stats = {"pages": 0, "sections": 0, "code_examples": 0, "errors": 0}

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
                # Find the section this code example belongs to
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

        except sqlite3.IntegrityError as e:
            print(f"  [SKIP] {page['url']}: {e}")

    conn.commit()
    conn.close()

    print(f"[framework] Done: {stats['pages']} pages, {stats['sections']} sections, {stats['code_examples']} code examples, {stats['errors']} errors")
    return stats


if __name__ == "__main__":
    db_path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("griptape.db")
    asyncio.run(scrape(db_path))
