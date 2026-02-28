"""SQLite database module for Griptape documentation storage and retrieval."""

import os
import sqlite3
from contextlib import contextmanager
from importlib.resources import as_file, files
from pathlib import Path

_bundled_db_context = None
_bundled_db_path = None

SCHEMA_SQL = """
-- Documentation pages (both framework + nodes docs)
CREATE TABLE IF NOT EXISTS pages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    url TEXT NOT NULL UNIQUE,
    source TEXT NOT NULL,
    title TEXT NOT NULL,
    content TEXT,
    content_html TEXT,
    breadcrumbs TEXT,
    last_modified TEXT,
    crawled_at TEXT DEFAULT (datetime('now'))
);

-- Sections within pages (h2/h3/h4 level)
CREATE TABLE IF NOT EXISTS sections (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    page_id INTEGER NOT NULL REFERENCES pages(id) ON DELETE CASCADE,
    heading TEXT NOT NULL,
    level INTEGER,
    content TEXT,
    anchor TEXT
);

-- Code examples extracted from pages
CREATE TABLE IF NOT EXISTS code_examples (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    page_id INTEGER NOT NULL REFERENCES pages(id) ON DELETE CASCADE,
    section_id INTEGER REFERENCES sections(id) ON DELETE SET NULL,
    language TEXT,
    code TEXT NOT NULL,
    context TEXT
);

-- Griptape Nodes (structured from node docs)
CREATE TABLE IF NOT EXISTS nodes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    display_name TEXT,
    category TEXT NOT NULL,
    description TEXT,
    page_id INTEGER REFERENCES pages(id) ON DELETE SET NULL
);

-- Full-text search indexes
CREATE VIRTUAL TABLE IF NOT EXISTS pages_fts USING fts5(
    title, content, content=pages, content_rowid=id
);

CREATE VIRTUAL TABLE IF NOT EXISTS sections_fts USING fts5(
    heading, content, content=sections, content_rowid=id
);

-- Triggers to keep FTS in sync
CREATE TRIGGER IF NOT EXISTS pages_ai AFTER INSERT ON pages BEGIN
    INSERT INTO pages_fts(rowid, title, content) VALUES (new.id, new.title, new.content);
END;
CREATE TRIGGER IF NOT EXISTS pages_ad AFTER DELETE ON pages BEGIN
    INSERT INTO pages_fts(pages_fts, rowid, title, content) VALUES('delete', old.id, old.title, old.content);
END;
CREATE TRIGGER IF NOT EXISTS pages_au AFTER UPDATE ON pages BEGIN
    INSERT INTO pages_fts(pages_fts, rowid, title, content) VALUES('delete', old.id, old.title, old.content);
    INSERT INTO pages_fts(rowid, title, content) VALUES (new.id, new.title, new.content);
END;

CREATE TRIGGER IF NOT EXISTS sections_ai AFTER INSERT ON sections BEGIN
    INSERT INTO sections_fts(rowid, heading, content) VALUES (new.id, new.heading, new.content);
END;
CREATE TRIGGER IF NOT EXISTS sections_ad AFTER DELETE ON sections BEGIN
    INSERT INTO sections_fts(sections_fts, rowid, heading, content) VALUES('delete', old.id, old.heading, old.content);
END;
CREATE TRIGGER IF NOT EXISTS sections_au AFTER UPDATE ON sections BEGIN
    INSERT INTO sections_fts(sections_fts, rowid, heading, content) VALUES('delete', old.id, old.heading, old.content);
    INSERT INTO sections_fts(rowid, heading, content) VALUES (new.id, new.heading, new.content);
END;

-- Indexes for common queries
CREATE INDEX IF NOT EXISTS idx_pages_source ON pages(source);
CREATE INDEX IF NOT EXISTS idx_pages_url ON pages(url);
CREATE INDEX IF NOT EXISTS idx_sections_page_id ON sections(page_id);
CREATE INDEX IF NOT EXISTS idx_code_examples_page_id ON code_examples(page_id);
CREATE INDEX IF NOT EXISTS idx_nodes_category ON nodes(category);
CREATE INDEX IF NOT EXISTS idx_nodes_name ON nodes(name);
"""


def get_db_path() -> Path:
    """Get the path to the SQLite database.

    Checks GRIPTAPE_MCP_DB_PATH env var first, then falls back to the
    bundled database shipped with the package.
    """
    global _bundled_db_context, _bundled_db_path

    env_path = os.environ.get("GRIPTAPE_MCP_DB_PATH")
    if env_path:
        resolved = Path(env_path).resolve()
        if not resolved.suffix == ".db":
            raise ValueError(f"GRIPTAPE_MCP_DB_PATH must point to a .db file, got: {resolved}")
        if not resolved.is_file():
            raise FileNotFoundError(f"Database not found: {resolved}")
        return resolved

    if _bundled_db_path is None:
        data_ref = files("griptape_mcp").joinpath("data/griptape.db")
        _bundled_db_context = as_file(data_ref)
        _bundled_db_path = Path(_bundled_db_context.__enter__())
    return _bundled_db_path


def get_connection(db_path: Path | None = None) -> sqlite3.Connection:
    """Create a read-only SQLite connection to the documentation database."""
    path = db_path or get_db_path()
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def get_writable_connection(db_path: Path) -> sqlite3.Connection:
    """Create a writable SQLite connection (used by scrapers)."""
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db(db_path: Path) -> sqlite3.Connection:
    """Initialize a new database with the schema."""
    conn = get_writable_connection(db_path)
    conn.executescript(SCHEMA_SQL)
    conn.commit()
    return conn


@contextmanager
def read_db(db_path: Path | None = None):
    """Context manager for read-only database access."""
    conn = get_connection(db_path)
    try:
        yield conn
    finally:
        conn.close()


# --- Query helpers used by the MCP server ---


def search_pages(conn: sqlite3.Connection, query: str, source: str = "all", limit: int = 10) -> list[dict]:
    """Full-text search across documentation pages."""
    try:
        if source == "all":
            rows = conn.execute(
                """
                SELECT p.id, p.url, p.source, p.title,
                       snippet(pages_fts, 1, '>>>','<<<', '...', 40) AS snippet
                FROM pages_fts
                JOIN pages p ON p.id = pages_fts.rowid
                WHERE pages_fts MATCH ?
                ORDER BY rank
                LIMIT ?
                """,
                (query, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT p.id, p.url, p.source, p.title,
                       snippet(pages_fts, 1, '>>>','<<<', '...', 40) AS snippet
                FROM pages_fts
                JOIN pages p ON p.id = pages_fts.rowid
                WHERE pages_fts MATCH ? AND p.source = ?
                ORDER BY rank
                LIMIT ?
                """,
                (query, source, limit),
            ).fetchall()
        return [dict(row) for row in rows]
    except sqlite3.OperationalError:
        return []


def get_page_by_url(conn: sqlite3.Connection, url: str) -> dict | None:
    """Get a page by exact URL match."""
    row = conn.execute("SELECT * FROM pages WHERE url = ?", (url,)).fetchone()
    return dict(row) if row else None


def get_page_by_title(conn: sqlite3.Connection, title: str) -> dict | None:
    """Get a page by fuzzy title match."""
    row = conn.execute(
        "SELECT * FROM pages WHERE title LIKE ? LIMIT 1",
        (f"%{title}%",),
    ).fetchone()
    return dict(row) if row else None


def get_page_sections(conn: sqlite3.Connection, page_id: int) -> list[dict]:
    """Get all sections for a page."""
    rows = conn.execute(
        "SELECT * FROM sections WHERE page_id = ? ORDER BY id",
        (page_id,),
    ).fetchall()
    return [dict(row) for row in rows]


def get_page_code_examples(conn: sqlite3.Connection, page_id: int) -> list[dict]:
    """Get all code examples for a page."""
    rows = conn.execute(
        "SELECT * FROM code_examples WHERE page_id = ? ORDER BY id",
        (page_id,),
    ).fetchall()
    return [dict(row) for row in rows]


def search_nodes(conn: sqlite3.Connection, query: str, category: str | None = None, limit: int = 20) -> list[dict]:
    """Search Griptape Nodes by name/description/category.

    Handles spaced queries like 'Load Image' matching 'LoadImage'.
    """
    like = f"%{query}%"
    stripped = query.replace(" ", "")
    stripped_like = f"%{stripped}%"

    if category:
        rows = conn.execute(
            """
            SELECT n.*, p.url FROM nodes n
            LEFT JOIN pages p ON p.id = n.page_id
            WHERE n.category = ? AND (
                n.name LIKE ? OR n.display_name LIKE ? OR n.description LIKE ?
                OR REPLACE(n.name, ' ', '') LIKE ?
                OR REPLACE(n.display_name, ' ', '') LIKE ?
            )
            ORDER BY n.name
            LIMIT ?
            """,
            (category, like, like, like, stripped_like, stripped_like, limit),
        ).fetchall()
    else:
        rows = conn.execute(
            """
            SELECT n.*, p.url FROM nodes n
            LEFT JOIN pages p ON p.id = n.page_id
            WHERE n.name LIKE ? OR n.display_name LIKE ?
                OR n.description LIKE ? OR n.category LIKE ?
                OR REPLACE(n.name, ' ', '') LIKE ?
                OR REPLACE(n.display_name, ' ', '') LIKE ?
            ORDER BY n.name
            LIMIT ?
            """,
            (like, like, like, like, stripped_like, stripped_like, limit),
        ).fetchall()

    # Fallback: split multi-word queries into individual words
    if not rows and " " in query:
        seen_ids: set[int] = set()
        combined: list[sqlite3.Row] = []
        for word in query.split():
            if len(word) < 2:
                continue
            word_like = f"%{word}%"
            word_rows = conn.execute(
                """
                SELECT n.*, p.url FROM nodes n
                LEFT JOIN pages p ON p.id = n.page_id
                WHERE n.name LIKE ? OR n.display_name LIKE ? OR n.description LIKE ?
                ORDER BY n.name
                LIMIT ?
                """,
                (word_like, word_like, word_like, limit),
            ).fetchall()
            for r in word_rows:
                if r["id"] not in seen_ids:
                    seen_ids.add(r["id"])
                    combined.append(r)
        rows = combined[:limit]

    return [dict(row) for row in rows]


def get_node_by_name(conn: sqlite3.Connection, name: str) -> dict | None:
    """Get a node by name with progressive fuzzy matching.

    Tries exact match, then LIKE, then space-stripped match so that
    'Load Image' finds 'LoadImage' and vice versa.
    """
    # 1. Exact match on name or display_name
    row = conn.execute(
        "SELECT n.*, p.url, p.content FROM nodes n LEFT JOIN pages p ON p.id = n.page_id "
        "WHERE n.name = ? OR n.display_name = ? LIMIT 1",
        (name, name),
    ).fetchone()
    if row:
        return dict(row)

    # 2. LIKE match (partial)
    row = conn.execute(
        "SELECT n.*, p.url, p.content FROM nodes n LEFT JOIN pages p ON p.id = n.page_id "
        "WHERE n.name LIKE ? OR n.display_name LIKE ? LIMIT 1",
        (f"%{name}%", f"%{name}%"),
    ).fetchone()
    if row:
        return dict(row)

    # 3. Space-stripped match ('Load Image' → 'LoadImage')
    stripped = name.replace(" ", "")
    row = conn.execute(
        "SELECT n.*, p.url, p.content FROM nodes n LEFT JOIN pages p ON p.id = n.page_id "
        "WHERE REPLACE(n.name, ' ', '') LIKE ? OR REPLACE(n.display_name, ' ', '') LIKE ? LIMIT 1",
        (f"%{stripped}%", f"%{stripped}%"),
    ).fetchone()
    if row:
        return dict(row)

    return None


def list_all_categories(conn: sqlite3.Connection) -> dict:
    """List all framework sections and node categories with counts."""
    framework_rows = conn.execute(
        """
        SELECT
            CASE
                WHEN url LIKE '%/structures/%' THEN 'Structures'
                WHEN url LIKE '%/tools/%' THEN 'Tools'
                WHEN url LIKE '%/drivers/%' THEN 'Drivers'
                WHEN url LIKE '%/engines/%' THEN 'Engines'
                WHEN url LIKE '%/data/%' THEN 'Data'
                WHEN url LIKE '%/misc/%' THEN 'Misc'
                WHEN url LIKE '%/recipes/%' THEN 'Recipes'
                ELSE 'Other'
            END AS category,
            COUNT(*) AS count
        FROM pages WHERE source = 'framework'
        GROUP BY category ORDER BY count DESC
        """
    ).fetchall()

    node_rows = conn.execute(
        "SELECT category, COUNT(*) AS count FROM nodes GROUP BY category ORDER BY count DESC"
    ).fetchall()

    return {
        "framework_sections": [dict(r) for r in framework_rows],
        "node_categories": [dict(r) for r in node_rows],
    }


def search_code_examples(conn: sqlite3.Connection, query: str, limit: int = 10) -> list[dict]:
    """Search code examples by topic using a three-layer search strategy.

    Layer 1: Section FTS — matches sections linked to code examples.
    Layer 2: Page FTS — matches pages, returns their code examples (catches
             the ~67% of examples with no section_id).
    Layer 3: Code text LIKE — direct search on code content for class names,
             imports, etc.
    """
    seen: set[int] = set()
    results: list[dict] = []

    def _collect(rows: list[sqlite3.Row]) -> None:
        for row in rows:
            r = dict(row)
            ce_id = r.pop("ce_id", None)
            if ce_id is not None and ce_id in seen:
                continue
            if ce_id is not None:
                seen.add(ce_id)
            results.append(r)

    # Layer 1: section FTS → code_examples via section_id
    try:
        _collect(
            conn.execute(
                """
                SELECT ce.id AS ce_id, ce.language, ce.code, ce.context,
                       s.heading, p.title, p.url
                FROM sections_fts
                JOIN sections s ON s.id = sections_fts.rowid
                JOIN code_examples ce ON ce.section_id = s.id
                JOIN pages p ON p.id = ce.page_id
                WHERE sections_fts MATCH ?
                ORDER BY rank
                LIMIT ?
                """,
                (query, limit),
            ).fetchall()
        )
    except sqlite3.OperationalError:
        pass

    # Layer 2: page FTS → code_examples via page_id
    if len(results) < limit:
        try:
            _collect(
                conn.execute(
                    """
                    SELECT ce.id AS ce_id, ce.language, ce.code, ce.context,
                           s.heading, p.title, p.url
                    FROM pages_fts
                    JOIN pages p ON p.id = pages_fts.rowid
                    JOIN code_examples ce ON ce.page_id = p.id
                    LEFT JOIN sections s ON s.id = ce.section_id
                    WHERE pages_fts MATCH ?
                    ORDER BY rank
                    LIMIT ?
                    """,
                    (query, limit - len(results)),
                ).fetchall()
            )
        except sqlite3.OperationalError:
            pass

    # Layer 3: direct LIKE search on code text and context
    if len(results) < limit:
        like_pattern = f"%{query}%"
        _collect(
            conn.execute(
                """
                SELECT ce.id AS ce_id, ce.language, ce.code, ce.context,
                       s.heading, p.title, p.url
                FROM code_examples ce
                JOIN pages p ON p.id = ce.page_id
                LEFT JOIN sections s ON s.id = ce.section_id
                WHERE ce.code LIKE ? OR ce.context LIKE ?
                LIMIT ?
                """,
                (like_pattern, like_pattern, limit - len(results)),
            ).fetchall()
        )

    return results[:limit]
