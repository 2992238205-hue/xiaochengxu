import json
import os
import re
import sqlite3
import time
import uuid
import hashlib
import secrets
import io
import zipfile
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from html import unescape
from pathlib import Path
from urllib.parse import quote
from urllib.request import Request, urlopen

from flask import Flask, jsonify, redirect, request, send_from_directory, g, make_response

try:
    from zoneinfo import ZoneInfo
except Exception:
    ZoneInfo = None

try:
    from backend.novel_agents import (
        MoonshotClient,
        NovelAgentOrchestrator,
        STUDENT_PROFILE_TEMPLATE,
        build_orchestrator_from_env,
        chunk_text,
        now_iso,
        normalize_student_profile,
        select_knowledge,
    )
except Exception:
    from novel_agents import (
        MoonshotClient,
        NovelAgentOrchestrator,
        STUDENT_PROFILE_TEMPLATE,
        build_orchestrator_from_env,
        chunk_text,
        normalize_student_profile,
        now_iso,
        select_knowledge,
    )

try:
    from backend.transcription_service import (
        SUPPORTED_MEDIA_EXTS,
        normalize_language,
        parse_term_text,
        read_low_conf_threshold,
        safe_filename,
    )
    from backend.transcription_worker import TranscriptionWorker
except Exception:
    from transcription_service import (
        SUPPORTED_MEDIA_EXTS,
        normalize_language,
        parse_term_text,
        read_low_conf_threshold,
        safe_filename,
    )
    from transcription_worker import TranscriptionWorker


APP_ROOT = Path(__file__).resolve().parents[1]
DB_PATH = Path(os.getenv("BOOK_DB_PATH", APP_ROOT / "backend" / "books.db"))
DEFAULT_ADMIN_KEY = "change-this-admin-key"
ADMIN_KEY_FILE = Path(os.getenv("ADMIN_KEY_FILE", APP_ROOT / "backend" / ".admin_key"))
ADMIN_KEY = os.getenv("ADMIN_KEY", "").strip()
if not ADMIN_KEY:
    try:
        if ADMIN_KEY_FILE.exists():
            ADMIN_KEY = ADMIN_KEY_FILE.read_text(encoding="utf-8").strip()
    except Exception:
        ADMIN_KEY = ""
if not ADMIN_KEY:
    ADMIN_KEY = DEFAULT_ADMIN_KEY
ALLOW_ADMIN_BOOTSTRAP = os.getenv("ALLOW_ADMIN_BOOTSTRAP", "0") == "1"
SESSION_COOKIE_NAME = os.getenv("AUTH_SESSION_COOKIE", "reader_session")
SESSION_DAYS = int(os.getenv("AUTH_SESSION_DAYS", "30"))
OTP_EXPIRE_SECONDS = int(os.getenv("AUTH_OTP_EXPIRE_SECONDS", "300"))
OTP_COOLDOWN_SECONDS = int(os.getenv("AUTH_OTP_COOLDOWN_SECONDS", "60"))
OTP_MAX_ATTEMPTS = int(os.getenv("AUTH_OTP_MAX_ATTEMPTS", "5"))
AUTH_HASH_SECRET = os.getenv("AUTH_HASH_SECRET", "change-this-auth-hash-secret")
MONTHLY_GENERATION_LIMIT = int(os.getenv("GEN_MONTHLY_LIMIT", "20"))
AUTH_DEV_OTP_FALLBACK = os.getenv("AUTH_DEV_OTP_FALLBACK", "1") == "1"
COOKIE_SAMESITE_RAW = str(os.getenv("AUTH_COOKIE_SAMESITE", "Lax")).strip().lower()
COOKIE_SAMESITE = {"lax": "Lax", "strict": "Strict", "none": "None"}.get(
    COOKIE_SAMESITE_RAW, "Lax"
)
COOKIE_SECURE = os.getenv("AUTH_COOKIE_SECURE", "0") == "1"
UPLOAD_DIR = Path(os.getenv("COVER_UPLOAD_DIR", APP_ROOT / "content" / "user_covers"))
MAX_COVER_UPLOAD_BYTES = int(os.getenv("MAX_COVER_UPLOAD_BYTES", str(2 * 1024 * 1024)))
ALLOWED_COVER_EXTS = {".jpg", ".jpeg", ".png", ".webp"}
TRANSCRIBE_UPLOAD_DIR = Path(
    os.getenv("TRANSCRIBE_UPLOAD_DIR", APP_ROOT / "content" / "transcription_uploads")
)
TRANSCRIBE_OUTPUT_DIR = Path(
    os.getenv("TRANSCRIBE_OUTPUT_DIR", APP_ROOT / "content" / "transcription_outputs")
)
MAX_TRANSCRIBE_UPLOAD_BYTES = int(os.getenv("MAX_TRANSCRIBE_UPLOAD_BYTES", str(2 * 1024 * 1024 * 1024)))
MAX_TRANSCRIBE_BATCH = int(os.getenv("MAX_TRANSCRIBE_BATCH", "10"))
ENABLE_TRANSCRIPTION_WORKER = os.getenv("ENABLE_TRANSCRIPTION_WORKER", "1") == "1"
TRANSCRIBE_PROVIDER = str(os.getenv("TRANSCRIBE_PROVIDER", "kimi")).strip().lower() or "kimi"

if ZoneInfo is not None:
    SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")
else:
    SHANGHAI_TZ = timezone(timedelta(hours=8))

app = Flask(__name__, static_folder=str(APP_ROOT), static_url_path="")

DICT_CACHE = {}
DICT_CACHE_LIMIT = 4000
WORD_OVERRIDE = {
    "artificial": "人工的；人造的",
    "status": "状态；地位",
    "instant": "瞬间；立即的",
}
PHRASE_OVERRIDE = {
    "artificial intelligence": "人工智能",
    "machine learning": "机器学习",
    "deep learning": "深度学习",
    "natural language processing": "自然语言处理",
}


def db_conn():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with db_conn() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS books (
              id TEXT PRIMARY KEY,
              title TEXT NOT NULL,
              description TEXT NOT NULL,
              word_goal INTEGER NOT NULL DEFAULT 3500,
              updated_at TEXT NOT NULL,
              cover_url TEXT NOT NULL DEFAULT '',
              category TEXT NOT NULL DEFAULT '',
              sort_order INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
              id TEXT PRIMARY KEY,
              phone_e164 TEXT NOT NULL UNIQUE,
              status TEXT NOT NULL DEFAULT 'active',
              created_at TEXT NOT NULL,
              last_login_at TEXT NOT NULL DEFAULT ''
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS auth_otp_codes (
              id TEXT PRIMARY KEY,
              phone_e164 TEXT NOT NULL,
              code_hash TEXT NOT NULL,
              expires_at TEXT NOT NULL,
              attempt_count INTEGER NOT NULL DEFAULT 0,
              used_at TEXT NOT NULL DEFAULT '',
              client_ip TEXT NOT NULL DEFAULT '',
              created_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS auth_sessions (
              id TEXT PRIMARY KEY,
              user_id TEXT NOT NULL,
              token_hash TEXT NOT NULL UNIQUE,
              expires_at TEXT NOT NULL,
              revoked_at TEXT NOT NULL DEFAULT '',
              user_agent TEXT NOT NULL DEFAULT '',
              client_ip TEXT NOT NULL DEFAULT '',
              created_at TEXT NOT NULL,
              last_seen_at TEXT NOT NULL,
              FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS user_generated_books (
              id TEXT PRIMARY KEY,
              user_id TEXT NOT NULL,
              title TEXT NOT NULL,
              description TEXT NOT NULL DEFAULT '',
              word_goal INTEGER NOT NULL DEFAULT 3500,
              cover_url TEXT NOT NULL DEFAULT '',
              source TEXT NOT NULL DEFAULT 'story_lab',
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL,
              FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS user_generated_chapters (
              book_id TEXT NOT NULL,
              chapter_index INTEGER NOT NULL,
              title TEXT NOT NULL,
              english TEXT NOT NULL,
              chinese TEXT NOT NULL,
              target_words_json TEXT NOT NULL DEFAULT '[]',
              PRIMARY KEY (book_id, chapter_index),
              FOREIGN KEY (book_id) REFERENCES user_generated_books(id) ON DELETE CASCADE
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS user_reader_state (
              user_id TEXT PRIMARY KEY,
              profile_json TEXT NOT NULL DEFAULT '{}',
              progress_json TEXT NOT NULL DEFAULT '{}',
              settings_json TEXT NOT NULL DEFAULT '{}',
              comments_json TEXT NOT NULL DEFAULT '{}',
              updated_at TEXT NOT NULL,
              FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS user_reading_history (
              id TEXT PRIMARY KEY,
              user_id TEXT NOT NULL,
              book_id TEXT NOT NULL,
              chapter_index INTEGER NOT NULL DEFAULT 0,
              page_index INTEGER NOT NULL DEFAULT 0,
              book_title_snapshot TEXT NOT NULL DEFAULT '',
              chapter_title_snapshot TEXT NOT NULL DEFAULT '',
              viewed_at TEXT NOT NULL,
              FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS user_generation_logs (
              id TEXT PRIMARY KEY,
              user_id TEXT NOT NULL,
              month_key TEXT NOT NULL,
              provider TEXT NOT NULL DEFAULT '',
              status TEXT NOT NULL DEFAULT 'success',
              error_message TEXT NOT NULL DEFAULT '',
              group_count INTEGER NOT NULL DEFAULT 0,
              word_count INTEGER NOT NULL DEFAULT 0,
              created_at TEXT NOT NULL,
              FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_auth_otp_phone_created ON auth_otp_codes(phone_e164, created_at DESC)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_auth_sessions_user ON auth_sessions(user_id, created_at DESC)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_user_generated_books_user ON user_generated_books(user_id, updated_at DESC)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_user_reading_history_user ON user_reading_history(user_id, viewed_at DESC)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_user_generation_logs_user_month ON user_generation_logs(user_id, month_key, created_at DESC)"
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS chapters (
              book_id TEXT NOT NULL,
              chapter_index INTEGER NOT NULL,
              title TEXT NOT NULL,
              english TEXT NOT NULL,
              chinese TEXT NOT NULL,
              target_words_json TEXT NOT NULL DEFAULT '[]',
              PRIMARY KEY (book_id, chapter_index),
              FOREIGN KEY (book_id) REFERENCES books(id) ON DELETE CASCADE
            )
            """
        )


def ensure_book_columns():
    required_columns = {
        "cover_url": "TEXT NOT NULL DEFAULT ''",
        "category": "TEXT NOT NULL DEFAULT ''",
        "sort_order": "INTEGER NOT NULL DEFAULT 0",
    }
    with db_conn() as conn:
        rows = conn.execute("PRAGMA table_info(books)").fetchall()
        existing = {row["name"] for row in rows}
        for col, ddl in required_columns.items():
            if col in existing:
                continue
            conn.execute(f"ALTER TABLE books ADD COLUMN {col} {ddl}")


def init_novel_tables():
    with db_conn() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS novel_knowledge (
              id TEXT PRIMARY KEY,
              title TEXT NOT NULL,
              content TEXT NOT NULL,
              tags TEXT NOT NULL DEFAULT '',
              source TEXT NOT NULL DEFAULT '',
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS novel_chapter_outputs (
              id TEXT PRIMARY KEY,
              project_name TEXT NOT NULL,
              chapter_index INTEGER NOT NULL,
              total_chapters INTEGER NOT NULL,
              chapter_title TEXT NOT NULL,
              chapter_summary TEXT NOT NULL,
              chapter_text TEXT NOT NULL,
              hero_stage INTEGER NOT NULL DEFAULT 1,
              ai_capability_level INTEGER NOT NULL DEFAULT 1,
              energy_gain INTEGER NOT NULL DEFAULT 0,
              energy_after INTEGER NOT NULL DEFAULT 0,
              quality_score INTEGER NOT NULL DEFAULT 0,
              quality_passed INTEGER NOT NULL DEFAULT 0,
              knowledge_ids_json TEXT NOT NULL DEFAULT '[]',
              agent_trace_json TEXT NOT NULL DEFAULT '{}',
              created_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_novel_chapter_outputs_project
            ON novel_chapter_outputs(project_name, chapter_index DESC, created_at DESC)
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS novel_project_states (
              project_name TEXT PRIMARY KEY,
              state_json TEXT NOT NULL DEFAULT '{}',
              student_profile_json TEXT NOT NULL DEFAULT '{}',
              routing_json TEXT NOT NULL DEFAULT '{}',
              updated_at TEXT NOT NULL
            )
            """
        )


def init_transcription_tables():
    with db_conn() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS transcription_jobs (
              id TEXT PRIMARY KEY,
              file_name TEXT NOT NULL,
              source_path TEXT NOT NULL,
              language TEXT NOT NULL DEFAULT 'zh',
              term_text TEXT NOT NULL DEFAULT '',
              status TEXT NOT NULL DEFAULT 'queued',
              progress REAL NOT NULL DEFAULT 0,
              error_message TEXT NOT NULL DEFAULT '',
              output_md_path TEXT NOT NULL DEFAULT '',
              output_txt_path TEXT NOT NULL DEFAULT '',
              output_srt_path TEXT NOT NULL DEFAULT '',
              duration_sec REAL NOT NULL DEFAULT 0,
              segment_count INTEGER NOT NULL DEFAULT 0,
              low_conf_count INTEGER NOT NULL DEFAULT 0,
              provider_note TEXT NOT NULL DEFAULT '',
              created_at TEXT NOT NULL,
              started_at TEXT NOT NULL DEFAULT '',
              finished_at TEXT NOT NULL DEFAULT '',
              updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS transcription_segments (
              job_id TEXT NOT NULL,
              segment_index INTEGER NOT NULL,
              start_sec REAL NOT NULL DEFAULT 0,
              end_sec REAL NOT NULL DEFAULT 0,
              text TEXT NOT NULL DEFAULT '',
              confidence REAL NOT NULL DEFAULT 0,
              engine TEXT NOT NULL DEFAULT 'local_whisper',
              is_low_conf INTEGER NOT NULL DEFAULT 0,
              PRIMARY KEY (job_id, segment_index),
              FOREIGN KEY (job_id) REFERENCES transcription_jobs(id) ON DELETE CASCADE
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS transcription_terms (
              source_term TEXT PRIMARY KEY,
              replacement_term TEXT NOT NULL,
              updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_transcription_jobs_status_created ON transcription_jobs(status, created_at DESC)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_transcription_segments_job_idx ON transcription_segments(job_id, segment_index ASC)"
        )


def require_admin():
    import base64
    raw = request.headers.get("X-Admin-Key", "")
    # Try base64 decode first (frontend encodes to avoid non-ASCII header issues)
    try:
        key = base64.b64decode(raw).decode("utf-8")
    except Exception:
        key = raw
    return bool(key) and key == ADMIN_KEY


def validate_admin_key(value):
    key = normalize_text(value)
    if len(key) < 6:
        return "管理员密钥至少 6 位"
    if any(ch.isspace() for ch in key):
        return "管理员密钥不能包含空格"
    return ""


def save_admin_key(value):
    global ADMIN_KEY
    key = normalize_text(value)
    err = validate_admin_key(key)
    if err:
        raise ValueError(err)
    ADMIN_KEY_FILE.parent.mkdir(parents=True, exist_ok=True)
    ADMIN_KEY_FILE.write_text(key, encoding="utf-8")
    ADMIN_KEY = key


def normalize_text(value):
    if value is None:
        return ""
    text = str(value)
    for _ in range(3):
        decoded = unescape(text)
        if decoded == text:
            break
        text = decoded
    return text.strip()


def normalize_word(value):
    text = normalize_text(value).lower()
    text = re.sub(r"[^a-zA-Z'\-\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def utc_now_iso():
    return datetime.utcnow().isoformat(timespec="seconds")


def now_shanghai():
    return datetime.now(SHANGHAI_TZ)


def current_month_key():
    return now_shanghai().strftime("%Y-%m")


def month_key_for_utc_iso(utc_iso_text):
    text = normalize_text(utc_iso_text)
    if not text:
        return current_month_key()
    try:
        dt_utc = datetime.fromisoformat(text)
        if dt_utc.tzinfo is None:
            dt_utc = dt_utc.replace(tzinfo=timezone.utc)
        dt_sh = dt_utc.astimezone(SHANGHAI_TZ)
        return dt_sh.strftime("%Y-%m")
    except Exception:
        return current_month_key()


def hash_auth_value(raw_text):
    base = f"{AUTH_HASH_SECRET}|{normalize_text(raw_text)}".encode("utf-8")
    return hashlib.sha256(base).hexdigest()


def normalize_phone_cn(raw_phone):
    text = normalize_text(raw_phone)
    if not text:
        return ""
    digits = re.sub(r"\D", "", text)
    if len(digits) == 13 and digits.startswith("86"):
        digits = digits[2:]
    if len(digits) == 11 and digits.startswith("1"):
        return f"+86{digits}"
    return ""


def mask_phone_e164(phone_e164):
    text = normalize_text(phone_e164)
    match = re.match(r"^\+86(\d{11})$", text)
    if not match:
        return ""
    digits = match.group(1)
    return f"{digits[:3]}****{digits[-4:]}"


def sms_phone_for_provider(phone_e164):
    match = re.match(r"^\+86(\d{11})$", normalize_text(phone_e164))
    if not match:
        return ""
    return match.group(1)


def current_request_ip():
    forwarded = normalize_text(request.headers.get("X-Forwarded-For", ""))
    if forwarded:
        return normalize_text(forwarded.split(",")[0])
    return normalize_text(request.remote_addr)


def current_user_agent():
    return normalize_text(request.headers.get("User-Agent", ""))


def trim_translation(value, max_len=88):
    text = normalize_text(value)
    if not text:
        return ""
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"\s+", " ", text).strip("；;，,。 ")
    if len(text) > max_len:
        return f"{text[:max_len]}..."
    return text


def take_first_text(node):
    if isinstance(node, str):
        return node
    if isinstance(node, list):
        for item in node:
            found = take_first_text(item)
            if found:
                return found
        return ""
    if isinstance(node, dict):
        for key in ("i", "l", "value", "#text"):
            if key in node:
                found = take_first_text(node.get(key))
                if found:
                    return found
        for value in node.values():
            found = take_first_text(value)
            if found:
                return found
    return ""


def fetch_json(url):
    req = Request(url, headers={"User-Agent": "Mozilla/5.0 EnglishReader/1.0"})
    with urlopen(req, timeout=3.5) as resp:
        return json.loads(resp.read().decode("utf-8", errors="ignore"))


def send_sms_code_via_aliyun(phone_e164, code):
    phone_digits = sms_phone_for_provider(phone_e164)
    if not phone_digits:
        raise ValueError("手机号格式错误，仅支持中国大陆 +86")

    if AUTH_DEV_OTP_FALLBACK:
        print(f"[OTP DEV] phone={phone_e164} code={code}")
        return {"provider": "dev-fallback"}

    access_key_id = normalize_text(os.getenv("ALIYUN_SMS_ACCESS_KEY_ID", ""))
    access_key_secret = normalize_text(os.getenv("ALIYUN_SMS_ACCESS_KEY_SECRET", ""))
    sign_name = normalize_text(os.getenv("ALIYUN_SMS_SIGN_NAME", ""))
    template_code = normalize_text(os.getenv("ALIYUN_SMS_TEMPLATE_CODE", ""))
    if not all([access_key_id, access_key_secret, sign_name, template_code]):
        raise ValueError("短信服务未配置完整，请检查阿里云短信环境变量")

    try:
        from alibabacloud_dysmsapi20170525.client import Client as DysmsapiClient
        from alibabacloud_tea_openapi import models as OpenApiModels
        from alibabacloud_dysmsapi20170525 import models as DysmsapiModels
    except Exception as exc:
        raise ValueError(f"阿里云短信依赖缺失：{exc}") from exc

    config = OpenApiModels.Config(
        access_key_id=access_key_id,
        access_key_secret=access_key_secret,
        endpoint="dysmsapi.aliyuncs.com",
    )
    client = DysmsapiClient(config)
    req = DysmsapiModels.SendSmsRequest(
        phone_numbers=phone_digits,
        sign_name=sign_name,
        template_code=template_code,
        template_param=json.dumps({"code": str(code)}, ensure_ascii=False),
    )
    resp = client.send_sms(req)
    body = getattr(resp, "body", None)
    if not body:
        raise ValueError("短信服务响应为空")
    resp_code = normalize_text(getattr(body, "code", ""))
    resp_message = normalize_text(getattr(body, "message", ""))
    if resp_code != "OK":
        raise ValueError(f"短信发送失败：{resp_code or 'UNKNOWN'} {resp_message}")
    return {"provider": "aliyun", "bizId": normalize_text(getattr(body, "biz_id", ""))}


def create_or_get_user(phone_e164):
    now = utc_now_iso()
    with db_conn() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE phone_e164 = ?",
            (phone_e164,),
        ).fetchone()
        if row:
            conn.execute(
                "UPDATE users SET last_login_at = ? WHERE id = ?",
                (now, row["id"]),
            )
            return dict(row)
        user_id = f"user-{uuid.uuid4().hex[:12]}"
        conn.execute(
            """
            INSERT INTO users (id, phone_e164, status, created_at, last_login_at)
            VALUES (?, ?, 'active', ?, ?)
            """,
            (user_id, phone_e164, now, now),
        )
        created = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        return dict(created)


def create_user_session(user_id):
    token = secrets.token_urlsafe(36)
    token_hash = hash_auth_value(f"session:{token}")
    now = utc_now_iso()
    expires = (datetime.utcnow() + timedelta(days=max(1, SESSION_DAYS))).isoformat(timespec="seconds")
    session_id = f"sess-{uuid.uuid4().hex[:12]}"
    with db_conn() as conn:
        conn.execute(
            """
            INSERT INTO auth_sessions (
              id, user_id, token_hash, expires_at, revoked_at, user_agent, client_ip, created_at, last_seen_at
            ) VALUES (?, ?, ?, ?, '', ?, ?, ?, ?)
            """,
            (
                session_id,
                user_id,
                token_hash,
                expires,
                current_user_agent(),
                current_request_ip(),
                now,
                now,
            ),
        )
    return token, expires


def get_session_user_from_request():
    cached = getattr(g, "_current_user", None)
    if cached is not None:
        return cached

    token = normalize_text(request.cookies.get(SESSION_COOKIE_NAME, ""))
    if not token:
        g._current_user = None
        return None
    token_hash = hash_auth_value(f"session:{token}")
    now = utc_now_iso()
    with db_conn() as conn:
        row = conn.execute(
            """
            SELECT u.*
            FROM auth_sessions s
            JOIN users u ON u.id = s.user_id
            WHERE s.token_hash = ? AND s.revoked_at = '' AND s.expires_at > ? AND u.status = 'active'
            ORDER BY s.created_at DESC
            LIMIT 1
            """,
            (token_hash, now),
        ).fetchone()
        if not row:
            g._current_user = None
            return None
        conn.execute(
            "UPDATE auth_sessions SET last_seen_at = ? WHERE token_hash = ?",
            (now, token_hash),
        )
        g._current_user = dict(row)
        return g._current_user


def require_login_user():
    user = get_session_user_from_request()
    if not user:
        return None, (jsonify({"ok": False, "error": "请先手机号登录后再操作。"}), 401)
    return user, None


def revoke_current_session():
    token = normalize_text(request.cookies.get(SESSION_COOKIE_NAME, ""))
    if not token:
        return
    token_hash = hash_auth_value(f"session:{token}")
    with db_conn() as conn:
        conn.execute(
            "UPDATE auth_sessions SET revoked_at = ? WHERE token_hash = ?",
            (utc_now_iso(), token_hash),
        )


def count_monthly_generation(user_id, month_key):
    with db_conn() as conn:
        row = conn.execute(
            """
            SELECT COUNT(1) AS c
            FROM user_generation_logs
            WHERE user_id = ? AND month_key = ? AND status IN ('success', 'failed')
            """,
            (user_id, month_key),
        ).fetchone()
    return int((row["c"] if row else 0) or 0)


def write_generation_log(user_id, status, provider="", group_count=0, word_count=0, error_message=""):
    if not user_id:
        return
    now = utc_now_iso()
    month_key = month_key_for_utc_iso(now)
    with db_conn() as conn:
        conn.execute(
            """
            INSERT INTO user_generation_logs (
              id, user_id, month_key, provider, status, error_message, group_count, word_count, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                f"ugl-{uuid.uuid4().hex[:12]}",
                user_id,
                month_key,
                normalize_text(provider),
                normalize_text(status) or "failed",
                normalize_text(error_message),
                int(group_count or 0),
                int(word_count or 0),
                now,
            ),
        )


def fetch_youdao_translation(query):
    url = f"https://dict.youdao.com/jsonapi?q={quote(query)}"
    try:
        data = fetch_json(url)
    except Exception:
        return ""

    ec = data.get("ec")
    if isinstance(ec, dict):
        word_node = ec.get("word")
        if isinstance(word_node, list):
            word_node = word_node[0] if word_node else {}
        if isinstance(word_node, dict):
            trs = word_node.get("trs")
            if isinstance(trs, list):
                for item in trs:
                    tr = item.get("tr") if isinstance(item, dict) else None
                    meaning = trim_translation(take_first_text(tr))
                    if meaning:
                        return meaning

    web_trans = data.get("web_trans")
    if isinstance(web_trans, dict):
        rows = web_trans.get("web-translation")
        if isinstance(rows, list):
            for row in rows:
                trans = row.get("trans") if isinstance(row, dict) else None
                if isinstance(trans, list) and trans:
                    value = trans[0].get("value") if isinstance(trans[0], dict) else ""
                    meaning = trim_translation(value)
                    if meaning:
                        return meaning

    simple = data.get("simple")
    if isinstance(simple, dict):
        word = simple.get("word")
        if isinstance(word, list):
            word = word[0] if word else {}
        if isinstance(word, dict):
            trs = word.get("trs")
            if isinstance(trs, list):
                for item in trs:
                    tr = item.get("tr") if isinstance(item, dict) else None
                    meaning = trim_translation(take_first_text(tr))
                    if meaning:
                        return meaning

    return ""


def fetch_mymemory_translation(query):
    url = f"https://api.mymemory.translated.net/get?q={quote(query)}&langpair=en|zh-CN"
    try:
        data = fetch_json(url)
    except Exception:
        return ""
    translated = trim_translation((data or {}).get("responseData", {}).get("translatedText", ""))
    if translated and translated.lower() != normalize_word(query):
        return translated
    return ""


def context_phrase(word, context, prev_word="", next_word=""):
    word = normalize_word(word)
    prev_word = normalize_word(prev_word)
    next_word = normalize_word(next_word)

    candidates = []
    if prev_word and word:
        candidates.append(f"{prev_word} {word}")
    if word and next_word:
        candidates.append(f"{word} {next_word}")
    if prev_word and word and next_word:
        candidates.append(f"{prev_word} {word} {next_word}")

    tokens = re.findall(r"[A-Za-z][A-Za-z'-]*", (context or "").lower())
    for i, token in enumerate(tokens):
        if token != word:
            continue
        if i > 0:
            candidates.append(f"{tokens[i - 1]} {token}")
        if i + 1 < len(tokens):
            candidates.append(f"{token} {tokens[i + 1]}")
        if i > 0 and i + 1 < len(tokens):
            candidates.append(f"{tokens[i - 1]} {token} {tokens[i + 1]}")

    for candidate in candidates:
        normalized = normalize_word(candidate)
        if normalized in PHRASE_OVERRIDE:
            return normalized, PHRASE_OVERRIDE[normalized]
    return "", ""


def lookup_dictionary(word, context="", prev_word="", next_word=""):
    normalized_word = normalize_word(word)
    if not normalized_word:
        return {
            "ok": False,
            "word": "",
            "lookup": "",
            "translation": "",
            "source": "",
            "cached": False,
        }

    phrase, phrase_translation = context_phrase(
        normalized_word, context=context, prev_word=prev_word, next_word=next_word
    )
    if phrase and phrase_translation:
        return {
            "ok": True,
            "word": normalized_word,
            "lookup": phrase,
            "translation": phrase_translation,
            "source": "phrase_override",
            "cached": True,
        }

    if normalized_word in DICT_CACHE:
        cached_result = dict(DICT_CACHE[normalized_word])
        cached_result["cached"] = True
        return cached_result

    if normalized_word in WORD_OVERRIDE:
        result = {
            "ok": True,
            "word": normalized_word,
            "lookup": normalized_word,
            "translation": WORD_OVERRIDE[normalized_word],
            "source": "word_override",
            "cached": False,
        }
        DICT_CACHE[normalized_word] = result
        return result

    translation = fetch_youdao_translation(normalized_word)
    source = "youdao"
    if not translation:
        translation = fetch_mymemory_translation(normalized_word)
        source = "mymemory"

    result = {
        "ok": bool(translation),
        "word": normalized_word,
        "lookup": normalized_word,
        "translation": translation or "",
        "source": source if translation else "",
        "cached": False,
    }
    DICT_CACHE[normalized_word] = result
    if len(DICT_CACHE) > DICT_CACHE_LIMIT:
        DICT_CACHE.pop(next(iter(DICT_CACHE)))
    return result


def normalize_book(raw_book):
    raw_chapters = raw_book.get("chapters", [])
    if not isinstance(raw_chapters, list):
        raw_chapters = []

    chapters = []
    for idx, ch in enumerate(raw_chapters):
        if not isinstance(ch, dict):
            continue
        english = normalize_text(ch.get("english") or ch.get("content"))
        chinese = normalize_text(ch.get("chinese"))
        display_text = english or chinese
        if not display_text:
            continue

        target_words_raw = ch.get("targetWords", [])
        if not isinstance(target_words_raw, list):
            target_words_raw = []
        target_words = []
        for item in target_words_raw:
            if not isinstance(item, dict):
                continue
            word = normalize_text(item.get("word"))
            translation = normalize_text(item.get("translation"))
            if not word:
                continue
            target_words.append(
                {
                    "word": word,
                    "translation": translation or "未提供翻译",
                }
            )

        chapters.append(
            {
                "title": normalize_text(ch.get("title")) or f"Chapter {idx + 1}",
                "english": display_text,
                "chinese": chinese,
                "targetWords": target_words,
            }
        )

    if not chapters:
        raise ValueError("书籍章节为空，至少需要一章正文。")

    return {
        "id": normalize_text(raw_book.get("id")) or f"book-{uuid.uuid4().hex[:12]}",
        "title": normalize_text(raw_book.get("title")) or "未命名小说",
        "description": normalize_text(raw_book.get("description")) or "后台上传书籍",
        "wordGoal": int(raw_book.get("wordGoal") or 3500),
        "coverUrl": normalize_text(raw_book.get("coverUrl")),
        "category": normalize_text(raw_book.get("category")),
        "sortOrder": int(raw_book.get("sortOrder") or 0),
        "chapters": chapters,
    }


def strip_markdown_line(line):
    text = normalize_text(unescape(line))
    if not text:
        return ""
    if re.match(r"^\s{0,3}#{1,6}\s+", text):
        text = re.sub(r"^\s{0,3}#{1,6}\s+", "", text)
    text = re.sub(r"^\s{0,3}>\s?", "", text)
    text = re.sub(r"^\s*[-*+]\s+", "", text)
    text = re.sub(r"^\s*\d+[.)、]\s+", "", text)
    text = re.sub(r"!\[([^\]]*)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = text.replace("**", "").replace("__", "").replace("~~", "").replace("`", "")
    text = normalize_text(text)
    return text


def parse_markdown_book(content, file_name):
    lines = [
        unescape(line)
        for line in content.replace("\ufeff", "").replace("\r", "").split("\n")
    ]
    heading_regex = re.compile(r"^\s{0,3}(#{1,6})\s+(.*?)\s*$")
    chapter_regex = re.compile(
        r"(第\s*(\d+|[一二三四五六七八九十百零两]+)\s*[章节组回课篇册节]|chapter\s*[-#:：]?\s*\d+|\bch\s*[-#:：]?\s*\d+)",
        re.IGNORECASE,
    )
    # Allow mixed formats:
    # - Some chapters use Markdown headings (# 第1章)
    # - Other chapters are plain lines (第2章 ...)
    # We treat any line starting with a chapter marker as a chapter split.
    chapter_start_regex = re.compile(
        r"^\s*(第\s*(\d+|[一二三四五六七八九十百零两]+)\s*[章节组回课篇册节]|chapter\s*[-#:：]?\s*\d+|\bch\s*[-#:：]?\s*\d+)",
        re.IGNORECASE,
    )

    headings = []
    for idx, line in enumerate(lines):
        match = heading_regex.match(line)
        if not match:
            continue
        headings.append(
            {
                "line": idx,
                "level": len(match.group(1)),
                "title": normalize_text(match.group(2)),
            }
        )

    chapter_headings = [h for h in headings if chapter_regex.search(h["title"])]
    seen_chapter_lines = {int(h["line"]) for h in chapter_headings}
    for idx, line in enumerate(lines):
        if idx in seen_chapter_lines:
            continue
        plain = strip_markdown_line(line)
        if not plain:
            continue
        if chapter_start_regex.search(plain):
            chapter_headings.append({"line": idx, "level": 1, "title": plain})
            seen_chapter_lines.add(idx)

    first_h1 = next(
        (h for h in headings if h["level"] == 1 and not chapter_regex.search(h["title"])),
        None,
    )
    fallback_title = re.sub(r"\.[^.]+$", "", file_name or "未命名小说")
    if first_h1:
        book_title = first_h1["title"]
    else:
        first_content_line = next((normalize_text(item) for item in lines if normalize_text(item)), "")
        if first_content_line and not chapter_regex.search(first_content_line):
            book_title = strip_markdown_line(first_content_line)
        else:
            book_title = fallback_title

    chapters = []
    if not chapter_headings:
        cleaned = []
        last_blank = False
        for line in lines:
            trimmed = normalize_text(line)
            if not trimmed:
                if not last_blank:
                    cleaned.append("")
                    last_blank = True
                continue
            plain = strip_markdown_line(line)
            if not plain:
                continue
            cleaned.append(plain)
            last_blank = False
        body = "\n".join(cleaned).strip()
        if not body:
            raise ValueError("Markdown 正文为空。")
        chapters.append(
            {
                "title": "Chapter 1",
                "english": body,
                "chinese": body if re.search(r"[\u4e00-\u9fff]", body) else "",
                "targetWords": [],
            }
        )
    else:
        dedup_headings = []
        seen_lines = set()
        for heading in chapter_headings:
            line_no = int(heading["line"])
            if line_no in seen_lines:
                continue
            dedup_headings.append(heading)
            seen_lines.add(line_no)
        chapter_headings = sorted(dedup_headings, key=lambda x: int(x["line"]))

        for i, heading in enumerate(chapter_headings):
            start = int(heading["line"]) + 1
            end = int(chapter_headings[i + 1]["line"]) if i + 1 < len(chapter_headings) else len(lines)
            body_lines = lines[start:end]
            cleaned = []
            last_blank = False

            for line in body_lines:
                trimmed = normalize_text(line)
                if re.match(r"^[=\-_*]{3,}$", trimmed):
                    continue
                if not trimmed:
                    if not last_blank:
                        cleaned.append("")
                        last_blank = True
                    continue
                if re.match(r"^[（(【\[]?\s*第?.{0,20}章完\s*[】\])）)]?$", trimmed):
                    continue
                h = heading_regex.match(line)
                if h and not chapter_regex.search(normalize_text(h.group(2))):
                    title_text = strip_markdown_line(h.group(2))
                    if title_text:
                        cleaned.append(title_text)
                        last_blank = False
                    continue
                plain = strip_markdown_line(line)
                if not plain:
                    continue
                cleaned.append(plain)
                last_blank = False

            body = "\n".join(cleaned).strip()
            if not body:
                continue
            chapters.append(
                {
                    "title": strip_markdown_line(heading["title"]) or f"Chapter {i + 1}",
                    "english": body,
                    "chinese": body if re.search(r"[\u4e00-\u9fff]", body) else "",
                    "targetWords": [],
                }
            )

    if not chapters:
        raise ValueError("Markdown 章节内容为空。")

    return {
        "id": f"md-{uuid.uuid4().hex[:12]}",
        "title": book_title,
        "description": f"Markdown 导入：{file_name}",
        "wordGoal": 3500,
        "chapters": chapters,
    }


def parse_docx_book(content_bytes, file_name):
    try:
        with zipfile.ZipFile(io.BytesIO(content_bytes)) as zf:
            xml_bytes = zf.read("word/document.xml")
    except Exception as exc:
        raise ValueError(f"DOCX 解析失败：{exc}") from exc

    ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    try:
        root = ET.fromstring(xml_bytes)
    except Exception as exc:
        raise ValueError(f"DOCX 内容损坏：{exc}") from exc

    paragraphs = []
    for p in root.findall(".//w:p", ns):
        text_parts = []
        for t in p.findall(".//w:t", ns):
            if t.text:
                text_parts.append(t.text)
        line = normalize_text("".join(text_parts))
        paragraphs.append(line)

    if not any(paragraphs):
        raise ValueError("DOCX 正文为空。")

    chapter_hint = re.compile(
        r"(第\s*(\d+|[一二三四五六七八九十百零两]+)\s*[章节组回课篇册节]|chapter\s*[-#:：]?\s*\d+|\bch\s*[-#:：]?\s*\d+)",
        re.IGNORECASE,
    )
    pseudo_lines = []
    for line in paragraphs:
        if not line:
            pseudo_lines.append("")
            continue
        if chapter_hint.search(line):
            pseudo_lines.append(f"# {line}")
            continue
        pseudo_lines.append(line)

    pseudo_markdown = "\n".join(pseudo_lines)
    parsed = parse_markdown_book(pseudo_markdown, file_name)
    parsed["id"] = f"docx-{uuid.uuid4().hex[:12]}"
    parsed["description"] = f"DOCX 导入：{file_name}"
    return parsed


def extract_chapter_no(text):
    line = normalize_text(text)
    if not line:
        return None

    # 宽松识别：第1章 / 第1组 / chapter 1 / ch1 / 1章 / 1.
    patterns = [
        re.compile(r"第\s*(\d{1,4})\s*[章节组回课篇册节]"),
        re.compile(r"\bchapter\s*[-#:：]?\s*(\d{1,4})\b", re.IGNORECASE),
        re.compile(r"\bch\s*[-#:：]?\s*(\d{1,4})\b", re.IGNORECASE),
        re.compile(r"(^|[\s#：:;；,，\[\(【（])(\d{1,4})(?:\s*[章节组回课篇册节]|[.、:：-])"),
        re.compile(r"^\s*(\d{1,4})\s*$"),
    ]
    for pattern in patterns:
        match = pattern.search(line)
        if not match:
            continue
        number_text = match.group(1) if match.lastindex == 1 else match.group(2)
        try:
            chapter_no = int(number_text)
        except Exception:
            continue
        if chapter_no > 0:
            return chapter_no
    return None


def parse_tasks_text(tasks_text, chapter_count):
    tasks_map = {idx: [] for idx in range(chapter_count)}
    if not tasks_text:
        return tasks_map

    seen = {idx: set() for idx in range(chapter_count)}
    active_chapter_idx = 0 if chapter_count > 0 else None
    def add_task(chapter_idx, word, translation=""):
        if chapter_idx < 0 or chapter_idx >= chapter_count:
            return
        normalized_word = normalize_text(word)
        if not normalized_word:
            return
        normalized_word = re.sub(r"^[^A-Za-z]+|[^A-Za-z'-]+$", "", normalized_word)
        if not normalized_word or not re.match(r"^[A-Za-z][A-Za-z'-]*$", normalized_word):
            return
        lower_word = normalized_word.lower()
        if lower_word in seen[chapter_idx]:
            return
        seen[chapter_idx].add(lower_word)
        tasks_map[chapter_idx].append(
            {
                "word": normalized_word,
                "translation": normalize_text(translation),
            }
        )

    for raw_line in tasks_text.splitlines():
        line = normalize_text(raw_line)
        if not line:
            continue

        # 兼容旧格式：章节序号|word|translation
        parts = [p.strip() for p in re.split(r"[|｜]", line)]
        chapter_no_in_col = extract_chapter_no(parts[0]) if parts else None
        if parts and len(parts) >= 2 and (parts[0].isdigit() or chapter_no_in_col is not None):
            chapter_idx = int(parts[0]) - 1 if parts[0].isdigit() else (chapter_no_in_col - 1)
            word = parts[1]
            translation = parts[2] if len(parts) >= 3 else ""
            add_task(chapter_idx, word, translation)
            active_chapter_idx = chapter_idx if 0 <= chapter_idx < chapter_count else active_chapter_idx
            continue

        # 兼容格式：word|translation（章节由上一个 ### 章节标题决定）
        if len(parts) >= 1 and active_chapter_idx is not None and re.search(r"[|｜]", line):
            word = parts[0]
            translation = parts[1] if len(parts) >= 2 else ""
            add_task(active_chapter_idx, word, translation)
            continue

        chapter_no = extract_chapter_no(line)
        if chapter_no is not None:
            chapter_idx = chapter_no - 1
            active_chapter_idx = chapter_idx if 0 <= chapter_idx < chapter_count else None
            continue

        if line.startswith("#") or line.startswith("[") or line.startswith("【"):
            continue

        if active_chapter_idx is not None and ":" in line and "|" not in line and "：" in line:
            left, right = line.split("：", 1)
            if re.match(r"^[A-Za-z][A-Za-z'-]*$", normalize_text(left)):
                add_task(active_chapter_idx, left, right)
                continue
        if active_chapter_idx is not None and ":" in line and "|" not in line:
            left, right = line.split(":", 1)
            if re.match(r"^[A-Za-z][A-Za-z'-]*$", normalize_text(left)):
                add_task(active_chapter_idx, left, right)
                continue

        # 新格式：逗号/空格分隔单词（可无中文，未写章节默认归第1章）
        if active_chapter_idx is not None:
            tokens = re.split(r"[,，、;；\s]+", line)
            for token in tokens:
                add_task(active_chapter_idx, token, "")

    return tasks_map


def apply_tasks(book, tasks_text):
    task_map = parse_tasks_text(tasks_text, len(book["chapters"]))
    for idx, chapter in enumerate(book["chapters"]):
        if task_map.get(idx):
            chapter["targetWords"] = task_map[idx]
        elif "targetWords" not in chapter:
            chapter["targetWords"] = []
    return book


def save_book(book):
    now = datetime.utcnow().isoformat(timespec="seconds")
    with db_conn() as conn:
        conn.execute(
            """
            INSERT INTO books (id, title, description, word_goal, updated_at, cover_url, category, sort_order)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
              title=excluded.title,
              description=excluded.description,
              word_goal=excluded.word_goal,
              updated_at=excluded.updated_at,
              cover_url=excluded.cover_url,
              category=excluded.category,
              sort_order=excluded.sort_order
            """,
            (
                book["id"],
                book["title"],
                book["description"],
                int(book["wordGoal"]),
                now,
                normalize_text(book.get("coverUrl")),
                normalize_text(book.get("category")),
                int(book.get("sortOrder") or 0),
            ),
        )
        conn.execute("DELETE FROM chapters WHERE book_id = ?", (book["id"],))
        for idx, chapter in enumerate(book["chapters"]):
            conn.execute(
                """
                INSERT INTO chapters (book_id, chapter_index, title, english, chinese, target_words_json)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    book["id"],
                    idx,
                    chapter["title"],
                    chapter["english"],
                    chapter["chinese"],
                    json.dumps(chapter.get("targetWords", []), ensure_ascii=False),
                ),
            )


def load_books():
    with db_conn() as conn:
        book_rows = conn.execute(
            "SELECT * FROM books ORDER BY sort_order ASC, updated_at DESC"
        ).fetchall()
        books = []
        for row in book_rows:
            chapters_rows = conn.execute(
                "SELECT * FROM chapters WHERE book_id = ? ORDER BY chapter_index ASC",
                (row["id"],),
            ).fetchall()
            chapters = []
            for ch in chapters_rows:
                try:
                    target_words = json.loads(ch["target_words_json"] or "[]")
                except Exception:
                    target_words = []
                chapters.append(
                    {
                        "title": ch["title"],
                        "english": ch["english"],
                        "chinese": ch["chinese"],
                        "targetWords": target_words,
                    }
                )
            books.append(
                {
                    "id": row["id"],
                    "title": row["title"],
                    "description": row["description"],
                    "wordGoal": row["word_goal"],
                    "coverUrl": row["cover_url"] or "",
                    "category": row["category"] or "",
                    "sortOrder": int(row["sort_order"] or 0),
                    "chapters": chapters,
                }
            )
        return books


def load_public_books():
    books = load_books()
    for item in books:
        item["ownership"] = "public"
        item["editable"] = False
    return books


def load_user_generated_books(user_id):
    with db_conn() as conn:
        rows = conn.execute(
            """
            SELECT * FROM user_generated_books
            WHERE user_id = ?
            ORDER BY updated_at DESC
            """,
            (user_id,),
        ).fetchall()
        books = []
        for row in rows:
            ch_rows = conn.execute(
                """
                SELECT * FROM user_generated_chapters
                WHERE book_id = ?
                ORDER BY chapter_index ASC
                """,
                (row["id"],),
            ).fetchall()
            chapters = []
            for ch in ch_rows:
                try:
                    target_words = json.loads(ch["target_words_json"] or "[]")
                except Exception:
                    target_words = []
                chapters.append(
                    {
                        "title": ch["title"],
                        "english": ch["english"],
                        "chinese": ch["chinese"],
                        "targetWords": target_words,
                    }
                )
            books.append(
                {
                    "id": row["id"],
                    "title": row["title"],
                    "description": row["description"] or "",
                    "wordGoal": int(row["word_goal"] or 3500),
                    "coverUrl": row["cover_url"] or "",
                    "category": "个人生成",
                    "sortOrder": 999999,
                    "ownership": "personal",
                    "editable": True,
                    "chapters": chapters,
                }
            )
    return books


def load_user_books_mix(user_id):
    return load_public_books() + load_user_generated_books(user_id)


def calc_word_count_for_text(text):
    return len(re.findall(r"[A-Za-z][A-Za-z'\-]*", normalize_text(text)))


def parse_group_items_from_payload(selected_groups):
    items = []
    if not isinstance(selected_groups, list):
        return items
    for idx, group in enumerate(selected_groups, start=1):
        if not isinstance(group, dict):
            continue
        title = normalize_text(group.get("groupName")) or f"第{idx}组"
        english = normalize_text(group.get("articleEnglish") or group.get("article"))
        chinese = normalize_text(group.get("articleChinese"))
        target_words = group.get("targetWords")
        if not isinstance(target_words, list):
            target_words = []
        safe_targets = []
        for entry in target_words:
            if isinstance(entry, dict):
                word = normalize_word(entry.get("word"))
                translation = normalize_text(entry.get("translation"))
            else:
                word = normalize_word(entry)
                translation = ""
            if not word:
                continue
            safe_targets.append({"word": word, "translation": translation})
        if not english:
            continue
        items.append(
            {
                "title": title,
                "english": english,
                "chinese": chinese,
                "targetWords": safe_targets,
            }
        )
    return items


def create_user_generated_book(user_id, payload):
    title = normalize_text(payload.get("title")) or f"词汇查验-{now_shanghai().strftime('%Y%m%d-%H%M')}"
    description = normalize_text(payload.get("description")) or "来自词汇故事生成器"
    source = normalize_text(payload.get("source")) or "story_lab"
    selected_items = parse_group_items_from_payload(payload.get("selectedGroups"))
    if not selected_items:
        raise ValueError("请先勾选至少一篇文章再加入书架。")

    cover_url = normalize_text(payload.get("coverUrl"))
    now = utc_now_iso()
    book_id = f"ugb-{uuid.uuid4().hex[:12]}"
    total_words = sum(calc_word_count_for_text(item["english"]) for item in selected_items)
    word_goal = max(120, total_words)

    with db_conn() as conn:
        conn.execute(
            """
            INSERT INTO user_generated_books (
              id, user_id, title, description, word_goal, cover_url, source, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (book_id, user_id, title, description, word_goal, cover_url, source, now, now),
        )
        for idx, item in enumerate(selected_items):
            conn.execute(
                """
                INSERT INTO user_generated_chapters (
                  book_id, chapter_index, title, english, chinese, target_words_json
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    book_id,
                    idx,
                    item["title"],
                    item["english"],
                    item["chinese"],
                    json.dumps(item["targetWords"], ensure_ascii=False),
                ),
            )
    return {"bookId": book_id, "chapterCount": len(selected_items)}


def ensure_personal_book_owner(book_id, user_id):
    with db_conn() as conn:
        row = conn.execute(
            "SELECT * FROM user_generated_books WHERE id = ? AND user_id = ?",
            (normalize_text(book_id), user_id),
        ).fetchone()
    return dict(row) if row else None


def update_personal_book(book_id, user_id, payload):
    row = ensure_personal_book_owner(book_id, user_id)
    if not row:
        raise ValueError("book not found")
    new_title = normalize_text(payload.get("title")) if "title" in payload else normalize_text(row["title"])
    new_cover = normalize_text(payload.get("coverUrl")) if "coverUrl" in payload else normalize_text(row["cover_url"])
    if not new_title:
        new_title = normalize_text(row["title"]) or "未命名书籍"
    now = utc_now_iso()
    with db_conn() as conn:
        conn.execute(
            """
            UPDATE user_generated_books
            SET title = ?, cover_url = ?, updated_at = ?
            WHERE id = ? AND user_id = ?
            """,
            (new_title, new_cover, now, book_id, user_id),
        )
    return {"id": book_id, "title": new_title, "coverUrl": new_cover}


def delete_personal_book(book_id, user_id):
    with db_conn() as conn:
        row = conn.execute(
            "SELECT id FROM user_generated_books WHERE id = ? AND user_id = ?",
            (normalize_text(book_id), user_id),
        ).fetchone()
        if not row:
            return False
        conn.execute("DELETE FROM user_generated_chapters WHERE book_id = ?", (book_id,))
        conn.execute("DELETE FROM user_generated_books WHERE id = ? AND user_id = ?", (book_id, user_id))
    return True


def batch_delete_personal_books(book_ids, user_id):
    cleaned = [normalize_text(item) for item in (book_ids or []) if normalize_text(item)]
    if not cleaned:
        return {"deleted": 0}
    deleted = 0
    for book_id in cleaned:
        if delete_personal_book(book_id, user_id):
            deleted += 1
    return {"deleted": deleted}


def load_user_reader_state(user_id):
    with db_conn() as conn:
        row = conn.execute("SELECT * FROM user_reader_state WHERE user_id = ?", (user_id,)).fetchone()
    if not row:
        return {
            "profile": {},
            "progressByBook": {},
            "settings": {},
            "commentsByAnchor": {},
            "updatedAt": "",
        }
    try:
        profile = json.loads(row["profile_json"] or "{}")
    except Exception:
        profile = {}
    try:
        progress = json.loads(row["progress_json"] or "{}")
    except Exception:
        progress = {}
    try:
        settings = json.loads(row["settings_json"] or "{}")
    except Exception:
        settings = {}
    try:
        comments = json.loads(row["comments_json"] or "{}")
    except Exception:
        comments = {}
    return {
        "profile": profile if isinstance(profile, dict) else {},
        "progressByBook": progress if isinstance(progress, dict) else {},
        "settings": settings if isinstance(settings, dict) else {},
        "commentsByAnchor": comments if isinstance(comments, dict) else {},
        "updatedAt": normalize_text(row["updated_at"]),
    }


def upsert_user_reader_state(user_id, state_payload):
    profile = state_payload.get("profile")
    progress = state_payload.get("progressByBook")
    settings = state_payload.get("settings")
    comments = state_payload.get("commentsByAnchor")
    now = utc_now_iso()
    with db_conn() as conn:
        conn.execute(
            """
            INSERT INTO user_reader_state (
              user_id, profile_json, progress_json, settings_json, comments_json, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
              profile_json = excluded.profile_json,
              progress_json = excluded.progress_json,
              settings_json = excluded.settings_json,
              comments_json = excluded.comments_json,
              updated_at = excluded.updated_at
            """,
            (
                user_id,
                json.dumps(profile if isinstance(profile, dict) else {}, ensure_ascii=False),
                json.dumps(progress if isinstance(progress, dict) else {}, ensure_ascii=False),
                json.dumps(settings if isinstance(settings, dict) else {}, ensure_ascii=False),
                json.dumps(comments if isinstance(comments, dict) else {}, ensure_ascii=False),
                now,
            ),
        )
    return load_user_reader_state(user_id)


def import_user_reader_state(user_id, state_payload, overwrite=False):
    current = load_user_reader_state(user_id)
    has_existing = bool(current.get("profile") or current.get("progressByBook") or current.get("settings") or current.get("commentsByAnchor"))
    if has_existing and not overwrite:
        return {"imported": False, "reason": "existing_state"}
    upsert_user_reader_state(user_id, state_payload)
    return {"imported": True}


def save_reading_history_event(user_id, payload):
    book_id = normalize_text(payload.get("bookId"))
    if not book_id:
        raise ValueError("bookId is required")
    chapter_index = _to_int(payload.get("chapterIndex"), default=0, low=0, high=100000)
    page_index = _to_int(payload.get("pageIndex"), default=0, low=0, high=100000)
    book_title = normalize_text(payload.get("bookTitle"))
    chapter_title = normalize_text(payload.get("chapterTitle"))
    now = utc_now_iso()

    with db_conn() as conn:
        latest = conn.execute(
            """
            SELECT * FROM user_reading_history
            WHERE user_id = ? AND book_id = ? AND chapter_index = ? AND page_index = ?
            ORDER BY viewed_at DESC
            LIMIT 1
            """,
            (user_id, book_id, chapter_index, page_index),
        ).fetchone()
        if latest:
            prev_time = normalize_text(latest["viewed_at"])
            try:
                prev_dt = datetime.fromisoformat(prev_time)
                now_dt = datetime.fromisoformat(now)
                if (now_dt - prev_dt).total_seconds() < 30:
                    conn.execute(
                        """
                        UPDATE user_reading_history
                        SET viewed_at = ?, book_title_snapshot = ?, chapter_title_snapshot = ?
                        WHERE id = ?
                        """,
                        (now, book_title, chapter_title, latest["id"]),
                    )
                    return latest["id"]
            except Exception:
                pass
        history_id = f"hist-{uuid.uuid4().hex[:12]}"
        conn.execute(
            """
            INSERT INTO user_reading_history (
              id, user_id, book_id, chapter_index, page_index,
              book_title_snapshot, chapter_title_snapshot, viewed_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (history_id, user_id, book_id, chapter_index, page_index, book_title, chapter_title, now),
        )
        return history_id


def list_user_reading_history(user_id, limit=200):
    safe_limit = _to_int(limit, default=100, low=1, high=500)
    with db_conn() as conn:
        rows = conn.execute(
            """
            SELECT * FROM user_reading_history
            WHERE user_id = ?
            ORDER BY viewed_at DESC
            LIMIT ?
            """,
            (user_id, safe_limit),
        ).fetchall()
    items = []
    for row in rows:
        items.append(
            {
                "id": row["id"],
                "bookId": row["book_id"],
                "chapterIndex": int(row["chapter_index"] or 0),
                "pageIndex": int(row["page_index"] or 0),
                "bookTitle": row["book_title_snapshot"] or "",
                "chapterTitle": row["chapter_title_snapshot"] or "",
                "viewedAt": row["viewed_at"],
            }
        )
    return items


def _to_int(value, default=0, low=None, high=None):
    try:
        parsed = int(value)
    except Exception:
        parsed = int(default)
    if low is not None:
        parsed = max(int(low), parsed)
    if high is not None:
        parsed = min(int(high), parsed)
    return parsed


def _to_bool(value, default=False):
    if isinstance(value, bool):
        return value
    text = normalize_text(value).lower()
    if not text:
        return bool(default)
    if text in {"1", "true", "yes", "y", "on"}:
        return True
    if text in {"0", "false", "no", "n", "off"}:
        return False
    return bool(default)


def validate_moonshot_api_key(raw_key):
    key = normalize_text(raw_key)
    if not key:
        return "缺少 API Key"
    try:
        key.encode("ascii")
    except Exception:
        return "包含非英文字符（请只粘贴 sk- 开头的 key）"
    if any(ch.isspace() for ch in key):
        return "包含空格或换行"
    if len(key) < 16:
        return "长度过短"
    if not key.startswith("sk-"):
        return "格式异常（通常应以 sk- 开头）"
    return ""


def build_llm_disabled_orchestrator():
    try:
        timeout_seconds = float(os.getenv("MOONSHOT_TIMEOUT_SECONDS", "240"))
    except Exception:
        timeout_seconds = 240.0
    try:
        top_p = float(os.getenv("MOONSHOT_TOP_P", "0.95"))
    except Exception:
        top_p = 0.95
    thinking_mode = os.getenv("MOONSHOT_THINKING_MODE", "thinking")
    try:
        max_retries = int(os.getenv("MOONSHOT_MAX_RETRIES", "4"))
    except Exception:
        max_retries = 4
    try:
        base_backoff_seconds = float(os.getenv("MOONSHOT_BASE_BACKOFF_SECONDS", "1.2"))
    except Exception:
        base_backoff_seconds = 1.2
    try:
        min_interval_seconds = float(os.getenv("MOONSHOT_MIN_INTERVAL_SECONDS", "0.45"))
    except Exception:
        min_interval_seconds = 0.45
    client = MoonshotClient(
        api_key="",
        base_url=os.getenv("MOONSHOT_BASE_URL", "https://api.moonshot.cn/v1"),
        model=os.getenv("MOONSHOT_MODEL", "kimi-k2-0905-preview"),
        timeout_seconds=timeout_seconds,
        top_p=top_p,
        thinking_mode=thinking_mode,
        max_retries=max_retries,
        base_backoff_seconds=base_backoff_seconds,
        min_interval_seconds=min_interval_seconds,
    )
    return NovelAgentOrchestrator(llm_client=client)


def _is_transient_model_text(text):
    normalized = normalize_text(text).lower()
    if not normalized:
        return False
    keywords = (
        "429",
        "503",
        "502",
        "504",
        "timeout",
        "timed out",
        "too many requests",
        "rate limit",
        "temporarily unavailable",
        "connection reset",
        "connection aborted",
    )
    return any(word in normalized for word in keywords)


def _result_has_transient_warning(result):
    if not isinstance(result, dict):
        return False
    warnings = result.get("warnings")
    if isinstance(warnings, list):
        for item in warnings:
            if _is_transient_model_text(item):
                return True
            text = normalize_text(item)
            if "限流" in text or "超时" in text or "降级" in text:
                return True
    agents = result.get("agents")
    if isinstance(agents, dict):
        for agent_payload in agents.values():
            if not isinstance(agent_payload, dict):
                continue
            if not bool(agent_payload.get("fallback")):
                continue
            if _is_transient_model_text(agent_payload.get("error")):
                return True
    return False


def _chapter_result_needs_retry(result, strict_quality_gate=True):
    if not isinstance(result, dict):
        return False
    if not _result_has_transient_warning(result):
        return False
    if not strict_quality_gate:
        return True
    quality = result.get("quality") if isinstance(result.get("quality"), dict) else {}
    passed = bool(quality.get("passed"))
    score = _to_int(quality.get("score"), default=0, low=0, high=100)
    effective_chars = _to_int(quality.get("effective_chars"), default=0, low=0)
    constraints = quality.get("length_constraints") if isinstance(quality.get("length_constraints"), dict) else {}
    min_required = _to_int(constraints.get("min_required"), default=0, low=0)
    if not passed:
        return True
    if min_required and effective_chars < min_required:
        return True
    if score < 78:
        return True
    return False


def normalize_tags(value):
    if isinstance(value, list):
        raw_items = value
    else:
        raw_items = re.split(r"[,，;；、\s]+", normalize_text(value))
    clean = []
    seen = set()
    for item in raw_items:
        tag = normalize_text(item)
        if not tag:
            continue
        lowered = tag.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        clean.append(tag)
    return ",".join(clean[:20])


def list_knowledge(limit=100, query=""):
    safe_limit = _to_int(limit, default=100, low=1, high=400)
    normalized_query = normalize_text(query)
    with db_conn() as conn:
        if normalized_query:
            like = f"%{normalized_query}%"
            rows = conn.execute(
                """
                SELECT * FROM novel_knowledge
                WHERE title LIKE ? OR content LIKE ? OR tags LIKE ?
                ORDER BY updated_at DESC
                LIMIT ?
                """,
                (like, like, like, safe_limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM novel_knowledge ORDER BY updated_at DESC LIMIT ?",
                (safe_limit,),
            ).fetchall()
    return [dict(row) for row in rows]


def get_knowledge_by_ids(knowledge_ids):
    clean_ids = [normalize_text(item) for item in (knowledge_ids or []) if normalize_text(item)]
    if not clean_ids:
        return []
    placeholders = ",".join(["?"] * len(clean_ids))
    with db_conn() as conn:
        rows = conn.execute(
            f"SELECT * FROM novel_knowledge WHERE id IN ({placeholders})",
            tuple(clean_ids),
        ).fetchall()
    rows_by_id = {row["id"]: dict(row) for row in rows}
    return [rows_by_id[item_id] for item_id in clean_ids if item_id in rows_by_id]


def create_knowledge(title, content, tags="", source="manual", auto_chunk=True):
    clean_title = normalize_text(title) or "未命名知识"
    clean_content = normalize_text(content)
    if not clean_content:
        raise ValueError("content is required")

    chunks = chunk_text(clean_content) if auto_chunk else [clean_content]
    now = now_iso()
    created_ids = []
    with db_conn() as conn:
        for idx, chunk in enumerate(chunks, start=1):
            item_id = f"know-{uuid.uuid4().hex[:12]}"
            chunk_title = clean_title if len(chunks) == 1 else f"{clean_title}（分片{idx}）"
            conn.execute(
                """
                INSERT INTO novel_knowledge (id, title, content, tags, source, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    item_id,
                    chunk_title,
                    chunk,
                    normalize_tags(tags),
                    normalize_text(source),
                    now,
                    now,
                ),
            )
            created_ids.append(item_id)
    return created_ids


def delete_knowledge(knowledge_id):
    target = normalize_text(knowledge_id)
    if not target:
        return False
    with db_conn() as conn:
        row = conn.execute("SELECT id FROM novel_knowledge WHERE id = ?", (target,)).fetchone()
        if not row:
            return False
        conn.execute("DELETE FROM novel_knowledge WHERE id = ?", (target,))
        return True


def parse_student_profile_payload(value):
    if isinstance(value, dict):
        return normalize_student_profile(value)
    if isinstance(value, str):
        text = normalize_text(value)
        if not text:
            return normalize_student_profile({})
        try:
            parsed = json.loads(text)
            if isinstance(parsed, dict):
                return normalize_student_profile(parsed)
        except Exception:
            return normalize_student_profile({"notes": text})
    return normalize_student_profile({})


def get_project_state(project_name):
    name = normalize_text(project_name)
    if not name:
        return {
            "state": {},
            "studentProfile": normalize_student_profile({}),
            "routingStrategy": {},
            "updatedAt": "",
        }
    with db_conn() as conn:
        row = conn.execute(
            "SELECT * FROM novel_project_states WHERE project_name = ?",
            (name,),
        ).fetchone()
    if not row:
        return {
            "state": {},
            "studentProfile": normalize_student_profile({}),
            "routingStrategy": {},
            "updatedAt": "",
        }

    try:
        state = json.loads(row["state_json"] or "{}")
    except Exception:
        state = {}
    try:
        student_profile = json.loads(row["student_profile_json"] or "{}")
    except Exception:
        student_profile = {}
    try:
        routing = json.loads(row["routing_json"] or "{}")
    except Exception:
        routing = {}
    return {
        "state": state if isinstance(state, dict) else {},
        "studentProfile": normalize_student_profile(student_profile),
        "routingStrategy": routing if isinstance(routing, dict) else {},
        "updatedAt": normalize_text(row["updated_at"]),
    }


def upsert_project_state(project_name, state, student_profile, routing):
    name = normalize_text(project_name)
    if not name:
        return
    with db_conn() as conn:
        conn.execute(
            """
            INSERT INTO novel_project_states (project_name, state_json, student_profile_json, routing_json, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(project_name) DO UPDATE SET
              state_json=excluded.state_json,
              student_profile_json=excluded.student_profile_json,
              routing_json=excluded.routing_json,
              updated_at=excluded.updated_at
            """,
            (
                name,
                json.dumps(state if isinstance(state, dict) else {}, ensure_ascii=False),
                json.dumps(student_profile if isinstance(student_profile, dict) else {}, ensure_ascii=False),
                json.dumps(routing if isinstance(routing, dict) else {}, ensure_ascii=False),
                now_iso(),
            ),
        )


def list_project_chapter_context(project_name, limit=40):
    name = normalize_text(project_name)
    if not name:
        return []
    safe_limit = _to_int(limit, default=40, low=1, high=240)
    with db_conn() as conn:
        rows = conn.execute(
            """
            SELECT chapter_index, chapter_title, chapter_summary, hero_stage, ai_capability_level, energy_after, created_at
            FROM novel_chapter_outputs
            WHERE project_name = ?
            ORDER BY chapter_index DESC, created_at DESC
            LIMIT ?
            """,
            (name, safe_limit),
        ).fetchall()
    ordered = []
    for row in reversed(rows):
        ordered.append(
            {
                "chapter_index": _to_int(row["chapter_index"], default=0, low=0),
                "chapter_title": normalize_text(row["chapter_title"]),
                "chapter_summary": normalize_text(row["chapter_summary"]),
                "hero_stage": _to_int(row["hero_stage"], default=1, low=1, high=10),
                "ai_capability_level": _to_int(row["ai_capability_level"], default=1, low=1, high=10),
                "energy_after": _to_int(row["energy_after"], default=0, low=0),
                "created_at": normalize_text(row["created_at"]),
            }
        )
    return ordered


def persist_project_memory_snapshot(project_name, chapter_index, merged_state, student_profile, routing_strategy):
    name = normalize_text(project_name)
    if not name:
        return ""
    content = json.dumps(
        {
            "project": name,
            "chapter": _to_int(chapter_index, default=1, low=1),
            "studentProfile": student_profile if isinstance(student_profile, dict) else {},
            "routingStrategy": routing_strategy if isinstance(routing_strategy, dict) else {},
            "mergedState": merged_state if isinstance(merged_state, dict) else {},
        },
        ensure_ascii=False,
        indent=2,
    )
    entry_id = f"know-{uuid.uuid4().hex[:12]}"
    now = now_iso()
    with db_conn() as conn:
        conn.execute(
            """
            INSERT INTO novel_knowledge (id, title, content, tags, source, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                entry_id,
                f"{name} 章节{chapter_index} 记忆快照",
                content,
                normalize_tags(["project_memory", name, f"chapter_{chapter_index}", "人物关系", "阶段进展"]),
                "project_memory",
                now,
                now,
            ),
        )
    return entry_id


def latest_project_energy(project_name):
    name = normalize_text(project_name)
    if not name:
        return 0
    with db_conn() as conn:
        row = conn.execute(
            """
            SELECT energy_after FROM novel_chapter_outputs
            WHERE project_name = ?
            ORDER BY chapter_index DESC, created_at DESC
            LIMIT 1
            """,
            (name,),
        ).fetchone()
    if not row:
        return 0
    return _to_int(row["energy_after"], default=0, low=0)


def save_novel_chapter_result(project_name, chapter_index, total_chapters, result):
    chapter = result.get("chapter") or {}
    quality = result.get("quality") or {}
    knowledge_used = result.get("knowledgeUsed") or []
    knowledge_ids = [item.get("id") for item in knowledge_used if item.get("id")]
    entry_id = f"chapter-{uuid.uuid4().hex[:12]}"

    with db_conn() as conn:
        conn.execute(
            """
            INSERT INTO novel_chapter_outputs (
              id, project_name, chapter_index, total_chapters, chapter_title, chapter_summary,
              chapter_text, hero_stage, ai_capability_level, energy_gain, energy_after,
              quality_score, quality_passed, knowledge_ids_json, agent_trace_json, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                entry_id,
                normalize_text(project_name),
                _to_int(chapter_index, default=1, low=1),
                _to_int(total_chapters, default=20, low=1),
                normalize_text(chapter.get("chapter_title")),
                normalize_text(chapter.get("chapter_summary")),
                normalize_text(chapter.get("chapter_text")),
                _to_int(chapter.get("hero_stage"), default=1, low=1, high=10),
                _to_int(chapter.get("ai_capability_level"), default=1, low=1, high=10),
                _to_int(chapter.get("energy_gain"), default=0, low=0),
                _to_int(chapter.get("energy_after"), default=0, low=0),
                _to_int(quality.get("score"), default=0, low=0, high=100),
                1 if bool(quality.get("passed")) else 0,
                json.dumps(knowledge_ids, ensure_ascii=False),
                json.dumps(result.get("agents") or {}, ensure_ascii=False),
                now_iso(),
            ),
        )
    return entry_id


def list_project_chapters(project_name, limit=20):
    name = normalize_text(project_name)
    safe_limit = _to_int(limit, default=20, low=1, high=200)
    with db_conn() as conn:
        if name:
            rows = conn.execute(
                """
                SELECT * FROM novel_chapter_outputs
                WHERE project_name = ?
                ORDER BY chapter_index DESC, created_at DESC
                LIMIT ?
                """,
                (name, safe_limit),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT * FROM novel_chapter_outputs
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (safe_limit,),
            ).fetchall()
    payload = []
    for row in rows:
        item = dict(row)
        try:
            item["knowledge_ids"] = json.loads(item.get("knowledge_ids_json") or "[]")
        except Exception:
            item["knowledge_ids"] = []
        item.pop("agent_trace_json", None)
        item.pop("knowledge_ids_json", None)
        payload.append(item)
    return payload


ORCHESTRATOR = build_orchestrator_from_env()


def get_request_orchestrator(payload=None):
    data = payload if isinstance(payload, dict) else {}
    require_llm = _to_bool(data.get("requireLLM"), False)
    api_key = normalize_text(request.headers.get("X-Moonshot-Api-Key", "")) or normalize_text(data.get("moonshotApiKey"))
    if not api_key:
        env_key = os.getenv("MOONSHOT_API_KEY", "")
        key_error = validate_moonshot_api_key(env_key)
        if key_error:
            if require_llm:
                raise ValueError(
                    f"Kimi API Key 无效：{key_error}。请在页面填入正确 key，或修正服务端 MOONSHOT_API_KEY。"
                )
            return build_llm_disabled_orchestrator()
        return ORCHESTRATOR

    key_error = validate_moonshot_api_key(api_key)
    if key_error:
        raise ValueError(f"页面填写的 Kimi API Key 无效：{key_error}")

    model = normalize_text(request.headers.get("X-Moonshot-Model", "")) or normalize_text(data.get("moonshotModel"))
    base_url = normalize_text(request.headers.get("X-Moonshot-Base-Url", "")) or normalize_text(data.get("moonshotBaseUrl"))
    thinking_mode = normalize_text(request.headers.get("X-Moonshot-Thinking-Mode", "")) or normalize_text(data.get("thinkingMode")) or "thinking"
    top_p_raw = normalize_text(request.headers.get("X-Moonshot-Top-P", "")) or normalize_text(data.get("moonshotTopP"))
    timeout_raw = normalize_text(request.headers.get("X-Moonshot-Timeout", "")) or normalize_text(data.get("moonshotTimeoutSeconds"))
    try:
        timeout_seconds = float(timeout_raw) if timeout_raw else float(os.getenv("MOONSHOT_TIMEOUT_SECONDS", "120"))
    except Exception:
        timeout_seconds = float(os.getenv("MOONSHOT_TIMEOUT_SECONDS", "120"))
    try:
        top_p = float(top_p_raw) if top_p_raw else float(os.getenv("MOONSHOT_TOP_P", "0.95"))
    except Exception:
        top_p = float(os.getenv("MOONSHOT_TOP_P", "0.95"))

    client = MoonshotClient(
        api_key=api_key,
        base_url=base_url or os.getenv("MOONSHOT_BASE_URL", "https://api.moonshot.cn/v1"),
        model=model or os.getenv("MOONSHOT_MODEL", "kimi-k2-0905-preview"),
        timeout_seconds=timeout_seconds,
        top_p=top_p,
        thinking_mode=thinking_mode,
        max_retries=int(os.getenv("MOONSHOT_MAX_RETRIES", "0")),
        base_backoff_seconds=float(os.getenv("MOONSHOT_BASE_BACKOFF_SECONDS", "1.2")),
        min_interval_seconds=float(os.getenv("MOONSHOT_MIN_INTERVAL_SECONDS", "0.45")),
    )
    return NovelAgentOrchestrator(llm_client=client)


def resolve_knowledge_for_generation(payload):
    manual_ids = payload.get("knowledgeIds")
    if isinstance(manual_ids, list) and manual_ids:
        return get_knowledge_by_ids(manual_ids)

    query = normalize_text(payload.get("knowledgeQuery"))
    if not query:
        query = normalize_text(payload.get("premise"))
    project_name = normalize_text(payload.get("projectName"))
    if project_name:
        query = f"{query} {project_name} 人物关系 阶段推进 连续性".strip()
    all_rows = list_knowledge(limit=240, query="")
    top_k = _to_int(payload.get("knowledgeTopK"), default=6, low=1, high=16)
    return select_knowledge(all_rows, query=query, top_k=top_k)


def auth_user_payload(user):
    if not user:
        return {"authenticated": False, "user": None}
    return {
        "authenticated": True,
        "user": {
            "id": user["id"],
            "phoneMasked": mask_phone_e164(user.get("phone_e164")),
        },
    }


def _normalize_transcription_row(row):
    if not row:
        return None
    return {
        "id": row["id"],
        "fileName": row["file_name"],
        "sourcePath": row["source_path"],
        "language": row["language"],
        "status": row["status"],
        "progress": float(row["progress"] or 0),
        "errorMessage": row["error_message"] or "",
        "providerNote": row["provider_note"] or "",
        "durationSec": float(row["duration_sec"] or 0),
        "segmentCount": int(row["segment_count"] or 0),
        "lowConfCount": int(row["low_conf_count"] or 0),
        "createdAt": row["created_at"],
        "startedAt": row["started_at"] or "",
        "finishedAt": row["finished_at"] or "",
        "updatedAt": row["updated_at"],
        "outputReady": bool(
            normalize_text(row["output_md_path"])
            and normalize_text(row["output_txt_path"])
            and normalize_text(row["output_srt_path"])
        ),
    }


def _load_transcription_job(job_id):
    with db_conn() as conn:
        row = conn.execute("SELECT * FROM transcription_jobs WHERE id = ?", (job_id,)).fetchone()
    return row


def _upsert_transcription_terms(term_text):
    pairs = parse_term_text(term_text)
    if not pairs:
        return []
    now = utc_now_iso()
    with db_conn() as conn:
        for source, replacement in pairs:
            conn.execute(
                """
                INSERT INTO transcription_terms (source_term, replacement_term, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(source_term) DO UPDATE SET
                  replacement_term = excluded.replacement_term,
                  updated_at = excluded.updated_at
                """,
                (source, replacement, now),
            )
    return pairs


def _remove_transcription_files(job_row):
    if not job_row:
        return
    candidates = [
        normalize_text(job_row["source_path"]),
        normalize_text(job_row["output_md_path"]),
        normalize_text(job_row["output_txt_path"]),
        normalize_text(job_row["output_srt_path"]),
    ]
    for raw_path in candidates:
        if not raw_path:
            continue
        try:
            path = Path(raw_path)
            if path.exists() and path.is_file():
                path.unlink()
        except Exception:
            pass
    output_md = normalize_text(job_row["output_md_path"])
    if output_md:
        try:
            parent = Path(output_md).parent
            if parent.exists() and parent.is_dir() and not any(parent.iterdir()):
                parent.rmdir()
        except Exception:
            pass


init_db()
ensure_book_columns()
init_novel_tables()
init_transcription_tables()

TRANSCRIPTION_WORKER = TranscriptionWorker(
    db_conn_factory=db_conn,
    output_dir=TRANSCRIBE_OUTPUT_DIR,
    provider_mode=TRANSCRIBE_PROVIDER,
)
TRANSCRIPTION_WORKER.recover_interrupted_jobs()
if ENABLE_TRANSCRIPTION_WORKER:
    TRANSCRIPTION_WORKER.start()


@app.get("/api/health")
def health():
    return jsonify({"ok": True})


@app.post("/api/auth/otp/send")
def api_auth_otp_send():
    payload = request.get_json(silent=True) or {}
    phone_e164 = normalize_phone_cn(payload.get("phone"))
    if not phone_e164:
        return jsonify({"ok": False, "error": "手机号格式错误，仅支持中国大陆手机号。"}), 400

    now = utc_now_iso()
    with db_conn() as conn:
        latest = conn.execute(
            """
            SELECT created_at FROM auth_otp_codes
            WHERE phone_e164 = ?
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (phone_e164,),
        ).fetchone()
        if latest:
            try:
                created_dt = datetime.fromisoformat(normalize_text(latest["created_at"]))
                now_dt = datetime.fromisoformat(now)
                if (now_dt - created_dt).total_seconds() < OTP_COOLDOWN_SECONDS:
                    return jsonify(
                        {
                            "ok": False,
                            "error": f"请求过于频繁，请 {OTP_COOLDOWN_SECONDS} 秒后重试。",
                            "cooldownSeconds": OTP_COOLDOWN_SECONDS,
                        }
                    ), 429
            except Exception:
                pass

    code = f"{secrets.randbelow(1_000_000):06d}"
    code_hash = hash_auth_value(f"otp:{phone_e164}:{code}")
    expires_at = (datetime.utcnow() + timedelta(seconds=max(60, OTP_EXPIRE_SECONDS))).isoformat(timespec="seconds")
    try:
        send_sms_code_via_aliyun(phone_e164, code)
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400

    with db_conn() as conn:
        conn.execute(
            """
            INSERT INTO auth_otp_codes (
              id, phone_e164, code_hash, expires_at, attempt_count, used_at, client_ip, created_at
            ) VALUES (?, ?, ?, ?, 0, '', ?, ?)
            """,
            (
                f"otp-{uuid.uuid4().hex[:12]}",
                phone_e164,
                code_hash,
                expires_at,
                current_request_ip(),
                now,
            ),
        )
    return jsonify({"ok": True, "cooldownSeconds": OTP_COOLDOWN_SECONDS})


@app.post("/api/auth/otp/verify")
def api_auth_otp_verify():
    payload = request.get_json(silent=True) or {}
    phone_e164 = normalize_phone_cn(payload.get("phone"))
    code = normalize_text(payload.get("code"))
    if not phone_e164 or not re.match(r"^\d{6}$", code):
        return jsonify({"ok": False, "error": "手机号或验证码格式错误。"}), 400

    now = utc_now_iso()
    with db_conn() as conn:
        row = conn.execute(
            """
            SELECT * FROM auth_otp_codes
            WHERE phone_e164 = ? AND used_at = ''
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (phone_e164,),
        ).fetchone()
        if not row:
            return jsonify({"ok": False, "error": "请先获取验证码。"}), 400

        if int(row["attempt_count"] or 0) >= OTP_MAX_ATTEMPTS:
            return jsonify({"ok": False, "error": "验证码尝试次数过多，请重新获取。"}), 429

        if normalize_text(row["expires_at"]) <= now:
            return jsonify({"ok": False, "error": "验证码已过期，请重新获取。"}), 400

        code_hash = hash_auth_value(f"otp:{phone_e164}:{code}")
        if code_hash != normalize_text(row["code_hash"]):
            conn.execute(
                "UPDATE auth_otp_codes SET attempt_count = attempt_count + 1 WHERE id = ?",
                (row["id"],),
            )
            return jsonify({"ok": False, "error": "验证码错误。"}), 400

        conn.execute("UPDATE auth_otp_codes SET used_at = ? WHERE id = ?", (now, row["id"]))

    user = create_or_get_user(phone_e164)
    token, expires_at = create_user_session(user["id"])
    response = make_response(
        jsonify(
            {
                "ok": True,
                **auth_user_payload(user),
                "expiresAt": expires_at,
            }
        )
    )
    response.set_cookie(
        SESSION_COOKIE_NAME,
        token,
        httponly=True,
        samesite=COOKIE_SAMESITE,
        secure=COOKIE_SECURE,
        path="/",
        max_age=max(1, SESSION_DAYS) * 24 * 3600,
    )
    return response


@app.get("/api/auth/me")
def api_auth_me():
    user = get_session_user_from_request()
    return jsonify({"ok": True, **auth_user_payload(user)})


@app.post("/api/auth/logout")
def api_auth_logout():
    revoke_current_session()
    response = make_response(jsonify({"ok": True}))
    response.set_cookie(
        SESSION_COOKIE_NAME,
        "",
        max_age=0,
        expires=0,
        path="/",
        samesite=COOKIE_SAMESITE,
        secure=COOKIE_SECURE,
    )
    return response


@app.get("/api/user/quota")
def api_user_quota():
    user, err = require_login_user()
    if err:
        return err
    month_key = current_month_key()
    used = count_monthly_generation(user["id"], month_key)
    remaining = max(0, MONTHLY_GENERATION_LIMIT - used)
    return jsonify(
        {
            "ok": True,
            "monthKey": month_key,
            "limit": MONTHLY_GENERATION_LIMIT,
            "used": used,
            "remaining": remaining,
        }
    )


@app.get("/api/public/books")
def api_public_books():
    return jsonify({"books": load_public_books()})


@app.get("/api/user/books")
def api_user_books():
    user, err = require_login_user()
    if err:
        return err
    return jsonify({"ok": True, "books": load_user_books_mix(user["id"])})


@app.post("/api/user/generated-books")
def api_user_generated_books():
    user, err = require_login_user()
    if err:
        return err
    payload = request.get_json(silent=True) or {}
    try:
        created = create_user_generated_book(user["id"], payload)
        return jsonify({"ok": True, **created})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400


@app.patch("/api/user/books/<book_id>")
def api_user_book_patch(book_id):
    user, err = require_login_user()
    if err:
        return err
    payload = request.get_json(silent=True) or {}
    try:
        updated = update_personal_book(book_id, user["id"], payload)
        return jsonify({"ok": True, "book": updated})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 404


@app.post("/api/user/books/<book_id>/cover/upload")
def api_user_book_cover_upload(book_id):
    user, err = require_login_user()
    if err:
        return err
    row = ensure_personal_book_owner(book_id, user["id"])
    if not row:
        return jsonify({"ok": False, "error": "book not found"}), 404
    file = request.files.get("file")
    if not file:
        return jsonify({"ok": False, "error": "missing file"}), 400
    filename = normalize_text(file.filename)
    ext = Path(filename).suffix.lower()
    if ext not in ALLOWED_COVER_EXTS:
        return jsonify({"ok": False, "error": "仅支持 jpg/jpeg/png/webp"}), 400
    data = file.read()
    if len(data) > MAX_COVER_UPLOAD_BYTES:
        return jsonify({"ok": False, "error": "封面文件过大"}), 400
    user_dir = UPLOAD_DIR / normalize_text(user["id"])
    user_dir.mkdir(parents=True, exist_ok=True)
    safe_name = f"cover-{uuid.uuid4().hex[:10]}{ext}"
    target = user_dir / safe_name
    target.write_bytes(data)
    rel_path = target.relative_to(UPLOAD_DIR).as_posix()
    cover_url = f"/user-covers/{quote(rel_path, safe='/')}"
    updated = update_personal_book(book_id, user["id"], {"coverUrl": cover_url})
    return jsonify({"ok": True, "coverUrl": cover_url, "book": updated})


@app.delete("/api/user/books/<book_id>")
def api_user_book_delete(book_id):
    user, err = require_login_user()
    if err:
        return err
    ok = delete_personal_book(book_id, user["id"])
    if not ok:
        return jsonify({"ok": False, "error": "book not found"}), 404
    return jsonify({"ok": True})


@app.post("/api/user/books/batch-delete")
def api_user_books_batch_delete():
    user, err = require_login_user()
    if err:
        return err
    payload = request.get_json(silent=True) or {}
    result = batch_delete_personal_books(payload.get("bookIds"), user["id"])
    return jsonify({"ok": True, **result})


@app.get("/api/user/state")
def api_user_state_get():
    user, err = require_login_user()
    if err:
        return err
    state = load_user_reader_state(user["id"])
    return jsonify({"ok": True, "state": state})


@app.put("/api/user/state")
def api_user_state_put():
    user, err = require_login_user()
    if err:
        return err
    payload = request.get_json(silent=True) or {}
    state = upsert_user_reader_state(user["id"], payload)
    return jsonify({"ok": True, "state": state})


@app.post("/api/user/state/import")
def api_user_state_import():
    user, err = require_login_user()
    if err:
        return err
    payload = request.get_json(silent=True) or {}
    overwrite = bool(payload.get("overwrite", False))
    result = import_user_reader_state(user["id"], payload, overwrite=overwrite)
    return jsonify({"ok": True, **result})


@app.post("/api/user/reading-history")
def api_user_reading_history_post():
    user, err = require_login_user()
    if err:
        return err
    payload = request.get_json(silent=True) or {}
    try:
        history_id = save_reading_history_event(user["id"], payload)
        return jsonify({"ok": True, "id": history_id})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400


@app.get("/api/user/reading-history")
def api_user_reading_history_get():
    user, err = require_login_user()
    if err:
        return err
    limit = request.args.get("limit", "200")
    items = list_user_reading_history(user["id"], limit=limit)
    return jsonify({"ok": True, "items": items})


@app.get("/api/public/dict")
def api_public_dict():
    word = normalize_text(request.args.get("word", "")).lower()
    context = normalize_text(request.args.get("context", ""))
    prev_word = normalize_text(request.args.get("prev", ""))
    next_word = normalize_text(request.args.get("next", ""))

    if not word:
        return jsonify({"ok": False, "error": "missing word"}), 400

    result = lookup_dictionary(
        word=word,
        context=context[:420],
        prev_word=prev_word,
        next_word=next_word,
    )
    return jsonify(result)


@app.get("/api/admin/bootstrap")
def api_admin_bootstrap():
    payload = {"ok": True}
    if ALLOW_ADMIN_BOOTSTRAP:
        payload["adminKey"] = ADMIN_KEY
    return jsonify(payload)


@app.post("/api/admin/verify")
def api_admin_verify():
    if not require_admin():
        return jsonify({"error": "unauthorized"}), 401
    return jsonify({"ok": True})


@app.post("/api/admin/transcription/jobs/upload")
def api_admin_transcription_upload():
    if not require_admin():
        return jsonify({"error": "unauthorized"}), 401

    TRANSCRIBE_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    TRANSCRIBE_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    language = normalize_language(request.form.get("language", "zh"))
    term_text = request.form.get("termText", request.form.get("term_text", ""))
    _upsert_transcription_terms(term_text)

    raw_files = []
    for key in ("files", "file"):
        raw_files.extend(request.files.getlist(key))
    files = []
    seen = set()
    for item in raw_files:
        if not item or not normalize_text(item.filename):
            continue
        marker = id(item)
        if marker in seen:
            continue
        seen.add(marker)
        files.append(item)

    if not files:
        return jsonify({"ok": False, "error": "missing files"}), 400
    if len(files) > max(1, MAX_TRANSCRIBE_BATCH):
        return jsonify({"ok": False, "error": f"单次最多上传 {MAX_TRANSCRIBE_BATCH} 个文件"}), 400

    for file in files:
        name = normalize_text(file.filename) or "media"
        ext = Path(name).suffix.lower()
        if ext not in SUPPORTED_MEDIA_EXTS:
            return jsonify({"ok": False, "error": f"不支持的文件类型：{ext or name}"}), 400

    created_jobs = []
    for file in files:
        original_name = normalize_text(file.filename) or "media"
        ext = Path(original_name).suffix.lower()

        temp_name = f"upload-{uuid.uuid4().hex[:12]}{ext}"
        target_path = TRANSCRIBE_UPLOAD_DIR / temp_name
        file.save(str(target_path))
        file_size = int(target_path.stat().st_size if target_path.exists() else 0)
        if file_size <= 0:
            try:
                target_path.unlink(missing_ok=True)
            except Exception:
                pass
            return jsonify({"ok": False, "error": f"上传文件为空：{original_name}"}), 400
        if file_size > MAX_TRANSCRIBE_UPLOAD_BYTES:
            try:
                target_path.unlink(missing_ok=True)
            except Exception:
                pass
            return jsonify({"ok": False, "error": f"文件过大：{original_name}"}), 400

        job_id = TRANSCRIPTION_WORKER.create_job(
            file_name=safe_filename(original_name),
            source_path=str(target_path),
            language=language,
            term_text=term_text,
        )
        created_jobs.append({"id": job_id, "fileName": safe_filename(original_name), "status": "queued"})

    return jsonify(
        {
            "ok": True,
            "jobs": created_jobs,
            "workerEnabled": ENABLE_TRANSCRIPTION_WORKER,
            "lowConfThreshold": read_low_conf_threshold(),
            "provider": TRANSCRIPTION_WORKER.provider_summary(),
        }
    )


@app.get("/api/admin/transcription/jobs")
def api_admin_transcription_jobs():
    if not require_admin():
        return jsonify({"error": "unauthorized"}), 401

    status = normalize_text(request.args.get("status", "")).lower()
    limit = _to_int(request.args.get("limit"), default=50, low=1, high=200)
    offset = _to_int(request.args.get("offset"), default=0, low=0, high=10000)

    query = "SELECT * FROM transcription_jobs"
    params = []
    if status:
        query += " WHERE status = ?"
        params.append(status)
    query += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])

    with db_conn() as conn:
        rows = conn.execute(query, tuple(params)).fetchall()
    items = [_normalize_transcription_row(row) for row in rows]
    return jsonify(
        {
            "ok": True,
            "items": items,
            "limit": limit,
            "offset": offset,
            "provider": TRANSCRIPTION_WORKER.provider_summary(),
        }
    )


@app.get("/api/admin/transcription/jobs/<job_id>")
def api_admin_transcription_job_detail(job_id):
    if not require_admin():
        return jsonify({"error": "unauthorized"}), 401
    row = _load_transcription_job(job_id)
    if not row:
        return jsonify({"ok": False, "error": "job not found"}), 404

    seg_limit = _to_int(request.args.get("segmentLimit"), default=500, low=1, high=3000)
    with db_conn() as conn:
        seg_rows = conn.execute(
            """
            SELECT segment_index, start_sec, end_sec, text, confidence, engine, is_low_conf
            FROM transcription_segments
            WHERE job_id = ?
            ORDER BY segment_index ASC
            LIMIT ?
            """,
            (job_id, seg_limit),
        ).fetchall()
    segments = [
        {
            "segmentIndex": int(seg["segment_index"]),
            "startSec": float(seg["start_sec"]),
            "endSec": float(seg["end_sec"]),
            "text": seg["text"] or "",
            "confidence": float(seg["confidence"] or 0),
            "engine": seg["engine"] or "",
            "isLowConf": int(seg["is_low_conf"] or 0) == 1,
        }
        for seg in seg_rows
    ]
    return jsonify(
        {
            "ok": True,
            "job": _normalize_transcription_row(row),
            "segments": segments,
            "provider": TRANSCRIPTION_WORKER.provider_summary(),
        }
    )


@app.post("/api/admin/transcription/jobs/<job_id>/retry-low-confidence")
def api_admin_transcription_retry_low_conf(job_id):
    if not require_admin():
        return jsonify({"error": "unauthorized"}), 401
    try:
        result = TRANSCRIPTION_WORKER.retry_low_confidence(job_id)
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500
    return jsonify(result)


@app.get("/api/admin/transcription/jobs/<job_id>/download")
def api_admin_transcription_download(job_id):
    if not require_admin():
        return jsonify({"error": "unauthorized"}), 401

    fmt = normalize_text(request.args.get("format", "md")).lower()
    col_map = {"md": "output_md_path", "txt": "output_txt_path", "srt": "output_srt_path"}
    target_col = col_map.get(fmt)
    if not target_col:
        return jsonify({"ok": False, "error": "format must be md/txt/srt"}), 400

    row = _load_transcription_job(job_id)
    if not row:
        return jsonify({"ok": False, "error": "job not found"}), 404
    output_path = normalize_text(row[target_col])
    if not output_path:
        return jsonify({"ok": False, "error": "output not ready"}), 404

    path = Path(output_path)
    if not path.exists() or not path.is_file():
        return jsonify({"ok": False, "error": "file not found"}), 404
    return send_from_directory(str(path.parent), path.name, as_attachment=True, download_name=f"{job_id}.{fmt}")


@app.delete("/api/admin/transcription/jobs/<job_id>")
def api_admin_transcription_delete(job_id):
    if not require_admin():
        return jsonify({"error": "unauthorized"}), 401

    with db_conn() as conn:
        row = conn.execute("SELECT * FROM transcription_jobs WHERE id = ?", (job_id,)).fetchone()
        if not row:
            return jsonify({"ok": False, "error": "job not found"}), 404
        if row["status"] in {"running", "reviewing"}:
            return jsonify({"ok": False, "error": "job is running"}), 409
        conn.execute("DELETE FROM transcription_segments WHERE job_id = ?", (job_id,))
        conn.execute("DELETE FROM transcription_jobs WHERE id = ?", (job_id,))

    _remove_transcription_files(row)
    return jsonify({"ok": True, "deleted": job_id})


@app.post("/api/admin/key/update")
def api_admin_key_update():
    if not require_admin():
        return jsonify({"error": "unauthorized"}), 401
    payload = request.get_json(silent=True) or {}
    new_key = normalize_text(payload.get("newKey"))
    err = validate_admin_key(new_key)
    if err:
        return jsonify({"ok": False, "error": err}), 400
    try:
        save_admin_key(new_key)
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    return jsonify({"ok": True, "message": "管理员密钥已更新"})


@app.post("/api/admin/books")
def api_admin_publish_json():
    if not require_admin():
        return jsonify({"error": "unauthorized"}), 401
    payload = request.get_json(silent=True) or {}
    try:
        book = normalize_book(payload)
        save_book(book)
        return jsonify(
            {
                "ok": True,
                "book": {
                    "id": book["id"],
                    "title": book["title"],
                    "chapter_count": len(book["chapters"]),
                },
            }
        )
    except Exception as exc:
        return jsonify({"error": str(exc)}), 400


@app.post("/api/admin/books/upload")
def api_admin_upload_file():
    if not require_admin():
        return jsonify({"error": "unauthorized"}), 401

    file = request.files.get("file")
    if not file:
        return jsonify({"error": "missing file"}), 400

    filename = file.filename or "book"
    raw_bytes = file.read()
    ext = Path(filename).suffix.lower()
    try:
        if ext == ".json":
            content = raw_bytes.decode("utf-8", errors="ignore")
            raw_book = json.loads(content)
        elif ext == ".docx":
            raw_book = parse_docx_book(raw_bytes, filename)
        else:
            content = raw_bytes.decode("utf-8", errors="ignore")
            raw_book = parse_markdown_book(content, filename)

        if request.form.get("book_id"):
            raw_book["id"] = request.form.get("book_id")
        if request.form.get("book_title"):
            raw_book["title"] = request.form.get("book_title")
        if request.form.get("book_cover_url"):
            raw_book["coverUrl"] = request.form.get("book_cover_url")
        if request.form.get("book_category"):
            raw_book["category"] = request.form.get("book_category")

        book = normalize_book(raw_book)
        tasks_text = request.form.get("tasks_text", "")
        book = apply_tasks(book, tasks_text)
        save_book(book)

        return jsonify(
            {
                "ok": True,
                "book": {
                    "id": book["id"],
                    "title": book["title"],
                    "chapter_count": len(book["chapters"]),
                },
            }
        )
    except Exception as exc:
        return jsonify({"error": str(exc)}), 400


@app.patch("/api/admin/books/<book_id>")
def api_admin_update_book(book_id):
    if not require_admin():
        return jsonify({"error": "unauthorized"}), 401
    payload = request.get_json(silent=True) or {}
    with db_conn() as conn:
        row = conn.execute("SELECT * FROM books WHERE id = ?", (book_id,)).fetchone()
        if not row:
            return jsonify({"error": "book not found"}), 404
        fields = {
            "title": normalize_text(payload.get("title")) or row["title"],
            "description": normalize_text(payload.get("description")) or row["description"],
            "cover_url": normalize_text(payload.get("coverUrl")) if "coverUrl" in payload else (row["cover_url"] or ""),
            "category": normalize_text(payload.get("category")) if "category" in payload else (row["category"] or ""),
            "sort_order": int(payload.get("sortOrder")) if "sortOrder" in payload and str(payload.get("sortOrder")).strip() != "" else int(row["sort_order"] or 0),
            "updated_at": datetime.utcnow().isoformat(timespec="seconds"),
        }
        conn.execute(
            """
            UPDATE books
            SET title = ?, description = ?, cover_url = ?, category = ?, sort_order = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                fields["title"],
                fields["description"],
                fields["cover_url"],
                fields["category"],
                fields["sort_order"],
                fields["updated_at"],
                book_id,
            ),
        )
        if "tasksText" in payload:
            tasks_text = normalize_text(payload.get("tasksText"))
            chapter_rows = conn.execute(
                "SELECT chapter_index, target_words_json FROM chapters WHERE book_id = ? ORDER BY chapter_index ASC",
                (book_id,),
            ).fetchall()
            chapter_count = len(chapter_rows)
            task_map = parse_tasks_text(tasks_text, chapter_count)
            for chapter_row in chapter_rows:
                chapter_idx = int(chapter_row["chapter_index"])
                conn.execute(
                    "UPDATE chapters SET target_words_json = ? WHERE book_id = ? AND chapter_index = ?",
                    (json.dumps(task_map.get(chapter_idx, []), ensure_ascii=False), book_id, chapter_idx),
                )
    return jsonify({"ok": True})


@app.post("/api/admin/books/reorder")
def api_admin_reorder_books():
    if not require_admin():
        return jsonify({"error": "unauthorized"}), 401
    payload = request.get_json(silent=True) or {}
    ordered_ids = payload.get("orderedIds")
    if not isinstance(ordered_ids, list):
        return jsonify({"error": "orderedIds must be a list"}), 400

    clean_ids = [normalize_text(item) for item in ordered_ids if normalize_text(item)]
    if not clean_ids:
        return jsonify({"error": "orderedIds is empty"}), 400

    with db_conn() as conn:
        rows = conn.execute("SELECT id FROM books").fetchall()
        existing = {row["id"] for row in rows}
        for book_id in clean_ids:
            if book_id not in existing:
                return jsonify({"error": f"book not found: {book_id}"}), 404
        for idx, book_id in enumerate(clean_ids):
            conn.execute(
                "UPDATE books SET sort_order = ?, updated_at = ? WHERE id = ?",
                (idx, datetime.utcnow().isoformat(timespec="seconds"), book_id),
            )
    return jsonify({"ok": True})


@app.delete("/api/admin/books/<book_id>")
def api_admin_delete_book(book_id):
    if not require_admin():
        return jsonify({"error": "unauthorized"}), 401
    with db_conn() as conn:
        row = conn.execute("SELECT id FROM books WHERE id = ?", (book_id,)).fetchone()
        if not row:
            return jsonify({"error": "book not found"}), 404
        conn.execute("DELETE FROM chapters WHERE book_id = ?", (book_id,))
        conn.execute("DELETE FROM books WHERE id = ?", (book_id,))
    return jsonify({"ok": True})


@app.get("/api/novel-studio/health")
def api_novel_studio_health():
    orchestrator = get_request_orchestrator()
    return jsonify(
        {
            "ok": True,
            "provider": "moonshot" if orchestrator.llm.enabled() else "offline-fallback",
            "model": orchestrator.llm.model if orchestrator.llm.enabled() else "fallback-template",
        }
    )


@app.get("/api/novel-studio/student-profile-template")
def api_novel_studio_student_profile_template():
    return jsonify({"ok": True, "template": STUDENT_PROFILE_TEMPLATE})


@app.get("/api/novel-studio/project-state")
def api_novel_studio_project_state():
    project_name = request.args.get("projectName", "")
    if not normalize_text(project_name):
        return jsonify({"ok": True, "state": {}, "studentProfile": normalize_student_profile({}), "routingStrategy": {}, "updatedAt": ""})
    state = get_project_state(project_name)
    return jsonify({"ok": True, **state})


@app.get("/api/novel-studio/knowledge")
def api_novel_studio_knowledge_list():
    query = request.args.get("q", "")
    limit = request.args.get("limit", "120")
    rows = list_knowledge(limit=limit, query=query)
    return jsonify({"ok": True, "items": rows})


@app.post("/api/novel-studio/knowledge")
def api_novel_studio_knowledge_create():
    if not require_admin():
        return jsonify({"error": "unauthorized"}), 401
    payload = request.get_json(silent=True) or {}
    try:
        created_ids = create_knowledge(
            title=payload.get("title"),
            content=payload.get("content"),
            tags=payload.get("tags", ""),
            source=payload.get("source", "manual"),
            auto_chunk=bool(payload.get("autoChunk", True)),
        )
        items = get_knowledge_by_ids(created_ids)
        return jsonify({"ok": True, "createdCount": len(created_ids), "items": items})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400


@app.delete("/api/novel-studio/knowledge/<knowledge_id>")
def api_novel_studio_knowledge_delete(knowledge_id):
    if not require_admin():
        return jsonify({"error": "unauthorized"}), 401
    ok = delete_knowledge(knowledge_id)
    if not ok:
        return jsonify({"error": "knowledge not found"}), 404
    return jsonify({"ok": True})


@app.post("/api/novel-studio/outline")
def api_novel_studio_outline():
    if not require_admin():
        return jsonify({"error": "unauthorized"}), 401
    payload = request.get_json(silent=True) or {}
    if not normalize_text(payload.get("premise")):
        return jsonify({"error": "premise is required"}), 400
    if not normalize_text(payload.get("projectName")):
        return jsonify({"error": "projectName is required"}), 400

    payload["totalChapters"] = _to_int(payload.get("totalChapters"), default=20, low=1, high=200)
    payload["chapterIndex"] = 1
    saved_state = get_project_state(payload.get("projectName"))
    payload["projectState"] = saved_state.get("state") or {}
    payload["recentChapters"] = list_project_chapter_context(payload.get("projectName"), limit=60)
    payload["studentProfile"] = parse_student_profile_payload(payload.get("studentProfile") or saved_state.get("studentProfile"))
    selected_knowledge = resolve_knowledge_for_generation(payload)
    require_llm = _to_bool(payload.get("requireLLM"), False)
    retry_on_transient = _to_bool(payload.get("retryOnTransient"), True)
    max_outline_attempts = _to_int(payload.get("maxOutlineAttempts"), default=2, low=1, high=3)
    retry_wait_seconds = _to_int(payload.get("retryWaitSeconds"), default=8, low=2, high=45)
    if not require_llm:
        max_outline_attempts = 1
    attempt_details = []
    result = None
    try:
        for attempt in range(1, max_outline_attempts + 1):
            orchestrator = get_request_orchestrator(payload)
            result = orchestrator.generate_outline(payload, selected_knowledge)
            transient = _result_has_transient_warning(result)
            quality_hint = "ok"
            if transient:
                quality_hint = "transient_warning"
            attempt_details.append(
                {
                    "attempt": attempt,
                    "transientWarning": transient,
                    "qualityHint": quality_hint,
                }
            )
            should_retry = retry_on_transient and require_llm and transient and attempt < max_outline_attempts
            if not should_retry:
                break
            time.sleep(retry_wait_seconds * attempt)
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    if isinstance(result, dict):
        result["generationAttempts"] = {
            "total": len(attempt_details),
            "max": max_outline_attempts,
            "details": attempt_details,
        }
    return jsonify({"ok": True, "result": result})


@app.post("/api/novel-studio/generate")
def api_novel_studio_generate():
    if not require_admin():
        return jsonify({"error": "unauthorized"}), 401
    payload = request.get_json(silent=True) or {}
    if not normalize_text(payload.get("premise")):
        return jsonify({"error": "premise is required"}), 400
    if not normalize_text(payload.get("projectName")):
        return jsonify({"error": "projectName is required"}), 400

    chapter_index = _to_int(payload.get("chapterIndex"), default=1, low=1, high=2000)
    total_chapters = _to_int(payload.get("totalChapters"), default=20, low=1, high=2000)
    payload["chapterIndex"] = chapter_index
    payload["totalChapters"] = total_chapters

    saved_state = get_project_state(payload.get("projectName"))
    payload["projectState"] = saved_state.get("state") or {}
    payload["recentChapters"] = list_project_chapter_context(payload.get("projectName"), limit=80)
    payload["studentProfile"] = parse_student_profile_payload(payload.get("studentProfile") or saved_state.get("studentProfile"))

    if "energyBefore" not in payload:
        payload["energyBefore"] = latest_project_energy(payload.get("projectName"))

    selected_knowledge = resolve_knowledge_for_generation(payload)
    require_llm = _to_bool(payload.get("requireLLM"), False)
    retry_on_transient = _to_bool(payload.get("retryOnTransient"), True)
    strict_quality_gate = _to_bool(payload.get("strictQualityGate"), True)
    max_generation_attempts = _to_int(payload.get("maxGenerationAttempts"), default=2, low=1, high=4)
    retry_wait_seconds = _to_int(payload.get("retryWaitSeconds"), default=10, low=2, high=60)
    if not require_llm:
        max_generation_attempts = 1

    result = None
    attempt_details = []
    last_error = ""
    try:
        for attempt in range(1, max_generation_attempts + 1):
            orchestrator = get_request_orchestrator(payload)
            result = orchestrator.generate_chapter(payload, selected_knowledge)
            quality = result.get("quality") if isinstance(result, dict) and isinstance(result.get("quality"), dict) else {}
            score = _to_int(quality.get("score"), default=0, low=0, high=100)
            passed = bool(quality.get("passed"))
            transient = _result_has_transient_warning(result)
            needs_retry = (
                retry_on_transient
                and require_llm
                and attempt < max_generation_attempts
                and _chapter_result_needs_retry(result, strict_quality_gate=strict_quality_gate)
            )
            attempt_details.append(
                {
                    "attempt": attempt,
                    "qualityPassed": passed,
                    "qualityScore": score,
                    "transientWarning": transient,
                    "retryPlanned": needs_retry,
                }
            )
            if not needs_retry:
                break
            time.sleep(retry_wait_seconds * attempt)
    except Exception as exc:
        last_error = str(exc)
        if (
            retry_on_transient
            and require_llm
            and len(attempt_details) < max_generation_attempts
            and _is_transient_model_text(last_error)
        ):
            for attempt in range(len(attempt_details) + 1, max_generation_attempts + 1):
                try:
                    time.sleep(retry_wait_seconds * attempt)
                    orchestrator = get_request_orchestrator(payload)
                    result = orchestrator.generate_chapter(payload, selected_knowledge)
                    quality = result.get("quality") if isinstance(result, dict) and isinstance(result.get("quality"), dict) else {}
                    score = _to_int(quality.get("score"), default=0, low=0, high=100)
                    passed = bool(quality.get("passed"))
                    transient = _result_has_transient_warning(result)
                    needs_retry = (
                        retry_on_transient
                        and require_llm
                        and attempt < max_generation_attempts
                        and _chapter_result_needs_retry(result, strict_quality_gate=strict_quality_gate)
                    )
                    attempt_details.append(
                        {
                            "attempt": attempt,
                            "qualityPassed": passed,
                            "qualityScore": score,
                            "transientWarning": transient,
                            "retryPlanned": needs_retry,
                        }
                    )
                    if not needs_retry:
                        break
                except Exception as retry_exc:
                    last_error = str(retry_exc)
                    attempt_details.append(
                        {
                            "attempt": attempt,
                            "qualityPassed": False,
                            "qualityScore": 0,
                            "transientWarning": _is_transient_model_text(last_error),
                            "retryPlanned": attempt < max_generation_attempts,
                            "error": last_error,
                        }
                    )
                    if not (_is_transient_model_text(last_error) and attempt < max_generation_attempts):
                        break
        if result is None:
            return jsonify({"ok": False, "error": last_error or str(exc)}), 400

    if isinstance(result, dict):
        result["generationAttempts"] = {
            "total": len(attempt_details),
            "max": max_generation_attempts,
            "details": attempt_details,
        }
    record_id = save_novel_chapter_result(
        project_name=payload.get("projectName"),
        chapter_index=chapter_index,
        total_chapters=total_chapters,
        result=result,
    )
    project_state = (result.get("projectState") or {}).get("merged") or {}
    routing_strategy = result.get("routingStrategy") or {}
    student_profile = result.get("studentProfile") or payload.get("studentProfile") or {}
    upsert_project_state(
        project_name=payload.get("projectName"),
        state=project_state,
        student_profile=student_profile,
        routing=routing_strategy,
    )
    memory_snapshot_id = persist_project_memory_snapshot(
        project_name=payload.get("projectName"),
        chapter_index=chapter_index,
        merged_state=project_state,
        student_profile=student_profile,
        routing_strategy=routing_strategy,
    )
    result["memorySnapshotKnowledgeId"] = memory_snapshot_id
    return jsonify({"ok": True, "recordId": record_id, "result": result})


@app.get("/api/novel-studio/chapters")
def api_novel_studio_chapters():
    project_name = request.args.get("projectName", "")
    limit = request.args.get("limit", "30")
    items = list_project_chapters(project_name=project_name, limit=limit)
    return jsonify({"ok": True, "items": items})


@app.get("/config.js")
def app_config_js():
    content = "window.APP_CONFIG = { apiBaseUrl: '/api', userCanUpload: false };"
    return app.response_class(content, mimetype="application/javascript")


@app.get("/")
def home():
    return redirect("/reader", code=302)


@app.get("/admin")
def admin_page():
    return send_from_directory(APP_ROOT, "admin.html")


@app.get("/bookshelf-admin")
def bookshelf_admin_page():
    return send_from_directory(APP_ROOT, "admin.html")


@app.get("/transcribe-admin")
def transcribe_admin_page():
    return send_from_directory(APP_ROOT, "transcribe_admin.html")


@app.get("/reader")
def reader_page():
    return redirect("/index.html", code=302)


@app.get("/generator")
def generator_page():
    return redirect("/index.html", code=302)


@app.get("/novel-studio")
def novel_studio_page():
    return send_from_directory(APP_ROOT, "novel_studio.html")


@app.get("/user-covers/<path:filepath>")
def user_covers(filepath):
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    return send_from_directory(str(UPLOAD_DIR), filepath)


@app.get("/<path:path>")
def static_files(path):
    full_path = APP_ROOT / path
    if full_path.exists() and full_path.is_file():
        return send_from_directory(APP_ROOT, path)
    return send_from_directory(APP_ROOT, "index.html")


if __name__ == "__main__":
    init_db()
    port = int(os.getenv("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
