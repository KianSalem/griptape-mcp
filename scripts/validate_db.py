"""Post-build validation for the documentation database."""

import sqlite3
import sys
from pathlib import Path


def validate(db_path: Path) -> bool:
    """Run validation checks on the built database."""
    if not db_path.exists():
        print(f"FAIL: Database not found: {db_path}")
        return False

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    passed = True

    def check(name: str, condition: bool, detail: str = ""):
        nonlocal passed
        status = "PASS" if condition else "FAIL"
        if not condition:
            passed = False
        msg = f"  [{status}] {name}"
        if detail:
            msg += f" - {detail}"
        print(msg)

    print(f"Validating: {db_path}\n")

    # Check tables exist
    tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
    for table in ["pages", "sections", "code_examples", "nodes"]:
        check(f"Table '{table}' exists", table in tables)

    # Check page counts
    fw_count = conn.execute("SELECT COUNT(*) FROM pages WHERE source='framework'").fetchone()[0]
    nodes_count = conn.execute("SELECT COUNT(*) FROM pages WHERE source='nodes'").fetchone()[0]
    check("Framework pages > 10", fw_count > 10, f"got {fw_count}")
    check("Nodes pages > 10", nodes_count > 10, f"got {nodes_count}")

    # Check nodes were extracted
    node_count = conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]
    check("Nodes extracted > 20", node_count > 20, f"got {node_count}")

    # Check sections exist
    section_count = conn.execute("SELECT COUNT(*) FROM sections").fetchone()[0]
    check("Sections > 50", section_count > 50, f"got {section_count}")

    # Check code examples exist
    example_count = conn.execute("SELECT COUNT(*) FROM code_examples").fetchone()[0]
    check("Code examples > 10", example_count > 10, f"got {example_count}")

    # Check no empty titles
    empty_titles = conn.execute("SELECT COUNT(*) FROM pages WHERE title = '' OR title IS NULL").fetchone()[0]
    check("No empty page titles", empty_titles == 0, f"got {empty_titles} empty")

    # Check FTS works
    try:
        fts_result = conn.execute("SELECT COUNT(*) FROM pages_fts WHERE pages_fts MATCH 'agent'").fetchone()[0]
        check("FTS search works", fts_result >= 0, f"'agent' matched {fts_result} pages")
    except Exception as e:
        check("FTS search works", False, str(e))

    # Check node categories
    categories = conn.execute("SELECT DISTINCT category FROM nodes ORDER BY category").fetchall()
    cat_list = [r[0] for r in categories]
    check("Multiple node categories", len(cat_list) > 3, f"got {len(cat_list)}: {', '.join(cat_list)}")

    conn.close()

    print(f"\n{'ALL CHECKS PASSED' if passed else 'SOME CHECKS FAILED'}")
    return passed


if __name__ == "__main__":
    db_path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("griptape.db")
    success = validate(db_path)
    sys.exit(0 if success else 1)
