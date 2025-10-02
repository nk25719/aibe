import os, sqlite3
from pathlib import Path
from typing import List, Dict, Any

DB_PATH = Path(os.getenv("PARTS_DB_PATH", "parts.db")).resolve()

def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def search_parts(q: str, limit: int = 20) -> List[Dict[str, Any]]:
    q = (q or "").strip()
    with get_conn() as conn:
        rows = []
        if q:
            try:
                rows = conn.execute(
                    """
                    SELECT rowid AS id, part_number, alternate_pn, description, equipment1, brand, eq_category, natural_description
                    FROM parts
                    WHERE rowid IN (SELECT rowid FROM parts_fts WHERE parts_fts MATCH ?)
                    LIMIT ?
                    """, (q, limit)
                ).fetchall()
            except sqlite3.OperationalError:
                rows = []
            if not rows:
                like = f"%{q}%"
                rows = conn.execute(
                    """
                    SELECT rowid AS id, part_number, alternate_pn, description, equipment1, brand, eq_category, natural_description
                    FROM parts
                    WHERE part_number LIKE ? OR description LIKE ? OR equipment1 LIKE ? OR brand LIKE ?
                    LIMIT ?
                    """, (like, like, like, like, limit)
                ).fetchall()
        return [dict(r) for r in rows]
