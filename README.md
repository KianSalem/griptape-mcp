<p align="center">
  <h1 align="center">griptape-mcp</h1>
  <p align="center">
    Stop letting your AI guess at Griptape APIs.<br/>
    Give it the actual docs.
  </p>
</p>

<p align="center">
  <a href="https://pypi.org/project/griptape-mcp/"><img src="https://img.shields.io/pypi/v/griptape-mcp?color=blue&logo=pypi&logoColor=white" alt="PyPI"></a>
  <a href="https://pypi.org/project/griptape-mcp/"><img src="https://img.shields.io/pypi/pyversions/griptape-mcp?logo=python&logoColor=white" alt="Python 3.10+"></a>
  <a href="https://github.com/KianSalem/griptape-mcp/blob/main/LICENSE"><img src="https://img.shields.io/badge/license-MIT-green" alt="MIT License"></a>
  <br/>
  <a href="https://modelcontextprotocol.io"><img src="https://img.shields.io/badge/MCP-compatible-8A2BE2" alt="MCP Compatible"></a>
  <img src="https://img.shields.io/badge/docker-ready-2496ED?logo=docker&logoColor=white" alt="Docker">
  <a href="https://github.com/KianSalem/griptape-mcp/stargazers"><img src="https://img.shields.io/github/stars/KianSalem/griptape-mcp?style=social" alt="GitHub Stars"></a>
</p>

---

Your AI keeps hallucinating Griptape method names. You ask it to build an Agent, it writes confident code that doesn't exist. You paste the error. It apologizes and writes different wrong code.

**griptape-mcp** fixes this. It ships the entire Griptape documentation — 84 framework pages, 125 nodes, 714 real code examples — as a pre-built SQLite database your AI can actually search. No hallucinations. No outdated training data. No API keys.

> Install it once. Your AI figures out the rest.

### What's inside the box

| | |
|---|---|
| 📚 **84 framework pages** | Agents, Pipelines, Workflows, Tools, Drivers, Engines, RAG, and more |
| 🧩 **125 visual nodes** | Every node in Griptape Nodes across 17 categories |
| 🔍 **Full-text search** | SQLite FTS5 — fast, typo-tolerant, ranked by relevance |
| 💻 **714 code examples** | Real, working snippets pulled straight from the official docs |
| 📦 **Zero runtime deps** | Pre-built database ships with the package. No scraping at query time. |

---

## What it looks like

Once connected, your AI uses the tools automatically. No prompting required.

**You:** How do I add conversation memory to an Agent?

**Claude:** *(calls `search_docs("conversation memory")`)* Found it. Here's the pattern:

```python
from griptape.structures import Agent
from griptape.memory.structure import ConversationMemory

agent = Agent(conversation_memory=ConversationMemory())
```

No guessing. No hallucinated imports. Just the actual docs.

---

## Get running in 60 seconds

**Step 1 — Install**

```bash
pip install griptape-mcp
```

**Step 2 — Connect your client**

<details>
<summary><b>Claude Desktop</b></summary>

Add to your config file:

- **macOS**: `~/Library/Application Support/Claude/claude_desktop_config.json`
- **Windows**: `%APPDATA%\Claude\claude_desktop_config.json`
- **Linux**: `~/.config/Claude/claude_desktop_config.json`

```json
{
  "mcpServers": {
    "griptape-docs": {
      "command": "griptape-mcp"
    }
  }
}
```

Restart Claude Desktop. Look for the 🔨 icon — that means tools are loaded.

</details>

<details>
<summary><b>Claude Code (one command)</b></summary>

```bash
claude mcp add griptape-docs griptape-mcp
```

Done. That's genuinely it.

Or add manually to your MCP settings:

```json
{
  "mcpServers": {
    "griptape-docs": {
      "command": "griptape-mcp"
    }
  }
}
```

</details>

<details>
<summary><b>Docker</b></summary>

```bash
docker build -t griptape-mcp .
```

```json
{
  "mcpServers": {
    "griptape-docs": {
      "command": "docker",
      "args": ["run", "-i", "--rm", "griptape-mcp"]
    }
  }
}
```

</details>

**Step 3 — Ask anything**

> *"How do I create a Griptape Agent with custom tools?"*
>
> *"What's the difference between a Pipeline and a Workflow?"*
>
> *"Show me a RAG pipeline example in Griptape"*
>
> *"What image processing nodes does Griptape Nodes have?"*
>
> *"Find me code examples for conversation memory"*

---

## What your AI can look up

Six tools your AI assistant can call, all read-only and fast:

| Tool | What it does |
|------|-------------|
| `search_docs` | Full-text search across all Griptape documentation. Filter by `"framework"`, `"nodes"`, or `"all"`. |
| `get_page` | Pull the complete content of any doc page by URL or title. Includes sections and code blocks. |
| `search_griptape_nodes` | Find nodes by name, description, or category. Returns descriptions and doc links. |
| `get_node_details` | Deep dive on a single node — full description, config, and code examples. |
| `list_categories` | Browse what's available: 8 framework sections + 17 node categories with counts. |
| `get_code_examples` | Search for working code snippets by topic. Great for "show me how to..." questions. |

---

## How it works

The architecture is intentionally boring — a SQLite file shipped inside the pip package, opened read-only at query time. No network calls happen during conversations.

```
┌──────────────────────────────────────────────────────────┐
│                    At build time                         │
│                                                          │
│  docs.griptape.ai ──┐                                   │
│                      ├──▶ scraper ──▶ SQLite + FTS5      │
│  GitHub markdown ────┘              (shipped in package) │
└──────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────┐
│                    At query time                         │
│                                                          │
│  Claude / AI ◀──stdio──▶ griptape-mcp ◀──▶ SQLite (ro)  │
│                                                          │
│  No network calls. No API keys. Just a local subprocess. │
└──────────────────────────────────────────────────────────┘
```

1. **Scrapers** crawl `docs.griptape.ai` (via sitemap) and Griptape Nodes (via GitHub markdown)
2. Content gets parsed into structured pieces: titles, headings, code blocks, node metadata
3. Everything lands in a **SQLite database** with FTS5 full-text search indexes
4. That database **ships inside the pip package** — nothing to fetch at runtime
5. The MCP server opens it read-only and exposes 6 search/lookup tools over stdio
6. A **nightly GitHub Actions job** re-scrapes and rebuilds to stay current

---

## Node coverage

125 nodes across 17 categories:

| Category | Count | | Category | Count |
|----------|------:|-|----------|------:|
| Image | 32 | | Lists | 17 |
| Video | 18 | | Text | 12 |
| Config | 9 | | Number | 7 |
| Tools | 7 | | JSON | 5 |
| Dict | 4 | | Audio | 3 |
| Execution | 3 | | Rules | 2 |
| Adv. Media Library | 2 | | Agents | 1 |
| Convert | 1 | | 3D | 1 |

---

## Development

### Setup

```bash
git clone https://github.com/KianSalem/griptape-mcp.git
cd griptape-mcp
pip install -e ".[dev]"
```

### Rebuild the docs database

```bash
cd scripts
python build_db.py
```

This scrapes both documentation sources and writes to `src/griptape_mcp/data/griptape.db`. If the website rate-limits you, the build script automatically falls back to scraping GitHub markdown.

### Run against a local database

```bash
GRIPTAPE_MCP_DB_PATH=./griptape.db griptape-mcp
```

### Validate

```bash
python scripts/validate_db.py src/griptape_mcp/data/griptape.db
```

```
  [PASS] Framework pages > 10 - got 84
  [PASS] Nodes pages > 10 - got 164
  [PASS] Nodes extracted > 20 - got 125
  [PASS] Sections > 50 - got 2263
  [PASS] Code examples > 10 - got 714
  [PASS] FTS search works - 'agent' matched 79 pages
  [PASS] Multiple node categories - got 17
  ALL CHECKS PASSED
```

### Project structure

```
griptape-mcp/
├── src/griptape_mcp/
│   ├── server.py               ← MCP tools (FastMCP)
│   ├── db.py                   ← Schema, queries, FTS
│   ├── __main__.py             ← Entry point
│   └── data/griptape.db        ← Pre-built database (14 MB)
├── scripts/
│   ├── build_db.py             ← Orchestrates full rebuild
│   ├── scrape_framework.py     ← Crawls docs.griptape.ai
│   ├── scrape_nodes.py         ← Crawls docs.griptapenodes.com
│   ├── scrape_nodes_github.py  ← GitHub fallback scraper
│   └── validate_db.py          ← Post-build validation
├── .github/workflows/
│   ├── rebuild-db.yml          ← Nightly CI rebuild
│   └── publish.yml             ← PyPI publish on release
├── Dockerfile
└── pyproject.toml
```

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

---

## License

MIT — do whatever you want with it.

---

<p align="center">
  <sub>Built because reading docs is great, but having your AI read them <i>for</i> you is better.</sub>
</p>
