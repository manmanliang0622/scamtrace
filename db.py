"""SQLite 連線與查詢工具。所有查詢一律使用 ? 參數化。"""
import sqlite3
from datetime import datetime
from pathlib import Path

from flask import current_app, g

SCHEMA_PATH = Path(__file__).with_name("schema.sql")


def now_iso():
    return datetime.now().isoformat(timespec="seconds")


def connect(path):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    # SQLite 預設不檢查外鍵，不開啟的話 ON DELETE CASCADE 不會生效
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def get_db():
    if "db" not in g:
        g.db = connect(current_app.config["DATABASE"])
    return g.db


def close_db(exc=None):
    conn = g.pop("db", None)
    if conn is not None:
        conn.close()


def init_schema(conn):
    conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
    conn.commit()


def query_all(sql, params=()):
    return get_db().execute(sql, params).fetchall()


def query_one(sql, params=()):
    return get_db().execute(sql, params).fetchone()


def execute(sql, params=()):
    conn = get_db()
    cur = conn.execute(sql, params)
    conn.commit()
    return cur.lastrowid


def init_app(app):
    app.teardown_appcontext(close_db)
    Path(app.config["DATABASE"]).parent.mkdir(parents=True, exist_ok=True)
    with app.app_context():
        init_schema(get_db())
