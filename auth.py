"""登入、註冊、權限檢查、CSRF、帳號鎖定與操作日誌。"""
import functools
import re
import secrets
from datetime import datetime, timedelta

from flask import (Blueprint, abort, current_app, flash, g, redirect,
                   render_template, request, session, url_for)
from werkzeug.security import check_password_hash, generate_password_hash

from db import execute, now_iso, query_one

bp = Blueprint("auth", __name__)

USERNAME_RE = re.compile(r"^[A-Za-z0-9_]{4,30}$")
LOGIN_ERROR = "帳號或密碼錯誤，或帳號已暫時鎖定，請稍後再試。"

AUDIT_ACTIONS = [
    "login_success", "login_failed", "account_locked", "register", "logout",
    "case_upload", "case_analyze", "case_delete", "feedback", "access_denied", "rate_limited",
]


# ---------- 驗證規則 ----------

def validate_username(username):
    if not USERNAME_RE.match(username):
        return "帳號需為 4–30 個字元，只能使用英文字母、數字與底線。"
    return None


def validate_password(password):
    if len(password) < 8 or not re.search(r"[A-Za-z]", password) or not re.search(r"\d", password):
        return "密碼至少 8 碼，且需同時包含英文字母與數字。"
    return None


# ---------- 操作日誌 ----------

def log_event(action, target=None, detail=None, user_id=None):
    """寫入操作日誌。detail 不得包含對話內容、個資原值或密碼。"""
    if user_id is None and g.get("user") is not None:
        user_id = g.user["id"]
    execute(
        "INSERT INTO audit_logs (user_id, action, target, detail, ip, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (user_id, action, target, detail, request.remote_addr, now_iso()),
    )


# ---------- CSRF ----------

def csrf_token():
    if "_csrf" not in session:
        session["_csrf"] = secrets.token_urlsafe(32)
    return session["_csrf"]


def check_csrf():
    if request.method != "POST":
        return
    sent = request.form.get("_csrf") or request.headers.get("X-CSRF-Token") or ""
    expected = session.get("_csrf") or ""
    if not expected or not secrets.compare_digest(sent, expected):
        abort(400, description="表單已過期或來源不正確，請重新整理頁面後再試。")


# ---------- 登入狀態與權限 ----------

def load_user():
    user_id = session.get("user_id")
    g.user = query_one("SELECT id, username, role FROM users WHERE id = ?", (user_id,)) if user_id else None


def login_required(view):
    @functools.wraps(view)
    def wrapped(*args, **kwargs):
        if g.user is None:
            return redirect(url_for("auth.login", next=request.path))
        return view(*args, **kwargs)
    return wrapped


def admin_required(view):
    @functools.wraps(view)
    def wrapped(*args, **kwargs):
        if g.user is None:
            return redirect(url_for("auth.login", next=request.path))
        if g.user["role"] != "admin":
            abort(403)
        return view(*args, **kwargs)
    return wrapped


def is_admin():
    return g.get("user") is not None and g.user["role"] == "admin"


def init_app(app):
    app.before_request(load_user)
    app.before_request(check_csrf)
    app.jinja_env.globals["csrf_token"] = csrf_token
    app.register_blueprint(bp)


# ---------- 路由 ----------

@bp.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        error = validate_username(username) or validate_password(password)
        if not error and query_one("SELECT 1 FROM users WHERE username = ?", (username,)):
            error = "這個帳號已被使用。"
        if error:
            flash(error, "error")
            return render_template("register.html", username=username), 400
        user_id = execute(
            "INSERT INTO users (username, password_hash, role, created_at) VALUES (?, ?, 'user', ?)",
            (username, generate_password_hash(password), now_iso()),
        )
        log_event("register", target=f"user:{user_id}", user_id=user_id)
        flash("註冊成功，請登入。", "success")
        return redirect(url_for("auth.login"))
    return render_template("register.html", username="")


@bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        user = query_one("SELECT * FROM users WHERE username = ?", (username,))
        now = datetime.now()

        if user is None:
            log_event("login_failed", detail="unknown_user", user_id=None)
            flash(LOGIN_ERROR, "error")
            return render_template("login.html", username=username), 401

        locked = user["locked_until"] and datetime.fromisoformat(user["locked_until"]) > now
        if locked:
            log_event("login_failed", target=f"user:{user['id']}", detail="locked", user_id=user["id"])
            flash(LOGIN_ERROR, "error")
            return render_template("login.html", username=username), 401

        if not check_password_hash(user["password_hash"], password):
            failed = user["failed_logins"] + 1
            log_event("login_failed", target=f"user:{user['id']}", detail="bad_password", user_id=user["id"])
            if failed >= current_app.config["MAX_FAILED_LOGINS"]:
                until = (now + timedelta(minutes=current_app.config["LOCK_MINUTES"])).isoformat(timespec="seconds")
                execute("UPDATE users SET failed_logins = 0, locked_until = ? WHERE id = ?", (until, user["id"]))
                log_event("account_locked", target=f"user:{user['id']}", detail=f"until {until}", user_id=user["id"])
            else:
                execute("UPDATE users SET failed_logins = ? WHERE id = ?", (failed, user["id"]))
            flash(LOGIN_ERROR, "error")
            return render_template("login.html", username=username), 401

        execute("UPDATE users SET failed_logins = 0, locked_until = NULL WHERE id = ?", (user["id"],))
        # 登入後重新產生 Session，避免 Session 固定攻擊
        session.clear()
        session["user_id"] = user["id"]
        csrf_token()
        g.user = user
        log_event("login_success", target=f"user:{user['id']}", user_id=user["id"])
        next_url = request.args.get("next", "")
        if not next_url.startswith("/") or next_url.startswith("//"):
            next_url = url_for("cases_list")
        return redirect(next_url)
    return render_template("login.html", username="")


@bp.route("/logout", methods=["POST"])
def logout():
    if g.user is not None:
        log_event("logout", target=f"user:{g.user['id']}")
    session.clear()
    return redirect(url_for("index"))
