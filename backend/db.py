"""Tiny SQLite layer for products. To use Supabase/Firebase later, only this file changes."""
import sqlite3
from contextlib import contextmanager

from . import config

GENDERS = ("men", "women", "unisex")


@contextmanager
def conn():
    c = sqlite3.connect(config.DB_PATH)
    c.row_factory = sqlite3.Row
    try:
        yield c
        c.commit()
    finally:
        c.close()


def init_db() -> None:
    with conn() as c:
        c.execute("""CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            price REAL NOT NULL,
            category TEXT NOT NULL,
            gender TEXT NOT NULL,
            image TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP)""")


def _row(r) -> dict:
    d = dict(r)
    d["image_url"] = f"/product-images/{d['image']}"
    return d


def list_products(category: str | None = None, gender: str | None = None) -> list[dict]:
    sql, args = "SELECT * FROM products WHERE 1=1", []
    if category:
        sql += " AND category = ?"; args.append(category.lower())
    if gender:
        # "unisex" items show up under both men and women
        sql += " AND (gender = ? OR gender = 'unisex')"; args.append(gender.lower())
    with conn() as c:
        return [_row(r) for r in c.execute(sql + " ORDER BY id DESC", args)]


def get_product(pid: int) -> dict | None:
    with conn() as c:
        r = c.execute("SELECT * FROM products WHERE id = ?", (pid,)).fetchone()
    return _row(r) if r else None


def add_product(name, price, category, gender, image) -> dict:
    with conn() as c:
        cur = c.execute("INSERT INTO products (name, price, category, gender, image) VALUES (?,?,?,?,?)",
                        (name, price, category, gender, image))
        pid = cur.lastrowid
    return get_product(pid)


def update_product(pid, name, price, category, gender, image) -> dict | None:
    with conn() as c:
        c.execute("UPDATE products SET name=?, price=?, category=?, gender=?, image=? WHERE id=?",
                  (name, price, category, gender, image, pid))
    return get_product(pid)


def delete_product(pid: int) -> None:
    with conn() as c:
        c.execute("DELETE FROM products WHERE id = ?", (pid,))
