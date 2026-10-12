import re

import pytest
from werkzeug.security import generate_password_hash

from app import create_app
import db


@pytest.fixture
def app(tmp_path):
    app = create_app({
        "TESTING": True,
        "SECRET_KEY": "test-secret",
        "DATABASE": str(tmp_path / "test.db"),
        "PENDING_DIR": str(tmp_path / "pending"),
        "ANTHROPIC_API_KEY": None,
    })
    (tmp_path / "pending").mkdir(exist_ok=True)
    return app


@pytest.fixture
def client(app):
    return app.test_client()


def csrf(client):
    with client.session_transaction() as s:
        if "_csrf" not in s:
            s["_csrf"] = "test-csrf-token"
        return s["_csrf"]


def post(client, url, data=None, **kw):
    data = dict(data or {})
    data.setdefault("_csrf", csrf(client))
    return client.post(url, data=data, **kw)


def make_user(app, username="alice_01", password="abc12345", role="user"):
    with app.app_context():
        return db.execute("INSERT INTO users (username, password_hash, role) VALUES (?, ?, ?)",
                          (username, generate_password_hash(password), role))


def login(client, username="alice_01", password="abc12345"):
    return post(client, "/login", {"username": username, "password": password})


SAMPLE = (
    "[LINE] 與王老師的聊天記錄\n"
    "儲存日期：2026/10/09 14:00\n\n"
    "2026/10/01（三）\n"
    "14:05\t王老師\t你好，我是投資分析師王老師，群組裡大家都賺了\n"
    "14:06\t陳美玲\t真的嗎\n"
    "14:07\t王老師\t[貼圖]\n"
    "14:08\t王老師\t今天先匯款 3 萬到 12345678901234，名額只剩今天，電話 0912-345-678\n"
)


def upload_and_preview(client, text=SAMPLE, self_name="陳美玲"):
    """上傳 → 選名字 → 回傳預覽 token。"""
    r = post(client, "/cases/new", {"raw_text": text, "source_type": "line_txt", "self_name": self_name})
    assert r.status_code == 302, r.data.decode()
    return re.search(r"/cases/preview/([\w-]+)", r.headers["Location"]).group(1)


def confirm(client, token):
    return post(client, f"/cases/preview/{token}/confirm", {"confirm": "yes"})
