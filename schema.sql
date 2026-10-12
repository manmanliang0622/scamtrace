-- 詐騙對話話術分析系統 資料表
-- 時間欄位一律為本地時間 ISO 8601（YYYY-MM-DDTHH:MM:SS）

CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    role          TEXT NOT NULL DEFAULT 'user' CHECK (role IN ('user', 'admin')),
    failed_logins INTEGER NOT NULL DEFAULT 0,
    locked_until  TEXT,
    created_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S', 'now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS scam_types (
    id          INTEGER PRIMARY KEY,
    code        TEXT UNIQUE,
    name        TEXT NOT NULL,
    description TEXT
);

CREATE TABLE IF NOT EXISTS tactics (
    id          INTEGER PRIMARY KEY,
    code        TEXT UNIQUE,
    name        TEXT NOT NULL,
    name_en     TEXT NOT NULL,
    description TEXT,
    color       TEXT
);

CREATE TABLE IF NOT EXISTS cases (
    id                INTEGER PRIMARY KEY,
    user_id           INTEGER NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    title             TEXT NOT NULL,
    source_type       TEXT CHECK (source_type IN ('line_txt', 'paste')),
    is_demo           INTEGER NOT NULL DEFAULT 0,
    message_count     INTEGER NOT NULL,
    period_start      TEXT,
    period_end        TEXT,
    status            TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'analyzed', 'failed')),
    overall_risk      INTEGER CHECK (overall_risk BETWEEN 0 AND 100),
    risk_level        TEXT CHECK (risk_level IN ('low', 'medium', 'high')),
    scam_type_id      INTEGER REFERENCES scam_types (id),
    summary           TEXT,
    turning_point_seq INTEGER,
    analyzed_by       TEXT CHECK (analyzed_by IN ('llm', 'rule')),
    model_name        TEXT,
    created_at        TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S', 'now', 'localtime')),
    analyzed_at       TEXT
);

CREATE TABLE IF NOT EXISTS messages (
    id              INTEGER PRIMARY KEY,
    case_id         INTEGER NOT NULL REFERENCES cases (id) ON DELETE CASCADE,
    seq             INTEGER NOT NULL,
    sent_at         TEXT,
    speaker         TEXT NOT NULL,
    is_self         INTEGER NOT NULL,
    masked_text     TEXT NOT NULL,
    msg_type        TEXT NOT NULL DEFAULT 'text'
                    CHECK (msg_type IN ('text', 'sticker', 'image', 'file', 'call', 'system')),
    stage           TEXT CHECK (stage IN ('contact', 'rapport', 'setup', 'action', 'pressure', 'none')),
    risk_score      INTEGER CHECK (risk_score BETWEEN 0 AND 100),
    requests_action INTEGER NOT NULL DEFAULT 0,
    UNIQUE (case_id, seq)
);

CREATE TABLE IF NOT EXISTS message_tactics (
    message_id INTEGER NOT NULL REFERENCES messages (id) ON DELETE CASCADE,
    tactic_id  INTEGER NOT NULL REFERENCES tactics (id),
    evidence   TEXT NOT NULL,
    confidence REAL CHECK (confidence BETWEEN 0 AND 1),
    PRIMARY KEY (message_id, tactic_id)
);

CREATE TABLE IF NOT EXISTS case_pii_stats (
    case_id  INTEGER NOT NULL REFERENCES cases (id) ON DELETE CASCADE,
    pii_type TEXT NOT NULL,
    count    INTEGER NOT NULL,
    PRIMARY KEY (case_id, pii_type)
);

CREATE TABLE IF NOT EXISTS feedback (
    id                  INTEGER PRIMARY KEY,
    case_id             INTEGER NOT NULL REFERENCES cases (id) ON DELETE CASCADE,
    message_id          INTEGER REFERENCES messages (id) ON DELETE CASCADE,
    user_id             INTEGER REFERENCES users (id) ON DELETE CASCADE,
    is_correct          INTEGER NOT NULL,
    corrected_tactic_id INTEGER REFERENCES tactics (id),
    comment             TEXT CHECK (comment IS NULL OR length(comment) <= 200),
    created_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S', 'now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS audit_logs (
    id         INTEGER PRIMARY KEY,
    user_id    INTEGER REFERENCES users (id) ON DELETE SET NULL,
    action     TEXT NOT NULL,
    target     TEXT,
    detail     TEXT,
    ip         TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S', 'now', 'localtime'))
);

CREATE INDEX IF NOT EXISTS idx_messages_case_seq ON messages (case_id, seq);
CREATE INDEX IF NOT EXISTS idx_cases_user_created ON cases (user_id, created_at);
CREATE INDEX IF NOT EXISTS idx_audit_created ON audit_logs (created_at);
CREATE INDEX IF NOT EXISTS idx_message_tactics_tactic ON message_tactics (tactic_id);
