"""Scrape Griptape Nodes documentation from GitHub source markdown.

Falls back to GitHub raw content when docs.griptapenodes.com rate-limits us.
"""

import asyncio
import json
import re
import sqlite3
import sys
from pathlib import Path

import httpx

USER_AGENT = "griptape-mcp-scraper/0.1"
SOURCE = "nodes"
BASE_DOCS_URL = "https://docs.griptapenodes.com/en/stable"

# GitHub API for listing directory contents
GITHUB_API = "https://api.github.com/repos/griptape-ai/griptape-nodes/contents/docs"
GITHUB_RAW = "https://raw.githubusercontent.com/griptape-ai/griptape-nodes/main/docs"

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
    "workflows": "Workflows",
}


async def list_github_files(client: httpx.AsyncClient, path: str) -> list[dict]:
    """Recursively list all .md files under a GitHub directory path."""
    files = []
    resp = await client.get(
        f"https://api.github.com/repos/griptape-ai/griptape-nodes/contents/{path}",
        headers={"User-Agent": USER_AGENT, "Accept": "application/vnd.github.v3+json"},
    )
    if resp.status_code != 200:
        print(f"  [WARN] GitHub API {resp.status_code} for {path}")
        return files

    for item in resp.json():
        if item["type"] == "file" and item["name"].endswith(".md"):
            files.append({
                "path": item["path"],
                "name": item["name"],
                "download_url": item["download_url"],
            })
        elif item["type"] == "dir":
            sub = await list_github_files(client, item["path"])
            files.extend(sub)
            await asyncio.sleep(0.5)  # Be nice to GitHub API

    return files


def parse_markdown(content: str) -> dict:
    """Parse markdown content into structured sections and code examples."""
    lines = content.split("\n")
    title = ""
    sections = []
    code_examples = []
    current_section = None
    in_code_block = False
    code_lang = ""
    code_lines = []
    text_parts = []

    for line in lines:
        # Code block detection
        if line.startswith("```"):
            if in_code_block:
                # End of code block
                code_text = "\n".join(code_lines)
                if code_text.strip():
                    context = ""
                    if current_section:
                        context = current_section["heading"]
                    code_examples.append({
                        "language": code_lang or "python",
                        "code": code_text,
                        "context": context,
                    })
                code_lines = []
                in_code_block = False
            else:
                # Start of code block
                in_code_block = True
                code_lang = line.lstrip("`").strip().split()[0] if line.lstrip("`").strip() else "python"
            continue

        if in_code_block:
            code_lines.append(line)
            continue

        # Heading detection
        heading_match = re.match(r"^(#{1,4})\s+(.+)", line)
        if heading_match:
            level = len(heading_match.group(1))
            heading_text = heading_match.group(2).strip()

            if level == 1 and not title:
                title = heading_text
                continue

            # Save previous section
            if current_section and text_parts:
                current_section["content"] = "\n".join(text_parts).strip()

            current_section = {
                "heading": heading_text,
                "level": level,
                "content": "",
                "anchor": re.sub(r"[^\w\s-]", "", heading_text.lower()).replace(" ", "-"),
            }
            sections.append(current_section)
            text_parts = []
        else:
            text_parts.append(line)

    # Close last section
    if current_section and text_parts:
        current_section["content"] = "\n".join(text_parts).strip()

    full_text = content

    return {
        "title": title,
        "content_text": full_text,
        "sections": sections,
        "code_examples": code_examples,
    }


def path_to_docs_url(file_path: str) -> str:
    """Convert a GitHub file path to the equivalent docs URL."""
    # docs/nodes/image/load_image.md -> /en/stable/nodes/image/load_image/
    rel = file_path.replace("docs/", "").replace(".md", "")
    if rel == "index":
        return f"{BASE_DOCS_URL}/"
    return f"{BASE_DOCS_URL}/{rel}/"


def extract_node_info(file_path: str, title: str) -> dict | None:
    """If this file path is a node documentation page, extract structured info."""
    # Match docs/nodes/{category}/{node_name}.md
    match = re.search(r"docs/nodes/(\w+)/(\w+)\.md$", file_path)
    if not match:
        return None

    category_slug = match.group(1)
    if category_slug == "overview":
        return None

    category = CATEGORY_MAP.get(category_slug, category_slug.replace("_", " ").title())

    return {
        "name": title or match.group(2).replace("_", " ").title(),
        "display_name": title or match.group(2).replace("_", " ").title(),
        "category": category,
    }


async def scrape(db_path: Path) -> dict:
    """Scrape Griptape Nodes docs from GitHub into the SQLite database."""
    print("[nodes-github] Listing documentation files from GitHub...")

    async with httpx.AsyncClient(follow_redirects=True, timeout=30.0) as client:
        md_files = await list_github_files(client, "docs")

    print(f"[nodes-github] Found {len(md_files)} markdown files")

    # Fetch all markdown content
    print("[nodes-github] Fetching markdown content...")
    semaphore = asyncio.Semaphore(5)

    async def fetch_one(client, f):
        async with semaphore:
            try:
                resp = await client.get(f["download_url"], headers={"User-Agent": USER_AGENT})
                resp.raise_for_status()
                await asyncio.sleep(0.3)
                return {**f, "content": resp.text, "error": None}
            except Exception as e:
                return {**f, "content": None, "error": str(e)}

    async with httpx.AsyncClient(follow_redirects=True, timeout=30.0) as client:
        tasks = [fetch_one(client, f) for f in md_files]
        results = await asyncio.gather(*tasks)

    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")

    stats = {"pages": 0, "sections": 0, "code_examples": 0, "nodes": 0, "errors": 0}

    for result in results:
        if result["error"]:
            print(f"  [ERROR] {result['path']}: {result['error']}")
            stats["errors"] += 1
            continue

        data = parse_markdown(result["content"])
        if not data["title"]:
            # Use filename as title fallback
            data["title"] = result["name"].replace(".md", "").replace("_", " ").title()

        url = path_to_docs_url(result["path"])

        try:
            cursor = conn.execute(
                """
                INSERT OR REPLACE INTO pages (url, source, title, content, content_html, breadcrumbs, last_modified)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (url, SOURCE, data["title"], data["content_text"], "", "[]", None),
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

            node_info = extract_node_info(result["path"], data["title"])
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
            print(f"  [SKIP] {url}: {e}")

    conn.commit()
    conn.close()

    print(
        f"[nodes-github] Done: {stats['pages']} pages, {stats['nodes']} nodes, "
        f"{stats['sections']} sections, {stats['code_examples']} code examples, "
        f"{stats['errors']} errors"
    )
    return stats


if __name__ == "__main__":
    db_path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("griptape.db")
    asyncio.run(scrape(db_path))
