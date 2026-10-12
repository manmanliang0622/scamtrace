import io
import json
import os
import time
from pathlib import Path

import pytest

import db
from conftest import SAMPLE, confirm, csrf, login, make_user, post, upload_and_preview


def logs(app, action=None):
    with app.app_context():
        if action:
            return [dict(r) for r in db.query_all("SELECT * FROM audit_logs WHERE action = ?", (action,))]
        return [dict(r) for r in db.query_all("SELECT * FROM audit_logs")]


def case_id_from(resp):
    return int(resp.headers["Location"].rsplit("/", 1)[1])


# ---------------------------------------------------------------- 帳號

def test_secret_key_required(tmp_path, monkeypatch):
    from app import create_app
    from config import Config
    monkeypatch.setattr(Config, "SECRET_KEY", None)
    with pytest.raises(RuntimeError):
        create_app({"DATABASE": str(tmp_path / "x.db"), "PENDING_DIR": str(tmp_path / "p")})


def test_register_success_and_hash(app, client):
    r = post(client, "/register", {"username": "alice_01", "password": "abc12345"})
    assert r.status_code == 302
    with app.app_context():
        row = db.query_one("SELECT * FROM users WHERE username = 'alice_01'")
    assert row["role"] == "user" and "abc12345" not in row["password_hash"]
    assert logs(app, "register")


@pytest.mark.parametrize("username,password", [
    ("ab", "abc12345"), ("有中文的帳號", "abc12345"), ("has space", "abc12345"),
    ("alice_02", "12345678"), ("alice_02", "abc123"),
])
def test_register_rejects_bad_input(client, username, password):
    assert post(client, "/register", {"username": username, "password": password}).status_code == 400


def test_register_duplicate(app, client):
    make_user(app)
    r = post(client, "/register", {"username": "alice_01", "password": "abc12345"})
    assert r.status_code == 400 and "已被使用" in r.data.decode()


def test_login_errors_identical(app, client):
    make_user(app)
    a = login(client, "nobody", "abc12345").data.decode()
    b = login(client, "alice_01", "wrongpass1").data.decode()
    msg = "帳號或密碼錯誤"
    assert msg in a and msg in b
    failed = logs(app, "login_failed")
    assert len(failed) == 2 and failed[0]["user_id"] is None
    assert all("wrongpass1" not in json.dumps(r, ensure_ascii=False) for r in logs(app))


def test_lockout_and_expiry(app, client):
    uid = make_user(app)
    for _ in range(5):
        login(client, "alice_01", "wrongpass1")
    assert logs(app, "account_locked")
    assert login(client, "alice_01", "abc12345").status_code == 401  # 鎖定中，密碼正確也拒絕
    with app.app_context():
        db.execute("UPDATE users SET locked_until = '2000-01-01T00:00:00' WHERE id = ?", (uid,))
    assert login(client, "alice_01", "abc12345").status_code == 302
    with app.app_context():
        assert db.query_one("SELECT failed_logins FROM users WHERE id = ?", (uid,))["failed_logins"] == 0


def test_session_cookie_and_regeneration(app, client):
    make_user(app)
    with client.session_transaction() as s:
        s["_csrf"] = "before"
        s["leftover"] = "x"
    r = login(client)
    cookie = r.headers["Set-Cookie"]
    assert "HttpOnly" in cookie and "SameSite=Lax" in cookie
    with client.session_transaction() as s:
        assert "leftover" not in s and s["_csrf"] != "before" and s["user_id"]
    assert logs(app, "login_success")


def test_logout(app, client):
    make_user(app)
    login(client)
    assert post(client, "/logout").status_code == 302
    assert logs(app, "logout")
    assert client.get("/cases").status_code == 302


def test_csrf_required(app, client):
    make_user(app)
    login(client)
    r = client.post("/cases/new", data={"paste": "A：hi"})
    assert r.status_code == 400
    r = client.post("/cases/new", data={"paste": "A：hi", "_csrf": "wrong"})
    assert r.status_code == 400


def test_login_required_and_admin_only(app, client):
    assert client.get("/cases").status_code == 302
    assert client.get("/cases/new").status_code == 302
    make_user(app)
    login(client)
    assert client.get("/admin").status_code == 403
    assert client.get("/admin/audit").status_code == 403


def test_sql_injection_login(app, client):
    make_user(app)
    assert login(client, "' OR '1'='1", "x' OR '1'='1").status_code == 401


# ---------------------------------------------------------------- 上傳與預覽

def test_upload_requires_choosing_self(app, client):
    make_user(app)
    login(client)
    r = post(client, "/cases/new", {"file": (io.BytesIO(SAMPLE.encode()), "chat.txt")},
             content_type="multipart/form-data")
    page = r.data.decode()
    assert r.status_code == 200 and "哪個名字是你" in page and "王老師" in page


def test_upload_rejects_non_txt(app, client):
    make_user(app)
    login(client)
    r = post(client, "/cases/new", {"file": (io.BytesIO(b"x"), "chat.pdf")}, content_type="multipart/form-data")
    assert r.status_code == 400 and "只接受 .txt" in r.data.decode()


def test_upload_too_large(app, client):
    make_user(app)
    login(client)
    big = b"a" * (1024 * 1024 + 10)
    r = post(client, "/cases/new", {"file": (io.BytesIO(big), "chat.txt")}, content_type="multipart/form-data")
    assert r.status_code == 413 and "檔案過大" in r.data.decode()


def test_preview_masks_and_pending_has_no_raw_values(app, client):
    make_user(app)
    login(client)
    token = upload_and_preview(client)
    assert logs(app, "case_upload")
    page = client.get(f"/cases/preview/{token}").data.decode()
    assert '<span class="code">[電話1]</span>' in page and "[帳號1]" in page
    assert "0912-345-678" not in page and "王老師" not in page
    pending = Path(app.config["PENDING_DIR"], f"{token}.json").read_text(encoding="utf-8")
    assert "0912" not in pending and "12345678901234" not in pending and "陳美玲" not in pending


def test_preview_owner_only(app, client):
    make_user(app)
    make_user(app, "bob_0001")
    login(client)
    token = upload_and_preview(client)
    other = app.test_client()
    login(other, "bob_0001")
    assert other.get(f"/cases/preview/{token}").status_code == 404


def test_preview_expired(app, client):
    make_user(app)
    login(client)
    token = upload_and_preview(client)
    path = Path(app.config["PENDING_DIR"], f"{token}.json")
    data = json.loads(path.read_text())
    data["created"] -= 31 * 60
    path.write_text(json.dumps(data))
    assert client.get(f"/cases/preview/{token}").status_code == 404
    assert not path.exists()


def test_cleanup_removes_old_pending(app, client):
    make_user(app)
    login(client)
    old = Path(app.config["PENDING_DIR"], "old_token_old_token_1234.json")
    old.write_text("{}")
    past = time.time() - 31 * 60
    os.utime(old, (past, past))
    upload_and_preview(client)
    assert not old.exists()


def test_manual_mask(app, client):
    make_user(app)
    login(client)
    token = upload_and_preview(client)
    post(client, f"/cases/preview/{token}/mask", {"fragment": "真的嗎"})
    page = client.get(f"/cases/preview/{token}").data.decode()
    assert "[遮罩1]" in page and "真的嗎" not in page


def test_confirm_requires_checkbox(app, client):
    make_user(app)
    login(client)
    token = upload_and_preview(client)
    r = post(client, f"/cases/preview/{token}/confirm", {})
    assert r.status_code == 302 and "preview" in r.headers["Location"]


# ---------------------------------------------------------------- 分析與結果頁

def test_confirm_creates_case_with_rule_analysis(app, client):
    make_user(app)
    login(client)
    token = upload_and_preview(client)
    r = confirm(client, token)
    case_id = case_id_from(r)
    assert not Path(app.config["PENDING_DIR"], f"{token}.json").exists()
    with app.app_context():
        case = db.query_one("SELECT * FROM cases WHERE id = ?", (case_id,))
        texts = [m["masked_text"] for m in db.query_all("SELECT masked_text FROM messages WHERE case_id = ?", (case_id,))]
    assert case["status"] == "analyzed" and case["analyzed_by"] == "rule"
    assert case["turning_point_seq"] == 4 and case["risk_level"] in ("medium", "high")
    assert all("0912" not in t for t in texts)
    page = client.get(f"/cases/{case_id}").data.decode()
    assert "本次使用規則比對，準確度較低" in page and "165 反詐騙專線" in page
    assert logs(app, "case_analyze")


def test_confirm_with_llm_client(app, client):
    from test_analyzer import FakeClient
    out = {"messages": [
        {"seq": 1, "stage": "contact", "requests_action": False,
         "tactics": [{"code": "authority", "evidence": "投資分析師", "confidence": 0.9}]},
        {"seq": 4, "stage": "action", "requests_action": True,
         "tactics": [{"code": "scarcity", "evidence": "名額只剩今天", "confidence": 0.9}]}],
        "scam_type": "investment", "is_likely_scam": True, "summary": "第 4 則要求匯款。"}
    app.config["ANTHROPIC_CLIENT"] = FakeClient([out])
    make_user(app)
    login(client)
    case_id = case_id_from(confirm(client, upload_and_preview(client)))
    page = client.get(f"/cases/{case_id}").data.decode()
    assert "假投資" in page and "語言模型分析" in page and "第 4 則要求匯款" in page


def test_timeline_api(app, client):
    make_user(app)
    login(client)
    case_id = case_id_from(confirm(client, upload_and_preview(client)))
    data = client.get(f"/api/cases/{case_id}/timeline").get_json()
    assert [d["seq"] for d in data] == [1, 2, 3, 4]
    assert set(data[0]) == {"seq", "sent_at", "speaker", "risk", "stage", "tactics"}
    assert "scarcity" in data[3]["tactics"]


def test_access_control_404_and_log(app, client):
    make_user(app)
    make_user(app, "bob_0001")
    login(client)
    case_id = case_id_from(confirm(client, upload_and_preview(client)))
    other = app.test_client()
    login(other, "bob_0001")
    a = other.get(f"/cases/{case_id}")
    b = other.get("/cases/9999")
    assert a.status_code == b.status_code == 404 and a.data == b.data
    assert other.get(f"/api/cases/{case_id}/timeline").status_code == 404
    denied = logs(app, "access_denied")
    assert any(d["target"] == f"case:{case_id}" for d in denied)
    assert post(other, f"/cases/{case_id}/delete").status_code == 404
    assert post(other, f"/cases/{case_id}/feedback", {"is_correct": "1"}).status_code == 404
    assert client.get(f"/cases/{case_id}").status_code == 200


def test_admin_can_view_any_case(app, client):
    make_user(app)
    make_user(app, "admin_01", role="admin")
    login(client)
    case_id = case_id_from(confirm(client, upload_and_preview(client)))
    admin = app.test_client()
    login(admin, "admin_01")
    assert admin.get(f"/cases/{case_id}").status_code == 200


def test_demo_case_public_read_only(app, client):
    make_user(app)
    login(client)
    case_id = case_id_from(confirm(client, upload_and_preview(client)))
    with app.app_context():
        db.execute("UPDATE cases SET is_demo = 1 WHERE id = ?", (case_id,))
    guest = app.test_client()
    r = guest.get(f"/cases/{case_id}")
    page = r.data.decode()
    assert r.status_code == 200 and "自編示範資料" in page
    assert "標註有誤" not in page and "刪除案例" not in page
    assert "自編示範資料" in guest.get("/demo").data.decode()


def test_cases_list_own_only(app, client):
    make_user(app)
    make_user(app, "bob_0001")
    login(client)
    confirm(client, upload_and_preview(client))
    other = app.test_client()
    login(other, "bob_0001")
    assert "對話分析" not in other.get("/cases").data.decode()
    assert "對話分析" in client.get("/cases").data.decode()


def test_delete_cascade(app, client):
    make_user(app)
    login(client)
    case_id = case_id_from(confirm(client, upload_and_preview(client)))
    post(client, f"/cases/{case_id}/feedback", {"is_correct": "1"})
    assert post(client, f"/cases/{case_id}/delete").status_code == 302
    with app.app_context():
        for table in ("messages", "case_pii_stats", "feedback"):
            assert db.query_one(f"SELECT COUNT(*) AS n FROM {table} WHERE case_id = ?", (case_id,))["n"] == 0
        assert db.query_one("SELECT COUNT(*) AS n FROM message_tactics")["n"] == 0
    assert logs(app, "case_delete")


def test_xss_escaped(app, client):
    make_user(app)
    login(client)
    text = "14:05\t壞人\t<script>alert(1)</script> 匯款\n14:06\t我\t?\n"
    token = upload_and_preview(client, text, self_name="我")
    case_id = case_id_from(post(client, f"/cases/preview/{token}/confirm",
                                {"confirm": "yes", "title": "<img src=x onerror=alert(1)>"}))
    page = client.get(f"/cases/{case_id}").data.decode()
    assert "<script>alert(1)</script>" not in page and "&lt;script&gt;" in page
    assert "<img src=x" not in client.get("/cases").data.decode()


def test_rate_limit(app, client):
    uid = make_user(app)
    login(client)
    with app.app_context():
        for _ in range(20):
            db.execute("INSERT INTO audit_logs (user_id, action, created_at) VALUES (?, 'case_analyze', ?)",
                       (uid, db.now_iso()))
    r = confirm(client, upload_and_preview(client))
    assert r.status_code == 429 and "每小時最多分析 20 次" in r.data.decode()
    assert logs(app, "rate_limited")


# ---------------------------------------------------------------- 回饋

def test_feedback_message_and_overall(app, client):
    make_user(app)
    login(client)
    case_id = case_id_from(confirm(client, upload_and_preview(client)))
    with app.app_context():
        mid = db.query_one("SELECT id FROM messages WHERE case_id = ? AND seq = 4", (case_id,))["id"]
    post(client, f"/cases/{case_id}/feedback", {"message_id": mid, "is_correct": "0", "corrected_tactic": "liking"})
    post(client, f"/cases/{case_id}/feedback", {"is_correct": "1"})
    with app.app_context():
        rows = db.query_all("SELECT * FROM feedback ORDER BY id")
    assert rows[0]["message_id"] == mid and rows[0]["is_correct"] == 0 and rows[0]["corrected_tactic_id"]
    assert rows[1]["message_id"] is None and rows[1]["is_correct"] == 1
    assert len(logs(app, "feedback")) == 2


def test_feedback_validation(app, client):
    make_user(app)
    login(client)
    case_id = case_id_from(confirm(client, upload_and_preview(client)))
    post(client, f"/cases/{case_id}/feedback", {"is_correct": "0", "comment": "字" * 201})
    assert post(client, f"/cases/{case_id}/feedback", {"is_correct": "0", "message_id": "99999"}).status_code == 400
    assert post(client, f"/cases/{case_id}/feedback", {"is_correct": "0", "corrected_tactic": "greed"}).status_code == 400
    with app.app_context():
        assert db.query_one("SELECT COUNT(*) AS n FROM feedback")["n"] == 0


# ---------------------------------------------------------------- 後台

def test_admin_dashboard_and_audit(app, client):
    make_user(app, "admin_01", role="admin")
    login(client, "admin_01")
    confirm(client, upload_and_preview(client, self_name="陳美玲"))
    page = client.get("/admin").data.decode()
    assert "已分析案例" in page and "模型 0／規則 1" in page
    audit = client.get("/admin/audit?action=login_success").data.decode()
    assert "login_success" in audit and "case_upload</code>" not in audit


def test_audit_pagination(app, client):
    make_user(app, "admin_01", role="admin")
    login(client, "admin_01")
    with app.app_context():
        for i in range(120):
            db.execute("INSERT INTO audit_logs (action, target, created_at) VALUES ('feedback', ?, ?)",
                       (f"case:{i}", f"2026-01-01T00:{i // 60:02d}:{i % 60:02d}"))
    page = client.get("/admin/audit?action=feedback&page=3").data.decode()
    assert page.count("<tr>") - 1 == 20 and "第 3 / 3 頁" in page


def test_stats_pairs(app):
    import stats
    with app.app_context():
        conn = db.get_db()
        conn.execute("INSERT INTO users (id, username, password_hash) VALUES (1, 'u', 'x')")
        conn.execute("INSERT INTO cases (id, user_id, title, message_count, status) VALUES (1, 1, 't', 8, 'analyzed')")
        ids = {r["code"]: r["id"] for r in conn.execute("SELECT id, code FROM tactics")}
        for i in range(8):
            conn.execute("INSERT INTO messages (id, case_id, seq, speaker, is_self, masked_text) VALUES (?, 1, ?, 'A', 0, 'x')",
                         (i + 1, i + 1))
        for mid in range(1, 6):
            conn.execute("INSERT INTO message_tactics VALUES (?, ?, 'x', 0.5)", (mid, ids["authority"]))
            conn.execute("INSERT INTO message_tactics VALUES (?, ?, 'x', 0.5)", (mid, ids["urgency_threat"]))
        for mid in range(6, 9):
            conn.execute("INSERT INTO message_tactics VALUES (?, ?, 'x', 0.5)", (mid, ids["liking"]))
            conn.execute("INSERT INTO message_tactics VALUES (?, ?, 'x', 0.5)", (mid, ids["unity"]))
        conn.commit()
        pairs = stats.tactic_pairs()
    assert pairs[0] == {"a": "權威", "b": "威脅恐嚇", "count": 5}
    assert pairs[1] == {"a": "喜好", "b": "團結", "count": 3}


# ---------------------------------------------------------------- 錯誤頁

def test_error_pages(app, client):
    @app.route("/boom")
    def boom():
        raise ValueError("secret internals")

    r = client.get("/no-such-page")
    assert r.status_code == 404 and "找不到頁面" in r.data.decode()
    r = client.get("/boom")
    assert r.status_code == 500 and "secret internals" not in r.data.decode() and "Traceback" not in r.data.decode()
