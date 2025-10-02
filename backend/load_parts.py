import re, json, sqlite3, pandas as pd, numpy as np
from pathlib import Path
import os

SRC = Path(os.getenv("PARTS_XLSX","AIBE Parts list.xlsx"))
OUT = Path(os.getenv("PARTS_DB_PATH","parts.db"))

def norm(s: str) -> str:
    s = str(s).strip().lower()
    s = re.sub(r"\s+","_",s)
    s = re.sub(r"[^a-z0-9_]","",s)
    s = re.sub(r"_+","_",s).strip("_")
    return s or "col"

def main():
    if not SRC.exists():
        raise SystemExit(f"Parts Excel not found: {SRC.resolve()}")
    df = pd.read_excel(SRC)

    # normalize/dedupe columns
    seen=set(); cols=[]
    for c in df.columns:
        base = norm(c); name=base; k=2
        while name in seen: name=f"{base}_{k}"; k+=1
        seen.add(name); cols.append(name)
    df.columns = cols

    # trim strings
    for c in df.columns:
        if df[c].dtype==object: df[c]=df[c].astype(str).str.strip()
    df = df.replace({np.nan: None})

    if OUT.exists(): OUT.unlink()
    conn = sqlite3.connect(OUT)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.execute("PRAGMA foreign_keys=ON;")

    # Surrogate PK
    cols_sql = ["row_id INTEGER PRIMARY KEY AUTOINCREMENT"]
    for c in df.columns: cols_sql.append(f"{c} TEXT")
    conn.execute(f"CREATE TABLE parts ({', '.join(cols_sql)});")

    # Insert
    conn.executemany(
        f"INSERT INTO parts ({', '.join(df.columns)}) VALUES ({','.join(['?']*len(df.columns))})",
        df.where(pd.notnull(df), None).values.tolist()
    )

    # Helpful indexes
    for key in ("part_number","partnumber","part_no","sku","id","code","item_code","description","equipment1","brand"):
        if key in df.columns:
            conn.execute(f"CREATE INDEX IF NOT EXISTS idx_parts_{key} ON parts({key});")

    # FTS
    text_cols = [c for c in df.columns][:8]  # up to 8
    if text_cols:
        conn.execute(f"CREATE VIRTUAL TABLE parts_fts USING fts5({', '.join(text_cols)}, content='parts');")
        conn.execute(f"INSERT INTO parts_fts ({', '.join(text_cols)}) SELECT {', '.join(text_cols)} FROM parts;")

    conn.commit(); conn.close()
    print(f"[OK] wrote {OUT.resolve()} with {len(df)} rows and FTS on {', '.join(text_cols)}")

if __name__=="__main__":
    main()
