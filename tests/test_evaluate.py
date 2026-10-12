import json

import db
import evaluate
from seed import seed_demo_cases

SCAM = (
    "2026/10/01（三）\n"
    "10:00\t王老師\t你好，我是投資分析師\n"
    "10:01\t小美\t你好\n"
    "10:02\t王老師\t今天先匯款到 12345678901234，名額只剩今天\n"
)
NORMAL = (
    "2026/10/01（三）\n"
    "10:00\t阿明\t晚上一起吃飯嗎\n"
    "10:01\t小美\t好啊\n"
)


def write_demo(tmp_path):
    d = tmp_path / "demo"
    d.mkdir()
    (d / "a_scam.txt").write_text(SCAM, encoding="utf-8")
    (d / "a_scam.json").write_text(json.dumps({
        "title": "假投資測試", "self_name": "小美", "is_scam": True, "scam_type": "investment", "turning_point": 3,
        "pii": [{"type": "bank_account", "value": "12345678901234"}],
        "messages": {"1": {"stage": "contact", "tactics": ["authority"]}, "2": {"stage": "contact", "tactics": []},
                     "3": {"stage": "action", "tactics": ["scarcity"]}},
    }, ensure_ascii=False), encoding="utf-8")
    (d / "b_normal.txt").write_text(NORMAL, encoding="utf-8")
    (d / "b_normal.json").write_text(json.dumps({
        "title": "約吃飯測試", "self_name": "小美", "is_scam": False, "scam_type": None, "turning_point": None,
        "pii": [], "messages": {"1": {"stage": "none", "tactics": []}, "2": {"stage": "none", "tactics": []}},
    }, ensure_ascii=False), encoding="utf-8")
    return d


def test_evaluate_rule_only(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    d = write_demo(tmp_path)
    out = tmp_path / "report.md"
    results = evaluate.main(["--demo-dir", str(d), "--out", str(out)])
    assert set(results) == {"rule"}
    assert results["rule"]["accuracy"] == 1.0
    assert results["rule"]["tp_mean_error"] == 0
    report = out.read_text(encoding="utf-8")
    assert "初步測試" in report and "語言模型部分未執行" in report
    assert "成功率 100%" in report


def test_check_dataset_flags_small_set(tmp_path):
    d = write_demo(tmp_path)
    problems = evaluate.check_dataset(evaluate.load_demo_set(d))
    assert any("至少需要 8 段" in p for p in problems)
    assert any("20–60" in p for p in problems)


def test_seed_demo_cases_idempotent(app, tmp_path):
    d = write_demo(tmp_path)
    with app.app_context():
        conn = db.get_db()
        conn.execute("INSERT INTO users (id, username, password_hash, role) VALUES (1, 'admin', 'x', 'admin')")
        conn.commit()
        assert seed_demo_cases(conn, 1, None, d) == 2
        assert seed_demo_cases(conn, 1, None, d) == 0
        rows = conn.execute("SELECT title, is_demo, status FROM cases ORDER BY id").fetchall()
        texts = [r[0] for r in conn.execute("SELECT masked_text FROM messages")]
    assert [(r["title"], r["is_demo"], r["status"]) for r in rows] == [("假投資測試", 1, "analyzed"), ("約吃飯測試", 1, "analyzed")]
    assert not any("12345678901234" in t for t in texts)
