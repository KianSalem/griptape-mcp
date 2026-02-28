# Contributing

Found something wrong with the docs coverage? Want a new tool? Pull requests are genuinely welcome.

## Quick setup

```bash
git clone https://github.com/KianSalem/griptape-mcp.git
cd griptape-mcp
pip install -e ".[dev]"
```

## Before you open a PR

- If you changed the scrapers or database schema, run the validator and paste the output in your PR description:
  ```bash
  python scripts/validate_db.py src/griptape_mcp/data/griptape.db
  ```
- If you added a new MCP tool, follow the same input validation pattern in `src/griptape_mcp/server.py` (see `_validate_query`).
- That's it.

## What's most useful to contribute

- Improving search result quality
- Fixing pages where the scraper missed content
- New MCP tools (open an issue first to discuss the idea)
- Adding support for other Griptape documentation sources
