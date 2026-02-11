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

from flask import Flask, jsonify, redirect, request, send_from_directory

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
              updated_at TEXT NOT NULL,
              cover_url TEXT NOT NULL DEFAULT '',
              category TEXT NOT NULL DEFAULT '',
              sort_order INTEGER NOT NULL DEFAULT 0
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
        "coverUrl": normalize_text(raw_book.get("coverUrl")),
        "category": normalize_text(raw_book.get("category")),
        "sortOrder": int(raw_book.get("sortOrder") or 0),
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
    api_key = normalize_text(request.headers.get("X-Moonshot-Api-Key", "")) or normalize_text(data.get("moonshotApiKey"))
    if not api_key:
        return ORCHESTRATOR

    model = normalize_text(request.headers.get("X-Moonshot-Model", "")) or normalize_text(data.get("moonshotModel"))
    base_url = normalize_text(request.headers.get("X-Moonshot-Base-Url", "")) or normalize_text(data.get("moonshotBaseUrl"))
    timeout_raw = normalize_text(request.headers.get("X-Moonshot-Timeout", "")) or normalize_text(data.get("moonshotTimeoutSeconds"))
    try:
        timeout_seconds = float(timeout_raw) if timeout_raw else float(os.getenv("MOONSHOT_TIMEOUT_SECONDS", "120"))
    except Exception:
        timeout_seconds = float(os.getenv("MOONSHOT_TIMEOUT_SECONDS", "120"))

    client = MoonshotClient(
        api_key=api_key,
        base_url=base_url or os.getenv("MOONSHOT_BASE_URL", "https://api.moonshot.cn/v1"),
        model=model or os.getenv("MOONSHOT_MODEL", "kimi-k2-0905-preview"),
        timeout_seconds=timeout_seconds,
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


init_db()
ensure_book_columns()
init_novel_tables()


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


@app.post("/api/admin/verify")
def api_admin_verify():
    if not require_admin():
        return jsonify({"error": "unauthorized"}), 401
    return jsonify({"ok": True})


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
    orchestrator = get_request_orchestrator(payload)
    result = orchestrator.generate_outline(payload, selected_knowledge)
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
    orchestrator = get_request_orchestrator(payload)
    result = orchestrator.generate_chapter(payload, selected_knowledge)
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
    return redirect("/novel-studio", code=302)


@app.get("/admin")
def admin_page():
    return send_from_directory(APP_ROOT, "admin.html")


@app.get("/reader")
def reader_page():
    return redirect("/index.html", code=302)


@app.get("/novel-studio")
def novel_studio_page():
    return send_from_directory(APP_ROOT, "novel_studio.html")


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
