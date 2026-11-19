"""Tiny SQLite layer for products. To use Supabase/Firebase later, only this file changes."""
import sqlite3
from contextlib import contextmanager

import httpx

from . import config, storage

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


def _sb(method: str, params: dict | None = None, json=None, prefer: str | None = None):
    """Supabase REST call on the products table. Returns the parsed JSON (or [])."""
    h = {"apikey": config.SUPABASE_KEY, "Authorization": f"Bearer {config.SUPABASE_KEY}"}
    if prefer:
        h["Prefer"] = prefer
    r = httpx.request(method, f"{config.SUPABASE_URL}/rest/v1/products", headers=h, params=params, json=json, timeout=30)
    r.raise_for_status()
    return r.json() if r.content else []


def init_db() -> None:
    if config.USE_SUPABASE:
        return  # table is created in the Supabase SQL editor
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
    d["image_url"] = storage.image_url(d["image"])
    return d


def list_products(category: str | None = None, gender: str | None = None) -> list[dict]:
    if config.USE_SUPABASE:
        params = {"select": "*", "order": "id.desc"}
        if category:
            params["category"] = f"eq.{category.lower()}"
        if gender:  # "unisex" items show up under both men and women
            params["or"] = f"(gender.eq.{gender.lower()},gender.eq.unisex)"
        return [_row(r) for r in _sb("GET", params)]
    sql, args = "SELECT * FROM products WHERE 1=1", []
    if category:
        sql += " AND category = ?"; args.append(category.lower())
    if gender:
        # "unisex" items show up under both men and women
        sql += " AND (gender = ? OR gender = 'unisex')"; args.append(gender.lower())
    with conn() as c:
        return [_row(r) for r in c.execute(sql + " ORDER BY id DESC", args)]


def get_product(pid: int) -> dict | None:
    if config.USE_SUPABASE:
        rows = _sb("GET", {"select": "*", "id": f"eq.{pid}"})
        return _row(rows[0]) if rows else None
    with conn() as c:
        r = c.execute("SELECT * FROM products WHERE id = ?", (pid,)).fetchone()
    return _row(r) if r else None


def add_product(name, price, category, gender, image) -> dict:
    if config.USE_SUPABASE:
        rows = _sb("POST", json={"name": name, "price": price, "category": category, "gender": gender, "image": image},
                   prefer="return=representation")
        return _row(rows[0])
    with conn() as c:
        cur = c.execute("INSERT INTO products (name, price, category, gender, image) VALUES (?,?,?,?,?)",
                        (name, price, category, gender, image))
        pid = cur.lastrowid
    return get_product(pid)


def update_product(pid, name, price, category, gender, image) -> dict | None:
    if config.USE_SUPABASE:
        rows = _sb("PATCH", {"id": f"eq.{pid}"},
                   json={"name": name, "price": price, "category": category, "gender": gender, "image": image},
                   prefer="return=representation")
        return _row(rows[0]) if rows else None
    with conn() as c:
        c.execute("UPDATE products SET name=?, price=?, category=?, gender=?, image=? WHERE id=?",
                  (name, price, category, gender, image, pid))
    return get_product(pid)


def delete_product(pid: int) -> None:
    if config.USE_SUPABASE:
        _sb("DELETE", {"id": f"eq.{pid}"})
        return
    with conn() as c:
        c.execute("DELETE FROM products WHERE id = ?", (pid,))
