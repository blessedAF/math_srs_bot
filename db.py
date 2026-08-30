"""
Слой работы с SQLite базой карточек.
"""

import sqlite3
from datetime import date
from pathlib import Path

DB_PATH = Path(__file__).parent / "cards.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS cards (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    front TEXT NOT NULL,
    back TEXT NOT NULL,
    topic TEXT DEFAULT '',
    ease REAL NOT NULL DEFAULT 2.5,
    interval INTEGER NOT NULL DEFAULT 0,
    repetitions INTEGER NOT NULL DEFAULT 0,
    next_review DATE NOT NULL DEFAULT CURRENT_DATE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with get_conn() as conn:
        conn.execute(SCHEMA)


def add_card(user_id: int, front: str, back: str, topic: str = "") -> int:
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO cards (user_id, front, back, topic, next_review) "
            "VALUES (?, ?, ?, ?, ?)",
            (user_id, front, back, topic, date.today().isoformat()),
        )
        return cur.lastrowid


def get_due_cards(user_id: int, limit: int = 20) -> list[sqlite3.Row]:
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM cards WHERE user_id = ? AND next_review <= ? "
            "ORDER BY next_review ASC LIMIT ?",
            (user_id, date.today().isoformat(), limit),
        ).fetchall()


def get_card(card_id: int) -> sqlite3.Row | None:
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM cards WHERE id = ?", (card_id,)
        ).fetchone()


def update_card_review(
    card_id: int, ease: float, interval: int, repetitions: int, next_review: date
) -> None:
    with get_conn() as conn:
        conn.execute(
            "UPDATE cards SET ease = ?, interval = ?, repetitions = ?, "
            "next_review = ? WHERE id = ?",
            (ease, interval, repetitions, next_review.isoformat(), card_id),
        )


def count_due(user_id: int) -> int:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT COUNT(*) as c FROM cards WHERE user_id = ? AND next_review <= ?",
            (user_id, date.today().isoformat()),
        ).fetchone()
        return row["c"]


def count_total(user_id: int) -> int:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT COUNT(*) as c FROM cards WHERE user_id = ?", (user_id,)
        ).fetchone()
        return row["c"]


def delete_card(card_id: int, user_id: int) -> bool:
    with get_conn() as conn:
        cur = conn.execute(
            "DELETE FROM cards WHERE id = ? AND user_id = ?", (card_id, user_id)
        )
        return cur.rowcount > 0


def list_cards(user_id: int, limit: int = 50) -> list[sqlite3.Row]:
    with get_conn() as conn:
        return conn.execute(
            "SELECT id, front, topic FROM cards WHERE user_id = ? "
            "ORDER BY topic, front LIMIT ?",
            (user_id, limit),
        ).fetchall()


def list_topics(user_id: int) -> list[str]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT DISTINCT topic FROM cards WHERE user_id = ? AND topic != ''",
            (user_id,),
        ).fetchall()
        return [r["topic"] for r in rows]
