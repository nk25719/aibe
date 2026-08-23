import sqlite3
from typing import Any

from app.config import settings


def get_legacy_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(settings.legacy_parts_db_path)
    conn.row_factory = sqlite3.Row
    return conn


def search_parts(q: str, limit: int = 20, offset: int = 0) -> list[dict[str, Any]]:
    query = (q or "").strip()
    with get_legacy_conn() as conn:
        rows = []
        if query:
            try:
                rows = conn.execute(
                    """
                    SELECT rowid AS id, part_number, alternate_pn, description, equipment1, brand, eq_category, natural_description
                    FROM parts
                    WHERE rowid IN (SELECT rowid FROM parts_fts WHERE parts_fts MATCH ?)
                    LIMIT ? OFFSET ?
                    """,
                    (query, limit, offset),
                ).fetchall()
            except sqlite3.OperationalError:
                rows = []
            if not rows:
                like = f"%{query}%"
                rows = conn.execute(
                    """
                    SELECT rowid AS id, part_number, alternate_pn, description, equipment1, brand, eq_category, natural_description
                    FROM parts
                    WHERE part_number LIKE ? OR alternate_pn LIKE ? OR description LIKE ? OR equipment1 LIKE ? OR brand LIKE ?
                    LIMIT ? OFFSET ?
                    """,
                    (like, like, like, like, like, limit, offset),
                ).fetchall()
        return [dict(r) for r in rows]
