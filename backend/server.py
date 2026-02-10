import json
import os
import re
import sqlite3
import uuid
from datetime import datetime
from html import unescape
from pathlib import Path
from urllib.parse import quote
from urllib.request import Request, urlopen

from flask import Flask, jsonify, request, send_from_directory


APP_ROOT = Path(__file__).resolve().parents[1]
DB_PATH = Path(os.getenv("BOOK_DB_PATH", APP_ROOT / "backend" / "books.db"))
ADMIN_KEY = os.getenv("ADMIN_KEY", "change-this-admin-key")
ALLOW_ADMIN_BOOTSTRAP = os.getenv("ALLOW_ADMIN_BOOTSTRAP", "0") == "1"

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
              updated_at TEXT NOT NULL
            )
            """
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


def require_admin():
    key = request.headers.get("X-Admin-Key", "")
    return bool(key) and key == ADMIN_KEY


def normalize_text(value):
    if value is None:
        return ""
    return unescape(str(value)).strip()


def normalize_word(value):
    text = normalize_text(value).lower()
    text = re.sub(r"[^a-zA-Z'\-\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


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
        "chapters": chapters,
    }


def parse_markdown_book(content, file_name):
    lines = [
        unescape(line)
        for line in content.replace("\ufeff", "").replace("\r", "").split("\n")
    ]
    heading_regex = re.compile(r"^\s{0,3}(#{1,6})\s+(.*?)\s*$")
    chapter_regex = re.compile(
        r"(第\s*(\d+|[一二三四五六七八九十百零两]+)\s*章|Chapter\s*\d+)",
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
    if not chapter_headings:
        raise ValueError("Markdown 未识别到章节标题，请使用 # 第1章 或 # Chapter 1 形式。")

    first_h1 = next(
        (h for h in headings if h["level"] == 1 and not chapter_regex.search(h["title"])),
        None,
    )
    fallback_title = re.sub(r"\.[^.]+$", "", file_name or "未命名小说")
    book_title = first_h1["title"] if first_h1 else fallback_title

    chapters = []
    for i, heading in enumerate(chapter_headings):
        start = heading["line"] + 1
        end = chapter_headings[i + 1]["line"] if i + 1 < len(chapter_headings) else len(lines)
        body_lines = lines[start:end]
        cleaned = []
        last_blank = False

        for line in body_lines:
            trimmed = line.strip()
            if re.match(r"^[=\-_*]{3,}$", trimmed):
                continue

            h = heading_regex.match(line)
            if h and not chapter_regex.search(normalize_text(h.group(2))):
                title_text = normalize_text(h.group(2))
                if title_text:
                    cleaned.append(title_text)
                    last_blank = False
                continue

            if not trimmed:
                if not last_blank:
                    cleaned.append("")
                    last_blank = True
                continue

            if re.match(r"^[（(【\[]?\s*第?.{0,20}章完\s*[】\])）)]?$", trimmed):
                continue

            cleaned.append(unescape(line))
            last_blank = False

        body = "\n".join(cleaned).strip()
        if not body:
            continue
        chapters.append(
            {
                "title": heading["title"],
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


def parse_tasks_text(tasks_text, chapter_count):
    tasks_map = {idx: [] for idx in range(chapter_count)}
    if not tasks_text:
        return tasks_map

    seen = {idx: set() for idx in range(chapter_count)}
    active_chapter_idx = None
    chapter_heading_regex = re.compile(
        r"^\s{0,3}#{2,6}\s*(?:(?:第\s*)?(\d+)\s*章(?:单词表)?|chapter\s*(\d+)\b)",
        re.IGNORECASE,
    )

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

        heading_match = chapter_heading_regex.match(line)
        if heading_match:
            chapter_no = int(heading_match.group(1) or heading_match.group(2))
            chapter_idx = chapter_no - 1
            active_chapter_idx = chapter_idx if 0 <= chapter_idx < chapter_count else None
            continue

        # 兼容旧格式：章节序号|word|translation
        parts = [p.strip() for p in line.split("|")]
        if parts and parts[0].isdigit():
            chapter_idx = int(parts[0]) - 1
            if len(parts) >= 2:
                word = parts[1]
                translation = parts[2] if len(parts) >= 3 else ""
                add_task(chapter_idx, word, translation)
            continue

        # 兼容格式：word|translation（章节由上一个 ### 章节标题决定）
        if len(parts) >= 1 and active_chapter_idx is not None and "|" in line:
            word = parts[0]
            translation = parts[1] if len(parts) >= 2 else ""
            add_task(active_chapter_idx, word, translation)
            continue

        if line.startswith("#"):
            continue

        # 新格式：### 1章单词表 + 逗号分隔单词（可无中文）
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
            INSERT INTO books (id, title, description, word_goal, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
              title=excluded.title,
              description=excluded.description,
              word_goal=excluded.word_goal,
              updated_at=excluded.updated_at
            """,
            (book["id"], book["title"], book["description"], int(book["wordGoal"]), now),
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
        book_rows = conn.execute("SELECT * FROM books ORDER BY updated_at DESC").fetchall()
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
                    "chapters": chapters,
                }
            )
        return books


init_db()


@app.get("/api/health")
def health():
    return jsonify({"ok": True})


@app.get("/api/public/books")
def api_public_books():
    return jsonify({"books": load_books()})


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
    content = file.read().decode("utf-8", errors="ignore")
    ext = Path(filename).suffix.lower()
    try:
        if ext == ".json":
            raw_book = json.loads(content)
        else:
            raw_book = parse_markdown_book(content, filename)

        if request.form.get("book_id"):
            raw_book["id"] = request.form.get("book_id")
        if request.form.get("book_title"):
            raw_book["title"] = request.form.get("book_title")

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


@app.get("/config.js")
def app_config_js():
    content = "window.APP_CONFIG = { apiBaseUrl: '/api', userCanUpload: false };"
    return app.response_class(content, mimetype="application/javascript")


@app.get("/")
def home():
    return send_from_directory(APP_ROOT, "index.html")


@app.get("/admin")
def admin_page():
    return send_from_directory(APP_ROOT, "admin.html")


@app.get("/<path:path>")
def static_files(path):
    full_path = APP_ROOT / path
    if full_path.exists() and full_path.is_file():
        return send_from_directory(APP_ROOT, path)
    return send_from_directory(APP_ROOT, "index.html")


if __name__ == "__main__":
    init_db()
    port = int(os.getenv("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, debug=False)
