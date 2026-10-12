"""應用程式設定。機密值一律從環境變數讀取，不寫在程式碼中。"""
import os


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY")
    ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")

    # 上傳與請求大小上限：1 MB
    MAX_CONTENT_LENGTH = 1024 * 1024

    # Session Cookie
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    # 部署到 HTTPS 時設定 SESSION_COOKIE_SECURE=1
    SESSION_COOKIE_SECURE = os.environ.get("SESSION_COOKIE_SECURE") == "1"

    # 預覽暫存檔有效時間（秒）
    PENDING_TTL_SECONDS = 30 * 60

    # 每位使用者每小時分析次數上限
    ANALYZE_LIMIT_PER_HOUR = 20

    # 登入失敗鎖定
    MAX_FAILED_LOGINS = 5
    LOCK_MINUTES = 15

    # 匯入限制
    MAX_MESSAGES = 2000

    # 語言模型
    MODEL_NAME = "claude-opus-5-5"
    CHUNK_SIZE = 150
    CHUNK_OVERLAP = 10
