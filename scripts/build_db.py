"""Orchestrate a full database build: init schema, scrape both doc sites, validate."""

import asyncio
import shutil
import sys
from pathlib import Path

# Add parent dir so we can import the package
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from griptape_mcp.db import init_db

from scrape_framework import scrape as scrape_framework
from scrape_nodes import scrape as scrape_nodes
from scrape_nodes_github import scrape as scrape_nodes_github


async def build(output_path: Path):
    # Remove old DB if it exists
    if output_path.exists():
        output_path.unlink()
        print(f"Removed existing database: {output_path}")

    # Initialize schema
    print(f"Initializing database: {output_path}")
    conn = init_db(output_path)
    conn.close()

    # Scrape framework docs from the website
    fw_stats = await scrape_framework(output_path)

    # Scrape nodes docs - try website first, fall back to GitHub markdown
    try:
        nodes_stats = await scrape_nodes(output_path)
        if nodes_stats["errors"] > nodes_stats["pages"]:
            print("[build] Too many errors from website, falling back to GitHub source...")
            nodes_stats = await scrape_nodes_github(output_path)
    except Exception as e:
        print(f"[build] Website scrape failed ({e}), falling back to GitHub source...")
        nodes_stats = await scrape_nodes_github(output_path)

    # Print summary
    total_pages = fw_stats["pages"] + nodes_stats["pages"]
    total_sections = fw_stats["sections"] + nodes_stats["sections"]
    total_examples = fw_stats["code_examples"] + nodes_stats["code_examples"]
    total_errors = fw_stats["errors"] + nodes_stats["errors"]

    print("\n" + "=" * 60)
    print("BUILD COMPLETE")
    print("=" * 60)
    print(f"  Total pages:         {total_pages}")
    print(f"  Total sections:      {total_sections}")
    print(f"  Total code examples: {total_examples}")
    print(f"  Total nodes:         {nodes_stats.get('nodes', 0)}")
    print(f"  Total errors:        {total_errors}")
    print(f"  Database size:       {output_path.stat().st_size / 1024 / 1024:.1f} MB")
    print(f"  Output:              {output_path}")

    # Copy to package data directory
    package_data_dir = Path(__file__).resolve().parent.parent / "src" / "griptape_mcp" / "data"
    package_data_dir.mkdir(parents=True, exist_ok=True)
    dest = package_data_dir / "griptape.db"
    shutil.copy2(output_path, dest)
    print(f"  Copied to:           {dest}")

    return total_errors == 0


if __name__ == "__main__":
    output = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("griptape.db")
    success = asyncio.run(build(output))
    sys.exit(0 if success else 1)
