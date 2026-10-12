"""建立資料表、查找表、管理員帳號與示範案例。

用法：
    ADMIN_USERNAME=admin ADMIN_PASSWORD=... python seed.py
未設定 ADMIN_PASSWORD 時會互動詢問。可重複執行，不會重複建立資料。
"""
import getpass
import json
import os
import sys
from pathlib import Path

from werkzeug.security import generate_password_hash

import db
from taxonomy import SCAM_TYPES, TACTICS

BASE_DIR = Path(__file__).resolve().parent
DEFAULT_DB = BASE_DIR / "instance" / "scam.db"
DEMO_DIR = BASE_DIR / "demo_data"


def seed_lookup(conn):
    for code, name, name_en, desc, color in TACTICS:
        conn.execute(
            "INSERT INTO tactics (code, name, name_en, description, color) VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(code) DO UPDATE SET name = excluded.name, name_en = excluded.name_en, "
            "description = excluded.description, color = excluded.color",
            (code, name, name_en, desc, color),
        )
    for code, name, desc in SCAM_TYPES:
        conn.execute(
            "INSERT INTO scam_types (code, name, description) VALUES (?, ?, ?) "
            "ON CONFLICT(code) DO UPDATE SET name = excluded.name, description = excluded.description",
            (code, name, desc),
        )
    conn.commit()


def ensure_admin(conn, username, password):
    """建立管理員；帳號已存在時只確保角色為 admin，不改密碼。回傳使用者 id。"""
    row = conn.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone()
    if row:
        conn.execute("UPDATE users SET role = 'admin' WHERE id = ?", (row["id"],))
        conn.commit()
        return row["id"]
    cur = conn.execute(
        "INSERT INTO users (username, password_hash, role) VALUES (?, ?, 'admin')",
        (username, generate_password_hash(password)),
    )
    conn.commit()
    return cur.lastrowid


def main():
    db_path = Path(os.environ.get("DATABASE", DEFAULT_DB))
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = db.connect(db_path)
    db.init_schema(conn)
    seed_lookup(conn)
    print(f"查找表完成：{len(TACTICS)} 個手法、{len(SCAM_TYPES)} 個詐騙類型")

    username = os.environ.get("ADMIN_USERNAME", "admin")
    exists = conn.execute("SELECT 1 FROM users WHERE username = ?", (username,)).fetchone()
    password = os.environ.get("ADMIN_PASSWORD")
    if not exists and not password:
        password = getpass.getpass(f"設定管理員 {username} 的密碼：")
    if not exists:
        from auth import validate_password
        err = validate_password(password or "")
        if err:
            sys.exit(f"管理員密碼不符規則：{err}")
    admin_id = ensure_admin(conn, username, password)
    print(f"管理員帳號：{username}（id {admin_id}）")

    created = seed_demo_cases(conn, admin_id, os.environ.get("ANTHROPIC_API_KEY"))
    print(f"示範案例：新增 {created} 段（已存在的不重複建立）")
    conn.close()


def load_demo_set(demo_dir=DEMO_DIR):
    """讀取 demo_data/ 下成對的 <name>.txt（LINE 匯出格式）與 <name>.json（人工標註）。"""
    pairs = []
    for txt in sorted(Path(demo_dir).glob("*.txt")):
        meta_path = txt.with_suffix(".json")
        if not meta_path.exists():
            continue
        pairs.append((txt.stem, txt.read_text(encoding="utf-8"), json.loads(meta_path.read_text(encoding="utf-8"))))
    return pairs


def seed_demo_cases(conn, admin_id, api_key=None, demo_dir=DEMO_DIR):
    from analyzer import analyze
    from app import create_case, store_analysis
    from deidentify import deidentify
    from parser import parse

    created = 0
    for _name, text, meta in load_demo_set(demo_dir):
        title = meta["title"]
        if conn.execute("SELECT 1 FROM cases WHERE is_demo = 1 AND title = ?", (title,)).fetchone():
            continue
        parsed = parse(text, "line_txt")
        masked, counts = deidentify(parsed.messages, meta["self_name"])
        case_id = create_case(conn, admin_id, title, "line_txt", masked, counts, is_demo=True)
        result = analyze(masked, api_key=api_key)
        store_analysis(conn, case_id, masked, result)
        created += 1
    return created


if __name__ == "__main__":
    main()
