"""Shared scraping utilities for MkDocs documentation sites."""

import asyncio
import re
import defusedxml.ElementTree as ET

import httpx
from bs4 import BeautifulSoup, Tag

USER_AGENT = "griptape-mcp-scraper/0.1 (+https://github.com/KianBrose/griptape-mcp)"
MAX_CONCURRENT = 3
REQUEST_DELAY = 1.0  # seconds between requests
MAX_RETRIES = 5
MAX_RESPONSE_SIZE = 10_000_000  # 10 MB - no legitimate docs page should exceed this


async def fetch_sitemap(url: str) -> list[dict]:
    """Fetch and parse a sitemap.xml, returning list of {url, lastmod}."""
    async with httpx.AsyncClient(follow_redirects=True) as client:
        for attempt in range(MAX_RETRIES):
            resp = await client.get(url, headers={"User-Agent": USER_AGENT})
            if resp.status_code == 429:
                wait = 10 * (attempt + 1)  # 10s, 20s, 30s, 40s, 50s
                print(f"  [429] Sitemap rate limited, waiting {wait}s (attempt {attempt + 1}/{MAX_RETRIES})")
                await asyncio.sleep(wait)
                continue
            resp.raise_for_status()
            break
        else:
            resp.raise_for_status()  # Raise on final failure

    root = ET.fromstring(resp.text)
    ns = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}

    entries = []
    for url_elem in root.findall("sm:url", ns):
        loc = url_elem.find("sm:loc", ns)
        lastmod = url_elem.find("sm:lastmod", ns)
        if loc is not None and loc.text:
            entries.append({
                "url": loc.text.strip(),
                "lastmod": lastmod.text.strip() if lastmod is not None and lastmod.text else None,
            })

    return entries


async def fetch_pages(urls: list[str]) -> list[dict]:
    """Async fetch multiple pages with rate limiting and retry on 429."""
    semaphore = asyncio.Semaphore(MAX_CONCURRENT)

    async def fetch_one(client: httpx.AsyncClient, url: str) -> dict:
        async with semaphore:
            for attempt in range(MAX_RETRIES):
                try:
                    resp = await client.get(url, headers={"User-Agent": USER_AGENT})
                    if resp.status_code == 429:
                        wait = 10 * (attempt + 1)
                        print(f"  [429] Rate limited, waiting {wait}s (attempt {attempt + 1}/{MAX_RETRIES})")
                        await asyncio.sleep(wait)
                        continue
                    resp.raise_for_status()
                    content_length = int(resp.headers.get("content-length", 0))
                    if content_length > MAX_RESPONSE_SIZE:
                        return {"url": url, "html": None, "error": f"Response too large ({content_length} bytes)"}
                    text = resp.text
                    if len(text) > MAX_RESPONSE_SIZE:
                        return {"url": url, "html": None, "error": f"Response too large ({len(text)} bytes)"}
                    await asyncio.sleep(REQUEST_DELAY)
                    return {"url": url, "html": text, "error": None}
                except httpx.HTTPStatusError as e:
                    if e.response.status_code == 429 and attempt < MAX_RETRIES - 1:
                        wait = 10 * (attempt + 1)
                        print(f"  [429] Rate limited, waiting {wait}s (attempt {attempt + 1}/{MAX_RETRIES})")
                        await asyncio.sleep(wait)
                        continue
                    return {"url": url, "html": None, "error": str(e)}
                except Exception as e:
                    return {"url": url, "html": None, "error": str(e)}
            return {"url": url, "html": None, "error": "Max retries exceeded (429)"}

    async with httpx.AsyncClient(follow_redirects=True, timeout=30.0) as client:
        tasks = [fetch_one(client, url) for url in urls]
        results = await asyncio.gather(*tasks)

    return list(results)


def extract_mkdocs_content(html: str) -> dict:
    """Extract structured content from an MkDocs Material page.

    Returns:
        {
            "title": str,
            "content_text": str,
            "content_html": str,
            "breadcrumbs": list[str],
            "sections": list[{heading, level, content, anchor}],
            "code_examples": list[{language, code, context}],
        }
    """
    soup = BeautifulSoup(html, "lxml")

    # Title
    h1 = soup.find("h1")
    title = h1.get_text(strip=True) if h1 else ""
    # Remove trailing anchor character (¶) that MkDocs adds
    title = title.rstrip("¶").strip()

    # Main content area
    content_el = soup.select_one(".md-content__inner") or soup.select_one(".md-content") or soup.select_one("article")
    if not content_el:
        return {
            "title": title,
            "content_text": "",
            "content_html": "",
            "breadcrumbs": [],
            "sections": [],
            "code_examples": [],
        }

    content_html = str(content_el)
    content_text = content_el.get_text(separator="\n", strip=True)

    # Breadcrumbs
    breadcrumbs = []
    crumb_nav = soup.select_one(".md-breadcrumb") or soup.select_one("nav[aria-label='Breadcrumb']")
    if crumb_nav:
        breadcrumbs = [a.get_text(strip=True) for a in crumb_nav.find_all("a")]

    # Sections (h2, h3, h4)
    sections = []
    for heading in content_el.find_all(["h2", "h3", "h4"]):
        level = int(heading.name[1])
        heading_text = heading.get_text(strip=True).rstrip("¶").strip()
        anchor = heading.get("id", "")

        # Collect text between this heading and the next
        section_parts = []
        for sibling in heading.find_next_siblings():
            if isinstance(sibling, Tag) and sibling.name in ("h1", "h2", "h3", "h4"):
                break
            section_parts.append(sibling.get_text(separator="\n", strip=True))

        sections.append({
            "heading": heading_text,
            "level": level,
            "content": "\n".join(section_parts),
            "anchor": anchor,
        })

    # Code examples
    code_examples = []
    for pre in content_el.find_all("pre"):
        code_el = pre.find("code")
        if not code_el:
            continue

        code_text = code_el.get_text()
        if not code_text.strip():
            continue

        # Detect language from class
        language = "text"
        classes = code_el.get("class", [])
        for cls in classes:
            if cls.startswith("language-"):
                language = cls.replace("language-", "")
                break
            # Also check for highlight classes
            match = re.match(r"highlight-(\w+)", cls)
            if match:
                language = match.group(1)
                break

        # Get surrounding context (previous paragraph or heading)
        context = ""
        prev = pre.find_previous(["p", "h2", "h3", "h4"])
        if prev:
            context = prev.get_text(strip=True).rstrip("¶").strip()

        code_examples.append({
            "language": language,
            "code": code_text.strip(),
            "context": context,
        })

    return {
        "title": title,
        "content_text": content_text,
        "content_html": content_html,
        "breadcrumbs": breadcrumbs,
        "sections": sections,
        "code_examples": code_examples,
    }
