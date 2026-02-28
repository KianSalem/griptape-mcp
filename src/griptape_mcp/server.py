"""MCP server exposing Griptape documentation to LLMs."""

import json

from mcp.server.fastmcp import FastMCP

from griptape_mcp.db import (
    get_connection,
    get_node_by_name,
    get_page_by_title,
    get_page_by_url,
    get_page_code_examples,
    get_page_sections,
    list_all_categories,
    search_code_examples,
    search_nodes as db_search_nodes,
    search_pages,
)

mcp = FastMCP("griptape-docs")

_conn = None

MAX_QUERY_LENGTH = 1000


def _get_conn():
    global _conn
    if _conn is None:
        _conn = get_connection()
    return _conn


def _validate_query(query: str) -> str | None:
    """Validate a search query. Returns an error message or None if valid."""
    if not query or not query.strip():
        return "Error: query must be a non-empty string."
    if len(query) > MAX_QUERY_LENGTH:
        return f"Error: query too long (max {MAX_QUERY_LENGTH} characters)."
    return None


@mcp.tool()
def search_docs(query: str, source: str = "all") -> str:
    """Search across all Griptape documentation.

    Full-text search of the Griptape Framework docs and Griptape Nodes docs.
    Returns the top matching pages with title, URL, and a text snippet.

    Args:
        query: Search terms (e.g. "RAG pipeline", "Agent memory", "image node")
        source: Filter results - "framework", "nodes", or "all" (default)
    """
    if err := _validate_query(query):
        return err
    if source not in ("framework", "nodes", "all"):
        return "Error: source must be 'framework', 'nodes', or 'all'."
    results = search_pages(_get_conn(), query, source)
    if not results:
        return f"No results found for '{query}'"

    lines = [f"Found {len(results)} result(s) for '{query}':\n"]
    for r in results:
        lines.append(f"- **{r['title']}** [{r['source']}]")
        lines.append(f"  URL: {r['url']}")
        if r.get("snippet"):
            lines.append(f"  {r['snippet']}")
        lines.append("")
    return "\n".join(lines)


@mcp.tool()
def get_page(url_or_title: str) -> str:
    """Get the full content of a specific documentation page.

    Retrieves the complete text content and code examples for a page.
    You can pass either the full URL or a partial title to match.

    Args:
        url_or_title: Full URL (e.g. "https://docs.griptape.ai/stable/griptape-framework/structures/agents/") or partial title (e.g. "Agents")
    """
    if not url_or_title or not url_or_title.strip():
        return "Error: url_or_title must be a non-empty string."
    if len(url_or_title) > MAX_QUERY_LENGTH:
        return f"Error: input too long (max {MAX_QUERY_LENGTH} characters)."
    conn = _get_conn()

    if url_or_title.startswith("http"):
        page = get_page_by_url(conn, url_or_title)
    else:
        page = get_page_by_title(conn, url_or_title)

    if not page:
        return f"No page found matching '{url_or_title}'"

    sections = get_page_sections(conn, page["id"])
    examples = get_page_code_examples(conn, page["id"])

    lines = [
        f"# {page['title']}",
        f"Source: {page['source']} | URL: {page['url']}",
        "",
    ]

    if page.get("content"):
        lines.append(page["content"])
        lines.append("")

    if sections:
        lines.append("## Sections")
        for s in sections:
            prefix = "#" * (s["level"] + 1) if s.get("level") else "##"
            lines.append(f"\n{prefix} {s['heading']}")
            if s.get("content"):
                lines.append(s["content"])

    if examples:
        lines.append("\n## Code Examples")
        for ex in examples:
            lang = ex.get("language", "python")
            if ex.get("context"):
                lines.append(f"\n{ex['context']}")
            lines.append(f"\n```{lang}")
            lines.append(ex["code"])
            lines.append("```")

    return "\n".join(lines)


@mcp.tool()
def search_griptape_nodes(query: str, category: str | None = None) -> str:
    """Search Griptape Nodes by name, description, or category.

    Griptape Nodes is a visual workflow builder with 120+ nodes for
    images, video, audio, text, agents, and more.

    Args:
        query: Search terms (e.g. "load image", "transcribe", "agent")
        category: Optional category filter (e.g. "Image", "Video", "Text", "Audio", "Agents", "Config")
    """
    if err := _validate_query(query):
        return err
    results = db_search_nodes(_get_conn(), query, category)
    if not results:
        msg = f"No nodes found for '{query}'"
        if category:
            msg += f" in category '{category}'"
        return msg

    lines = [f"Found {len(results)} node(s):\n"]
    for n in results:
        lines.append(f"- **{n.get('display_name') or n['name']}** [{n['category']}]")
        if n.get("description"):
            lines.append(f"  {n['description']}")
        if n.get("url"):
            lines.append(f"  Docs: {n['url']}")
        lines.append("")
    return "\n".join(lines)


@mcp.tool()
def get_node_details(node_name: str) -> str:
    """Get full documentation for a specific Griptape Node.

    Returns the complete description, configuration, inputs/outputs,
    and any code examples for the node.

    Args:
        node_name: Name of the node (e.g. "Load Image", "Create Agent", "Transcribe Audio")
    """
    if err := _validate_query(node_name):
        return err
    conn = _get_conn()
    node = get_node_by_name(conn, node_name)

    if not node:
        return f"No node found matching '{node_name}'. Try search_griptape_nodes() to find available nodes."

    lines = [
        f"# {node.get('display_name') or node['name']}",
        f"Category: {node['category']}",
    ]

    if node.get("description"):
        lines.append(f"\n{node['description']}")

    if node.get("url"):
        lines.append(f"\nDocs URL: {node['url']}")

    if node.get("content"):
        lines.append(f"\n## Full Documentation\n{node['content']}")

    if node.get("page_id"):
        examples = get_page_code_examples(conn, node["page_id"])
        if examples:
            lines.append("\n## Code Examples")
            for ex in examples:
                lang = ex.get("language", "python")
                if ex.get("context"):
                    lines.append(f"\n{ex['context']}")
                lines.append(f"\n```{lang}")
                lines.append(ex["code"])
                lines.append("```")

    return "\n".join(lines)


@mcp.tool()
def list_categories() -> str:
    """List all Griptape Framework sections and Node categories.

    Shows the available documentation areas and how many pages/nodes
    are in each, so you know what to search for.
    """
    cats = list_all_categories(_get_conn())

    lines = ["# Griptape Framework Sections\n"]
    for c in cats["framework_sections"]:
        lines.append(f"- {c['category']}: {c['count']} page(s)")

    lines.append("\n# Griptape Node Categories\n")
    for c in cats["node_categories"]:
        lines.append(f"- {c['category']}: {c['count']} node(s)")

    return "\n".join(lines)


@mcp.tool()
def get_code_examples(topic: str) -> str:
    """Search for code examples related to a topic.

    Finds code snippets from the documentation that match your query.
    Useful for finding working examples of Griptape patterns.

    Args:
        topic: What you want examples of (e.g. "RAG pipeline", "custom tool", "workflow")
    """
    if err := _validate_query(topic):
        return err
    results = search_code_examples(_get_conn(), topic)
    if not results:
        return f"No code examples found for '{topic}'. Try a broader search term."

    lines = [f"Found {len(results)} code example(s) for '{topic}':\n"]
    for r in results:
        lines.append(f"### From: {r['title']} > {r['heading']}")
        if r.get("url"):
            lines.append(f"URL: {r['url']}")
        lang = r.get("language", "python")
        lines.append(f"\n```{lang}")
        lines.append(r["code"])
        lines.append("```\n")

    return "\n".join(lines)
