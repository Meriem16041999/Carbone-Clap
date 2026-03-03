import sqlite3
import json

class SQLiteCache:
    def __init__(self, path="cache.sqlite"):
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS distances (
                key TEXT PRIMARY KEY,
                value REAL,
                meta TEXT
            )
        """)
        self.conn.commit()

    def get(self, key: str):
        cur = self.conn.execute("SELECT value FROM distances WHERE key=?", (key,))
        row = cur.fetchone()
        return row[0] if row else None

    def set(self, key: str, value: float, meta: dict = None):
        self.conn.execute("REPLACE INTO distances (key, value, meta) VALUES (?, ?, ?)",
                          (key, value if value is None else float(value), json.dumps(meta or {})))
        self.conn.commit()
