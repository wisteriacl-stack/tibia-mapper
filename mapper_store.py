import sqlite3

from app_paths import RUNTIME_ROOT

DATA_DIR = RUNTIME_ROOT / "data"
DB_PATH = DATA_DIR / "mapper.db"
DATA_DIR.mkdir(parents=True, exist_ok=True)


def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS map_points (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            label TEXT NOT NULL,
            x INTEGER,
            y INTEGER,
            z INTEGER,
            note TEXT,
            screenshot TEXT
        )
        """
    )
    conn.commit()
    conn.close()


def add_point(label, x=None, y=None, z=None, note=None, screenshot=None):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.execute(
        """
        INSERT INTO map_points (label, x, y, z, note, screenshot)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (label, x, y, z, note, screenshot),
    )
    point_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return point_id


def list_points(limit=100):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """
        SELECT id, created_at, label, x, y, z, note, screenshot
        FROM map_points
        ORDER BY id DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def delete_point(point_id):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.execute("DELETE FROM map_points WHERE id = ?", (point_id,))
    conn.commit()
    deleted = cursor.rowcount > 0
    conn.close()
    return deleted
