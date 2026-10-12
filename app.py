"""Flask 進入點與路由。"""
import json
import os
import re
import secrets
import time
from datetime import date, datetime, timedelta
from pathlib import Path

from flask import (Flask, abort, flash, g, jsonify, redirect, render_template,
                   request, url_for)
from werkzeug.exceptions import HTTPException

import analyzer
import auth
import db
import risk
import stats
from auth import admin_required, is_admin, log_event, login_required
from config import Config
from deidentify import CODE_RE, apply_manual_mask, deidentify
from parser import ParseError, decode_bytes, parse
from taxonomy import (RISK_LEVEL_NAMES, SCAM_TYPE_NAMES, STAGE_NAMES, STAGES,
                      TACTIC_COLORS, TACTIC_NAMES, TACTICS)

BASE_DIR = Path(__file__).resolve().parent
TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{20,64}$")
PII_LABELS = {
    "card": "信用卡號", "id_number": "身分證字號", "arc_number": "居留證號", "email": "Email",
    "url": "網址路徑", "phone": "電話", "bank_account": "銀行帳號", "line_id": "LINE ID",
    "address": "地址", "passport": "護照號碼", "manual": "手動遮罩",
}
ERROR_TEXT = {
    400: ("請求不正確", "請重新整理頁面後再試一次。"),
    403: ("沒有權限", "你沒有權限查看這個頁面。"),
    404: ("找不到頁面", "這個頁面不存在，或你沒有權限查看。"),
    413: ("檔案過大", "上傳內容不可超過 1 MB。"),
    429: ("分析次數已達上限", "每小時最多分析 20 次，請稍後再試。"),
    500: ("系統發生錯誤", "請稍後再試；若持續發生，請聯絡管理員。"),
}


def create_app(test_config=None):
    app = Flask(__name__, instance_path=str(BASE_DIR / "instance"))
    app.config.from_object(Config)
    app.config.update(
        DATABASE=str(Path(app.instance_path) / "scam.db"),
        PENDING_DIR=str(Path(app.instance_path) / "pending"),
    )
    if test_config:
        app.config.update(test_config)
    if not app.config.get("SECRET_KEY"):
        raise RuntimeError("未設定 SECRET_KEY 環境變數，請先設定後再啟動（見 README）。")

    Path(app.config["PENDING_DIR"]).mkdir(parents=True, exist_ok=True)
    db.init_app(app)
    with app.app_context():
        seed_lookup_if_empty()
    auth.init_app(app)
    register_routes(app)
    register_error_handlers(app)
    app.jinja_env.globals.update(
        TACTIC_NAMES=TACTIC_NAMES, TACTIC_COLORS=TACTIC_COLORS, STAGE_NAMES=STAGE_NAMES,
        SCAM_TYPE_NAMES=SCAM_TYPE_NAMES, RISK_LEVEL_NAMES=RISK_LEVEL_NAMES, PII_LABELS=PII_LABELS,
        TACTICS=TACTICS, STAGES=STAGES, is_admin=is_admin,
    )
    app.jinja_env.filters["split_codes"] = split_codes
    cleanup_pending(app.config["PENDING_DIR"], app.config["PENDING_TTL_SECONDS"])
    return app


def split_codes(text):
    """把遮罩後文字切成一般文字與代號兩種片段，供樣板以灰底標示代號。"""
    parts, pos = [], 0
    for m in CODE_RE.finditer(text):
        if m.start() > pos:
            parts.append({"text": text[pos:m.start()], "code": False})
        parts.append({"text": m.group(0), "code": True})
        pos = m.end()
    if pos < len(text):
        parts.append({"text": text[pos:], "code": False})
    return parts


def seed_lookup_if_empty():
    conn = db.get_db()
    if conn.execute("SELECT COUNT(*) FROM tactics").fetchone()[0] == 0:
        import seed
        seed.seed_lookup(conn)


# ---------------------------------------------------------------- 預覽暫存檔

def cleanup_pending(pending_dir, ttl):
    """刪除超過有效時間的暫存檔。啟動時與每次上傳時執行。"""
    now = time.time()
    for path in Path(pending_dir).glob("*.json"):
        try:
            if now - path.stat().st_mtime > ttl:
                path.unlink()
        except FileNotFoundError:
            pass


def pending_path(app, token):
    if not TOKEN_RE.match(token):
        return None
    return Path(app.config["PENDING_DIR"]) / f"{token}.json"


def load_pending(app, token):
    """讀取暫存；不存在、過期或不是本人的都回 404。"""
    path = pending_path(app, token)
    if path is None or not path.exists():
        abort(404)
    data = json.loads(path.read_text(encoding="utf-8"))
    if data["owner"] != g.user["id"]:
        abort(404)
    if time.time() - data["created"] > app.config["PENDING_TTL_SECONDS"]:
        path.unlink(missing_ok=True)
        flash("預覽已超過 30 分鐘失效，請重新上傳。", "error")
        abort(404)
    return path, data


def save_pending(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


# ---------------------------------------------------------------- 案例存取

def load_case_or_404(case_id, action="view"):
    """action：view（本人、管理員、示範案例）、feedback（僅本人）、delete（本人、管理員）。

    不符合時一律回 404，並寫入 access_denied 日誌，不透露案例是否存在。
    """
    case = db.query_one("SELECT * FROM cases WHERE id = ?", (case_id,))
    uid = g.user["id"] if g.user else None
    allowed = False
    if case is not None:
        owner = uid is not None and case["user_id"] == uid
        if action == "view":
            allowed = owner or is_admin() or bool(case["is_demo"])
        elif action == "feedback":
            allowed = owner
        elif action == "delete":
            allowed = owner or is_admin()
    if not allowed:
        log_event("access_denied", target=f"case:{case_id}", detail=action)
        abort(404)
    return case


def can_modify(case):
    return g.user is not None and case["user_id"] == g.user["id"]


# ---------------------------------------------------------------- 寫入分析結果

def tactic_ids(conn):
    return {r["code"]: r["id"] for r in conn.execute("SELECT id, code FROM tactics")}


def scam_type_id(conn, code):
    if not code:
        return None
    row = conn.execute("SELECT id FROM scam_types WHERE code = ?", (code,)).fetchone()
    return row["id"] if row else None


def create_case(conn, user_id, title, source_type, messages, pii_counts, is_demo=False):
    """建立案例並寫入遮罩後訊息與去識別化統計，回傳 case_id。"""
    times = [m["sent_at"] for m in messages if m.get("sent_at")]
    cur = conn.execute(
        "INSERT INTO cases (user_id, title, source_type, is_demo, message_count, period_start, period_end, "
        "status, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?)",
        (user_id, title, source_type, int(is_demo), len(messages), times[0] if times else None,
         times[-1] if times else None, db.now_iso()),
    )
    case_id = cur.lastrowid
    conn.executemany(
        "INSERT INTO messages (case_id, seq, sent_at, speaker, is_self, masked_text, msg_type) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        [(case_id, m["seq"], m["sent_at"], m["speaker"], int(m["is_self"]), m["text"], m["msg_type"])
         for m in messages],
    )
    conn.executemany(
        "INSERT INTO case_pii_stats (case_id, pii_type, count) VALUES (?, ?, ?)",
        [(case_id, k, v) for k, v in pii_counts.items() if v],
    )
    conn.commit()
    return case_id


def store_analysis(conn, case_id, messages, result):
    """把分析結果與風險分數寫回資料庫。messages 為遮罩後訊息（依 seq 排序）。"""
    scored = []
    for m in messages:
        r = result.messages.get(m["seq"], analyzer.empty_result(m))
        scored.append({"seq": m["seq"], "is_self": m["is_self"], "stage": r["stage"],
                       "requests_action": r["requests_action"], "tactics": r["tactics"]})
    overall, level, tp = risk.score_case(scored)
    ids = tactic_ids(conn)
    msg_ids = {r["seq"]: r["id"] for r in conn.execute("SELECT id, seq FROM messages WHERE case_id = ?", (case_id,))}
    conn.execute("DELETE FROM message_tactics WHERE message_id IN (SELECT id FROM messages WHERE case_id = ?)",
                 (case_id,))
    for s in scored:
        conn.execute("UPDATE messages SET stage = ?, risk_score = ?, requests_action = ? WHERE id = ?",
                     (s["stage"], s["risk"], int(s["requests_action"]), msg_ids[s["seq"]]))
        conn.executemany(
            "INSERT INTO message_tactics (message_id, tactic_id, evidence, confidence) VALUES (?, ?, ?, ?)",
            [(msg_ids[s["seq"]], ids[t["code"]], t["evidence"], t["confidence"]) for t in s["tactics"]],
        )
    conn.execute(
        "UPDATE cases SET status = 'analyzed', overall_risk = ?, risk_level = ?, scam_type_id = ?, summary = ?, "
        "turning_point_seq = ?, analyzed_by = ?, model_name = ?, analyzed_at = ? WHERE id = ?",
        (overall, level, scam_type_id(conn, result.scam_type), result.summary, tp, result.analyzed_by,
         result.model_name, db.now_iso(), case_id),
    )
    conn.commit()


def analyses_last_hour(user_id):
    since = (datetime.now() - timedelta(hours=1)).isoformat(timespec="seconds")
    row = db.query_one(
        "SELECT COUNT(*) AS n FROM audit_logs WHERE user_id = ? AND action = 'case_analyze' AND created_at >= ?",
        (user_id, since),
    )
    return row["n"]


# ---------------------------------------------------------------- 結果頁資料

def case_messages(case_id):
    rows = db.query_all("SELECT * FROM messages WHERE case_id = ? ORDER BY seq", (case_id,))
    tactics = {}
    for t in db.query_all(
        "SELECT mt.message_id, t.code, mt.evidence, mt.confidence FROM message_tactics mt "
        "JOIN tactics t ON t.id = mt.tactic_id JOIN messages m ON m.id = mt.message_id "
        "WHERE m.case_id = ? ORDER BY t.id",
        (case_id,),
    ):
        tactics.setdefault(t["message_id"], []).append(dict(t))
    return [dict(r, tactics=tactics.get(r["id"], [])) for r in rows]


def tactic_counts(messages):
    counts = {}
    for m in messages:
        for t in m["tactics"]:
            counts[t["code"]] = counts.get(t["code"], 0) + 1
    return sorted(counts.items(), key=lambda kv: -kv[1])


# ---------------------------------------------------------------- 路由

def register_routes(app):

    @app.route("/")
    def index():
        demos = db.query_all(
            "SELECT c.*, st.code AS scam_code FROM cases c LEFT JOIN scam_types st ON st.id = c.scam_type_id "
            "WHERE c.is_demo = 1 AND c.status = 'analyzed' ORDER BY c.id LIMIT 8"
        )
        return render_template("index.html", demos=demos)

    @app.route("/demo")
    def demo_list():
        demos = db.query_all(
            "SELECT c.*, st.code AS scam_code FROM cases c LEFT JOIN scam_types st ON st.id = c.scam_type_id "
            "WHERE c.is_demo = 1 ORDER BY c.id"
        )
        return render_template("demo.html", demos=demos)

    @app.route("/cases")
    @login_required
    def cases_list():
        cases = db.query_all(
            "SELECT c.*, st.code AS scam_code FROM cases c LEFT JOIN scam_types st ON st.id = c.scam_type_id "
            "WHERE c.user_id = ? ORDER BY c.created_at DESC, c.id DESC",
            (g.user["id"],),
        )
        return render_template("cases.html", cases=cases)

    @app.route("/cases/new", methods=["GET", "POST"])
    @login_required
    def case_new():
        if request.method == "GET":
            return render_template("upload.html")

        cleanup_pending(app.config["PENDING_DIR"], app.config["PENDING_TTL_SECONDS"])
        upload = request.files.get("file")
        raw_text = request.form.get("raw_text")  # 第二步：選完名字後由表單送回，不在伺服器端保存
        source_type = request.form.get("source_type")
        try:
            if raw_text is None and upload and upload.filename:
                if not upload.filename.lower().endswith(".txt"):
                    raise ParseError("只接受 .txt 檔案。")
                raw_text, source_type = decode_bytes(upload.read()), "line_txt"
            elif raw_text is None:
                raw_text, source_type = request.form.get("paste", ""), "paste"
            if source_type not in ("line_txt", "paste"):
                abort(400)
            if not raw_text.strip():
                raise ParseError("請上傳 LINE 匯出的 .txt 檔，或貼上對話文字。")
            result = parse(raw_text, source_type, app.config["MAX_MESSAGES"])
        except ParseError as e:
            flash(str(e), "error")
            return render_template("upload.html"), 400

        self_name = request.form.get("self_name")
        if self_name not in result.speakers:
            return render_template("choose_self.html", speakers=result.speakers, raw_text=raw_text,
                                   source_type=source_type, warnings=result.warnings,
                                   count=len(result.messages))

        masked, pii_counts = deidentify(result.messages, self_name)
        del raw_text, result  # 原文與對照表不再保留
        token = secrets.token_urlsafe(24)
        title = (request.form.get("title") or "").strip()[:100] or f"對話分析 {date.today().isoformat()}"
        save_pending(pending_path(app, token), {
            "owner": g.user["id"], "created": time.time(), "source_type": source_type, "title": title,
            "messages": masked, "pii_counts": pii_counts,
        })
        log_event("case_upload", target=f"pending:{token[:8]}", detail=f"{len(masked)} messages")
        return redirect(url_for("case_preview", token=token))

    @app.route("/cases/preview/<token>")
    @login_required
    def case_preview(token):
        _, data = load_pending(app, token)
        return render_template("preview.html", token=token, data=data)

    @app.route("/cases/preview/<token>/mask", methods=["POST"])
    @login_required
    def case_mask(token):
        path, data = load_pending(app, token)
        fragment = (request.form.get("fragment") or "").strip()
        if not fragment or len(fragment) > 100:
            flash("請先在左側選取要遮罩的文字（100 字以內）。", "error")
        else:
            n = apply_manual_mask(data["messages"], fragment, data["pii_counts"])
            if n:
                save_pending(path, data)
                flash(f"已遮罩 {n} 處。", "success")
            else:
                flash("找不到這段文字，或它位於既有代號中。", "error")
        return redirect(url_for("case_preview", token=token))

    @app.route("/cases/preview/<token>/confirm", methods=["POST"])
    @login_required
    def case_confirm(token):
        path, data = load_pending(app, token)
        if request.form.get("confirm") != "yes":
            flash("請先勾選「我確認內容已去識別化」。", "error")
            return redirect(url_for("case_preview", token=token))
        if analyses_last_hour(g.user["id"]) >= app.config["ANALYZE_LIMIT_PER_HOUR"]:
            log_event("rate_limited", target=f"pending:{token[:8]}")
            abort(429)

        title = (request.form.get("title") or data["title"]).strip()[:100] or data["title"]
        conn = db.get_db()
        case_id = create_case(conn, g.user["id"], title, data["source_type"], data["messages"], data["pii_counts"])
        path.unlink(missing_ok=True)
        try:
            result = analyzer.analyze(
                data["messages"], api_key=app.config.get("ANTHROPIC_API_KEY"),
                model=app.config["MODEL_NAME"], chunk_size=app.config["CHUNK_SIZE"],
                overlap=app.config["CHUNK_OVERLAP"], client=app.config.get("ANTHROPIC_CLIENT"),
            )
            store_analysis(conn, case_id, data["messages"], result)
        except Exception:
            app.logger.exception("分析失敗 case:%s", case_id)
            conn.rollback()
            conn.execute("UPDATE cases SET status = 'failed' WHERE id = ?", (case_id,))
            conn.commit()
            log_event("case_analyze", target=f"case:{case_id}", detail="failed")
            return redirect(url_for("case_detail", case_id=case_id))
        detail = f"by={result.analyzed_by} dropped={result.dropped}"
        if result.fallback_reason:
            detail += f" fallback={result.fallback_reason}"
        log_event("case_analyze", target=f"case:{case_id}", detail=detail)
        return redirect(url_for("case_detail", case_id=case_id))

    @app.route("/cases/<int:case_id>")
    def case_detail(case_id):
        case = load_case_or_404(case_id)
        messages = case_messages(case_id)
        scam = db.query_one("SELECT code FROM scam_types WHERE id = ?", (case["scam_type_id"],)) \
            if case["scam_type_id"] else None
        pii = db.query_all("SELECT pii_type, count FROM case_pii_stats WHERE case_id = ? ORDER BY count DESC",
                           (case_id,))
        return render_template("case.html", case=case, messages=messages, scam_code=scam["code"] if scam else None,
                               pii=pii, counts=tactic_counts(messages), can_modify=can_modify(case),
                               can_delete=can_modify(case) or is_admin())

    @app.route("/api/cases/<int:case_id>/timeline")
    def api_timeline(case_id):
        load_case_or_404(case_id)
        return jsonify([
            {"seq": m["seq"], "sent_at": m["sent_at"], "speaker": m["speaker"], "risk": m["risk_score"] or 0,
             "stage": m["stage"] or "none", "tactics": [t["code"] for t in m["tactics"]]}
            for m in case_messages(case_id)
        ])

    @app.route("/cases/<int:case_id>/feedback", methods=["POST"])
    @login_required
    def case_feedback(case_id):
        case = load_case_or_404(case_id, "feedback")
        message_id = request.form.get("message_id") or None
        if message_id is not None:
            if not message_id.isdigit() or not db.query_one(
                    "SELECT 1 FROM messages WHERE id = ? AND case_id = ?", (int(message_id), case_id)):
                abort(400)
            message_id = int(message_id)
        is_correct = request.form.get("is_correct")
        if is_correct not in ("0", "1"):
            abort(400)
        corrected = request.form.get("corrected_tactic") or None
        corrected_id = None
        if corrected:
            row = db.query_one("SELECT id FROM tactics WHERE code = ?", (corrected,))
            if row is None:
                abort(400)
            corrected_id = row["id"]
        comment = (request.form.get("comment") or "").strip() or None
        if comment and len(comment) > 200:
            flash("說明最多 200 字。", "error")
            return redirect(url_for("case_detail", case_id=case_id))
        db.execute(
            "INSERT INTO feedback (case_id, message_id, user_id, is_correct, corrected_tactic_id, comment, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (case["id"], message_id, g.user["id"], int(is_correct), corrected_id, comment, db.now_iso()),
        )
        log_event("feedback", target=f"case:{case_id}",
                  detail=f"message={message_id or 'overall'} correct={is_correct}")
        flash("感謝回饋！", "success")
        anchor = f"#msg-{request.form.get('seq')}" if request.form.get("seq", "").isdigit() else ""
        return redirect(url_for("case_detail", case_id=case_id) + anchor)

    @app.route("/cases/<int:case_id>/delete", methods=["POST"])
    @login_required
    def case_delete(case_id):
        load_case_or_404(case_id, "delete")
        db.execute("DELETE FROM cases WHERE id = ?", (case_id,))
        log_event("case_delete", target=f"case:{case_id}")
        flash("案例已刪除。", "success")
        return redirect(url_for("cases_list"))

    @app.route("/admin")
    @admin_required
    def admin_dashboard():
        cases = db.query_all(
            "SELECT c.id, c.title, c.is_demo, c.risk_level, c.status, c.created_at, u.username "
            "FROM cases c JOIN users u ON u.id = c.user_id ORDER BY c.id DESC LIMIT 100"
        )
        return render_template("admin/dashboard.html", s=stats.dashboard(), cases=cases)

    @app.route("/admin/cases/<int:case_id>/demo", methods=["POST"])
    @admin_required
    def admin_toggle_demo(case_id):
        if not db.query_one("SELECT 1 FROM cases WHERE id = ?", (case_id,)):
            abort(404)
        db.execute("UPDATE cases SET is_demo = ? WHERE id = ?", (int(request.form.get("is_demo") == "1"), case_id))
        return redirect(url_for("admin_dashboard"))

    @app.route("/admin/audit")
    @admin_required
    def admin_audit():
        per_page = 50
        action = request.args.get("action", "")
        if action not in auth.AUDIT_ACTIONS:
            action = ""
        page = max(1, request.args.get("page", 1, type=int))
        where, params = ("WHERE a.action = ?", [action]) if action else ("", [])
        total = db.query_one(f"SELECT COUNT(*) AS n FROM audit_logs a {where}", params)["n"]
        rows = db.query_all(
            f"SELECT a.*, u.username FROM audit_logs a LEFT JOIN users u ON u.id = a.user_id {where} "
            "ORDER BY a.created_at DESC, a.id DESC LIMIT ? OFFSET ?",
            params + [per_page, (page - 1) * per_page],
        )
        pages = max(1, (total + per_page - 1) // per_page)
        return render_template("admin/audit.html", rows=rows, action=action, actions=auth.AUDIT_ACTIONS,
                               page=page, pages=pages, total=total)


def register_error_handlers(app):

    @app.errorhandler(HTTPException)
    def http_error(e):
        code = e.code if e.code in ERROR_TEXT else 500
        title, message = ERROR_TEXT[code]
        if code == 400 and e.description and "表單" in e.description:
            message = e.description
        return render_template("error.html", code=code, title=title, message=message), code

    @app.errorhandler(Exception)
    def server_error(e):
        app.logger.exception("未預期的錯誤")
        title, message = ERROR_TEXT[500]
        return render_template("error.html", code=500, title=title, message=message), 500


if __name__ == "__main__":
    create_app().run(debug=os.environ.get("FLASK_DEBUG") == "1")
