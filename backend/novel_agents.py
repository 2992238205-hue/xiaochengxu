import json
import os
import random
import re
import socket
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


STAGE_DEFINITIONS = {
    1: "信息接收者：被动、依赖权威、死记硬背。",
    2: "逻辑追问者：开始主动思考，尝试放弃低效努力。",
    3: "本质拆解者：能用第一性原理拆解问题到最小单元。",
    4: "矛盾聚焦者：能识别主要矛盾并集中火力歼灭。",
    5: "立体建构者：规律迁移、多维反思、开始照见执念。",
    6: "无招创造者：基于本质自由创造，创造力持续涌现。",
    7: "归零破执者（远景）：破我执，智慧更稳定。",
    8: "仁者主体者（远景）：发心至善，主体性圆满。",
    9: "明心见性者（远景）：自觉觉他，慈悲而坚定。",
    10: "与道合一体（远景）：与规律同频，无为而无不为。",
}


DEFAULT_DEEP_THINKING_CARD = (
    "深度思考=矛盾论+第一性原理+立体多维。"
    "每次先问白痴问题，再5Why追问，找到最小单元与组合规律，"
    "最后重构方案并落地行动。"
)


STUDENT_PROFILE_TEMPLATE = {
    "name": "默认学生",
    "grade_stage": "高三",
    "base_score": 320,
    "target_score": 640,
    "subject_strengths": ["语文"],
    "subject_weaknesses": ["英语", "数学"],
    "personality_traits": ["内向", "怕被否定", "遇事犹豫"],
    "motivation_source": "不想重复上一世的失败，想证明自己可以逆袭",
    "family_pressure_level": 7,
    "school_pressure_level": 8,
    "self_discipline_level": 4,
    "anxiety_level": 8,
    "risk_tolerance_level": 3,
    "short_video_addiction_level": 7,
    "confidence_level": 3,
    "social_sensitivity_level": 8,
    "romance_expectation_level": 5,
    "notes": "希望通过可复制的方法快速看到提分反馈。",
}


def now_iso() -> str:
    return datetime.utcnow().isoformat(timespec="seconds")


def normalize_text(value: Optional[str]) -> str:
    if value is None:
        return ""
    return str(value).strip()


def compact_text(text: str, max_chars: int, head_ratio: float = 0.72) -> str:
    raw = normalize_text(text)
    if max_chars <= 0 or len(raw) <= max_chars:
        return raw
    head_len = int(max_chars * head_ratio)
    tail_len = max(0, max_chars - head_len - 16)
    if tail_len <= 0:
        return raw[:max_chars]
    return f"{raw[:head_len]}\n...(truncated)...\n{raw[-tail_len:]}"


def clamp_int(value: int, low: int, high: int) -> int:
    return max(low, min(high, int(value)))


def clamp_or_default(value, default: int, low: int, high: int) -> int:
    try:
        parsed = int(value)
    except Exception:
        parsed = int(default)
    return clamp_int(parsed, low, high)


def to_bool(value, default: bool = True) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    text = normalize_text(value).lower()
    if text in {"1", "true", "yes", "on", "y"}:
        return True
    if text in {"0", "false", "no", "off", "n"}:
        return False
    return default


def normalize_student_profile(raw: Optional[Dict]) -> Dict:
    source = raw if isinstance(raw, dict) else {}
    profile = dict(STUDENT_PROFILE_TEMPLATE)
    for key in profile.keys():
        if key not in source:
            continue
        value = source[key]
        if key in {
            "family_pressure_level",
            "school_pressure_level",
            "self_discipline_level",
            "anxiety_level",
            "risk_tolerance_level",
            "short_video_addiction_level",
            "confidence_level",
            "social_sensitivity_level",
            "romance_expectation_level",
        }:
            profile[key] = clamp_or_default(value, profile[key], 0, 10)
        elif key in {"base_score", "target_score"}:
            profile[key] = clamp_or_default(value, profile[key], 0, 1000)
        elif key in {"subject_strengths", "subject_weaknesses", "personality_traits"}:
            if isinstance(value, list):
                cleaned = [normalize_text(item) for item in value if normalize_text(item)]
            else:
                cleaned = [normalize_text(part) for part in re.split(r"[,，;；、\s]+", normalize_text(value)) if normalize_text(part)]
            profile[key] = cleaned[:10]
        else:
            profile[key] = normalize_text(value)

    if profile["target_score"] < profile["base_score"]:
        profile["target_score"] = profile["base_score"]
    return profile


def build_routing_strategy(profile: Dict, hero_stage: int, chapter_index: int, total_chapters: int) -> Dict:
    anxiety = clamp_or_default(profile.get("anxiety_level"), 6, 0, 10)
    confidence = clamp_or_default(profile.get("confidence_level"), 4, 0, 10)
    discipline = clamp_or_default(profile.get("self_discipline_level"), 4, 0, 10)
    risk = clamp_or_default(profile.get("risk_tolerance_level"), 4, 0, 10)
    short_video = clamp_or_default(profile.get("short_video_addiction_level"), 6, 0, 10)
    social = clamp_or_default(profile.get("social_sensitivity_level"), 7, 0, 10)
    base_score = clamp_or_default(profile.get("base_score"), 300, 0, 1000)
    target_score = clamp_or_default(profile.get("target_score"), 600, 0, 1000)
    score_gap = max(0, target_score - base_score)

    lane = "稳态推进线"
    if anxiety >= 8 and confidence <= 4:
        lane = "高压去恐惧线"
    elif discipline <= 4 and short_video >= 7:
        lane = "执行力修复线"
    elif risk <= 4 and social >= 7:
        lane = "主体性破胆线"
    elif score_gap >= 280:
        lane = "基础重建速攻线"
    elif hero_stage >= 5:
        lane = "创造迁移线"

    toxic_level = clamp_int(3 + (anxiety + short_video - confidence) // 4, 2, 9)
    challenge_intensity = clamp_int(4 + score_gap // 120 + hero_stage, 3, 10)
    emotion_focus = "羞耻->觉察->行动"
    if lane == "执行力修复线":
        emotion_focus = "拖延->痛感->纪律"
    elif lane == "主体性破胆线":
        emotion_focus = "讨好->犹豫->立场"
    elif lane == "创造迁移线":
        emotion_focus = "焦虑->整合->创造"

    subject_focus = profile.get("subject_weaknesses") or ["英语"]
    if not isinstance(subject_focus, list):
        subject_focus = [normalize_text(subject_focus)]
    subject_focus = [normalize_text(item) for item in subject_focus if normalize_text(item)] or ["英语"]

    midpoint = max(1, int(total_chapters * 0.5))
    pacing_mode = "前压后爆"
    if chapter_index > midpoint:
        pacing_mode = "稳扎稳打+高价值反转"

    return {
        "lane": lane,
        "challenge_intensity": challenge_intensity,
        "toxic_tutor_level": toxic_level,
        "emotion_focus": emotion_focus,
        "subject_focus": subject_focus[:3],
        "pacing_mode": pacing_mode,
        "dialogue_style": "高压追问+短句棒喝+给可执行动作",
        "conflict_axis": "外部权威流程 vs 主角主体性策略",
        "must_have_scene_types": ["学习实操", "社交压力场", "结果验证"],
        "reader_resonance_points": [
            "怕被否定但又不甘心",
            "低效假努力导致自我怀疑",
            "用一次可见突破建立信心",
        ],
    }


def normalize_project_state(raw: Optional[Dict]) -> Dict:
    state = raw if isinstance(raw, dict) else {}
    normalized = {
        "characters": [],
        "relationships": [],
        "timeline": [],
        "world_rules": [],
        "open_loops": [],
        "stage_progress": [],
        "summary_for_next_chapter": "",
    }
    for key in normalized.keys():
        value = state.get(key)
        if key == "summary_for_next_chapter":
            normalized[key] = normalize_text(value)
            continue
        if isinstance(value, list):
            normalized[key] = value
    return normalized


def _unique_list(items: List[str]) -> List[str]:
    seen = set()
    output = []
    for item in items:
        text = normalize_text(item)
        if not text:
            continue
        lowered = text.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        output.append(text)
    return output


def merge_project_state(previous: Optional[Dict], delta: Optional[Dict], chapter_index: int, hero_stage: int) -> Dict:
    prev = normalize_project_state(previous)
    inc = normalize_project_state(delta)

    merged_chars = {}
    for row in prev.get("characters", []):
        if not isinstance(row, dict):
            continue
        name = normalize_text(row.get("name"))
        if not name:
            continue
        merged_chars[name] = {
            "name": name,
            "role": normalize_text(row.get("role")),
            "traits": _unique_list(row.get("traits", []) if isinstance(row.get("traits"), list) else []),
            "status": normalize_text(row.get("status")),
            "goals": _unique_list(row.get("goals", []) if isinstance(row.get("goals"), list) else []),
        }
    for row in inc.get("characters", []):
        if not isinstance(row, dict):
            continue
        name = normalize_text(row.get("name"))
        if not name:
            continue
        base = merged_chars.get(
            name,
            {"name": name, "role": "", "traits": [], "status": "", "goals": []},
        )
        role = normalize_text(row.get("role"))
        if role:
            base["role"] = role
        status = normalize_text(row.get("status"))
        if status:
            base["status"] = status
        base["traits"] = _unique_list(base["traits"] + (row.get("traits", []) if isinstance(row.get("traits"), list) else []))
        base["goals"] = _unique_list(base["goals"] + (row.get("goals", []) if isinstance(row.get("goals"), list) else []))
        merged_chars[name] = base

    relation_map = {}
    for row in prev.get("relationships", []):
        if not isinstance(row, dict):
            continue
        a = normalize_text(row.get("a"))
        b = normalize_text(row.get("b"))
        rel_type = normalize_text(row.get("type"))
        if not a or not b:
            continue
        key = (a, b, rel_type)
        relation_map[key] = {
            "a": a,
            "b": b,
            "type": rel_type,
            "status": normalize_text(row.get("status")),
            "notes": normalize_text(row.get("notes")),
        }
    for row in inc.get("relationships", []):
        if not isinstance(row, dict):
            continue
        a = normalize_text(row.get("a"))
        b = normalize_text(row.get("b"))
        rel_type = normalize_text(row.get("type"))
        if not a or not b:
            continue
        key = (a, b, rel_type)
        base = relation_map.get(
            key,
            {"a": a, "b": b, "type": rel_type, "status": "", "notes": ""},
        )
        status = normalize_text(row.get("status"))
        notes = normalize_text(row.get("notes"))
        if status:
            base["status"] = status
        if notes:
            base["notes"] = notes
        relation_map[key] = base

    timeline = []
    for row in prev.get("timeline", []):
        if isinstance(row, dict):
            timeline.append(row)
    for row in inc.get("timeline", []):
        if isinstance(row, dict):
            timeline.append(row)
    dedup_timeline = []
    seen_timeline = set()
    for row in timeline:
        chapter = clamp_or_default(row.get("chapter"), chapter_index, 1, 9999)
        event = normalize_text(row.get("event"))
        impact = normalize_text(row.get("impact"))
        key = f"{chapter}|{event}|{impact}"
        if not event or key in seen_timeline:
            continue
        seen_timeline.add(key)
        dedup_timeline.append({"chapter": chapter, "event": event, "impact": impact})
    dedup_timeline.sort(key=lambda item: item.get("chapter", 0))

    world_rules = _unique_list(
        (prev.get("world_rules", []) if isinstance(prev.get("world_rules"), list) else [])
        + (inc.get("world_rules", []) if isinstance(inc.get("world_rules"), list) else [])
    )

    loop_map = {}
    for row in prev.get("open_loops", []):
        if not isinstance(row, dict):
            continue
        loop_id = normalize_text(row.get("id")) or normalize_text(row.get("description"))
        if not loop_id:
            continue
        loop_map[loop_id] = {
            "id": normalize_text(row.get("id")) or loop_id,
            "description": normalize_text(row.get("description")),
            "status": normalize_text(row.get("status")) or "open",
            "introduced_in": clamp_or_default(row.get("introduced_in"), 1, 1, 9999),
            "updated_in": clamp_or_default(row.get("updated_in"), chapter_index, 1, 9999),
        }

    for row in inc.get("open_loops", []):
        if not isinstance(row, dict):
            continue
        loop_id = normalize_text(row.get("id")) or normalize_text(row.get("description"))
        if not loop_id:
            continue
        base = loop_map.get(
            loop_id,
            {
                "id": normalize_text(row.get("id")) or loop_id,
                "description": normalize_text(row.get("description")),
                "status": "open",
                "introduced_in": chapter_index,
                "updated_in": chapter_index,
            },
        )
        desc = normalize_text(row.get("description"))
        status = normalize_text(row.get("status"))
        if desc:
            base["description"] = desc
        if status:
            base["status"] = status
        base["updated_in"] = chapter_index
        loop_map[loop_id] = base

    stage_progress = []
    for row in prev.get("stage_progress", []):
        if isinstance(row, dict):
            stage_progress.append(row)
    for row in inc.get("stage_progress", []):
        if isinstance(row, dict):
            stage_progress.append(row)
    stage_progress.append(
        {
            "chapter": chapter_index,
            "hero_stage": hero_stage,
            "milestone": normalize_text(inc.get("summary_for_next_chapter"))
            or f"第{chapter_index}章推进到阶段{hero_stage}",
        }
    )
    dedup_stage = {}
    for row in stage_progress:
        chapter = clamp_or_default(row.get("chapter"), chapter_index, 1, 9999)
        dedup_stage[chapter] = {
            "chapter": chapter,
            "hero_stage": clamp_or_default(row.get("hero_stage"), hero_stage, 1, 10),
            "milestone": normalize_text(row.get("milestone")),
        }

    return {
        "characters": sorted(merged_chars.values(), key=lambda item: item.get("name", "")),
        "relationships": sorted(relation_map.values(), key=lambda item: (item.get("a", ""), item.get("b", ""), item.get("type", ""))),
        "timeline": dedup_timeline[-240:],
        "world_rules": world_rules[:80],
        "open_loops": sorted(loop_map.values(), key=lambda item: (item.get("status", ""), item.get("updated_in", 0), item.get("id", ""))),
        "stage_progress": [dedup_stage[key] for key in sorted(dedup_stage.keys())][-240:],
        "summary_for_next_chapter": normalize_text(inc.get("summary_for_next_chapter")),
    }


def compact_project_state_for_prompt(state: Optional[Dict], max_chars: int = 2800) -> str:
    normalized = normalize_project_state(state)
    text = json.dumps(normalized, ensure_ascii=False)
    if not text:
        return "（暂无项目状态）"
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "...(truncated)"


def compact_recent_chapters_for_prompt(chapters: List[Dict], max_items: int = 8, max_chars_each: int = 280) -> str:
    if not chapters:
        return "（暂无历史章节）"
    parts = []
    ordered = sorted(chapters, key=lambda item: clamp_or_default(item.get("chapter_index"), 0, 0, 9999))
    for row in ordered[-max_items:]:
        idx = clamp_or_default(row.get("chapter_index"), 0, 0, 9999)
        title = normalize_text(row.get("chapter_title") or row.get("title"))
        summary = normalize_text(row.get("chapter_summary") or row.get("summary"))[:max_chars_each]
        parts.append(f"第{idx}章 {title} | 摘要：{summary}")
    return "\n".join(parts)


def count_effective_chars(text: str) -> int:
    raw = normalize_text(text)
    if not raw:
        return 0
    compact = re.sub(r"\s+", "", raw)
    return len(compact)


def build_length_constraints(target_word_count: int) -> Dict:
    target = clamp_or_default(target_word_count, 3200, 600, 12000)
    min_required = max(900, int(target * 0.82))
    ideal_low = max(min_required, int(target * 0.92))
    return {
        "target": target,
        "min_required": min_required,
        "ideal_low": ideal_low,
    }


def estimate_generation_max_tokens(target_word_count: int, rewrite: bool = False) -> int:
    target = clamp_or_default(target_word_count, 3200, 1200, 12000)
    cushion = 1600 if rewrite else 1300
    estimated = int(target * 1.45) + cushion
    return clamp_int(estimated, 3200, 8192)


def stage_for_chapter(chapter_index: int, total_chapters: int) -> int:
    total = max(1, int(total_chapters or 1))
    idx = clamp_int(chapter_index, 1, total)
    ratio = idx / total
    if ratio <= 0.15:
        return 1
    if ratio <= 0.30:
        return 2
    if ratio <= 0.45:
        return 3
    if ratio <= 0.60:
        return 4
    if ratio <= 0.80:
        return 5
    return 6


def ai_capability_band(hero_stage: int) -> Tuple[int, int]:
    low = clamp_int(hero_stage + 1, 1, 10)
    high = clamp_int(hero_stage + 2, 1, 10)
    return low, max(low, high)


def _tokenize(text: str) -> List[str]:
    text = normalize_text(text).lower()
    en_tokens = re.findall(r"[a-z0-9_]+", text)
    cn_tokens = re.findall(r"[\u4e00-\u9fff]{2,8}", text)
    return en_tokens + cn_tokens


def score_knowledge_item(item: Dict, query: str) -> float:
    query = normalize_text(query)
    if not query:
        return 0.0

    title = normalize_text(item.get("title"))
    content = normalize_text(item.get("content"))
    tags = normalize_text(item.get("tags"))
    haystack = f"{title}\n{tags}\n{content}".lower()
    q = query.lower()
    score = 0.0

    if q in haystack:
        score += 12.0
    if q and title.lower().find(q) >= 0:
        score += 6.0

    query_tokens = _tokenize(query)
    item_tokens = set(_tokenize(haystack))
    for token in query_tokens:
        if token in item_tokens:
            score += 1.2

    if "深度思考" in query and "深度思考" in haystack:
        score += 5.0
    if "第一性原理" in query and "第一性原理" in haystack:
        score += 4.0
    if "主要矛盾" in query and "主要矛盾" in haystack:
        score += 4.0
    return score


def select_knowledge(knowledge_rows: List[Dict], query: str, top_k: int = 6) -> List[Dict]:
    if not knowledge_rows:
        return []
    ranked = []
    for row in knowledge_rows:
        ranked.append((score_knowledge_item(row, query), row))

    ranked.sort(
        key=lambda item: (
            item[0],
            normalize_text(item[1].get("updated_at")),
            normalize_text(item[1].get("created_at")),
        ),
        reverse=True,
    )
    chosen = [item[1] for item in ranked[: max(1, int(top_k or 1))]]
    return chosen


def chunk_text(content: str, max_chars: int = 1600, overlap: int = 120) -> List[str]:
    text = normalize_text(content)
    if not text:
        return []
    if len(text) <= max_chars:
        return [text]

    chunks: List[str] = []
    start = 0
    length = len(text)
    while start < length:
        end = min(length, start + max_chars)
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= length:
            break
        start = max(0, end - overlap)
    return chunks


def parse_agent_model_map(raw) -> Dict[str, str]:
    if isinstance(raw, dict):
        source = raw
    elif isinstance(raw, str):
        text = normalize_text(raw)
        if not text:
            return {}
        try:
            loaded = json.loads(text)
            source = loaded if isinstance(loaded, dict) else {}
        except Exception:
            return {}
    else:
        return {}

    result = {}
    for key, value in source.items():
        model_key = normalize_text(key).lower()
        model_name = normalize_text(value)
        if not model_key or not model_name:
            continue
        result[model_key] = model_name
    return result


def parse_model_list(raw) -> List[str]:
    if isinstance(raw, list):
        items = [normalize_text(item) for item in raw]
    else:
        text = normalize_text(raw)
        if not text:
            return []
        items = [normalize_text(part) for part in re.split(r"[,，\n;；]+", text)]
    return [item for item in items if item]


def compact_knowledge_for_prompt(rows: List[Dict], max_items: int = 6, max_chars_each: int = 900) -> str:
    if not rows:
        return "（无额外知识）"
    parts = []
    for idx, row in enumerate(rows[:max_items], start=1):
        title = normalize_text(row.get("title")) or f"知识片段{idx}"
        tags = normalize_text(row.get("tags"))
        content = normalize_text(row.get("content"))[:max_chars_each]
        parts.append(f"[{idx}] 标题：{title}\n标签：{tags or '无'}\n内容：{content}")
    return "\n\n".join(parts)


def _load_json_object_candidate(candidate: str) -> Dict:
    text = normalize_text(candidate)
    if not text:
        return {}
    normalized_candidates = [text]
    # 兼容常见格式问题：末尾多余逗号
    normalized_candidates.append(re.sub(r",\s*([}\]])", r"\1", text))
    for item in normalized_candidates:
        try:
            loaded = json.loads(item)
            if isinstance(loaded, dict):
                return loaded
        except Exception:
            continue
    return {}


def _extract_json_object_candidates(raw: str, max_candidates: int = 8) -> List[str]:
    if not raw:
        return []

    candidates: List[str] = []
    fenced_matches = re.findall(r"```(?:json|JSON)?\s*([\s\S]*?)```", raw)
    for fenced in fenced_matches:
        candidate = normalize_text(fenced)
        if candidate:
            candidates.append(candidate)
            if len(candidates) >= max_candidates:
                return candidates

    # 扫描自然语言中的 JSON 对象，处理引号和转义，避免花括号误配。
    in_string = False
    escaping = False
    depth = 0
    start_idx = -1
    for idx, ch in enumerate(raw):
        if in_string:
            if escaping:
                escaping = False
            elif ch == "\\":
                escaping = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
            continue
        if ch == "{":
            if depth == 0:
                start_idx = idx
            depth += 1
        elif ch == "}":
            if depth <= 0:
                continue
            depth -= 1
            if depth == 0 and start_idx >= 0:
                candidate = normalize_text(raw[start_idx : idx + 1])
                if candidate:
                    candidates.append(candidate)
                    if len(candidates) >= max_candidates:
                        break
                start_idx = -1
    return candidates


def safe_json_loads(text: str) -> Dict:
    raw = normalize_text(text)
    if not raw:
        return {}

    direct = _load_json_object_candidate(raw)
    if direct:
        return direct

    for candidate in _extract_json_object_candidates(raw):
        loaded = _load_json_object_candidate(candidate)
        if loaded:
            return loaded
    return {}


@dataclass
class LLMCallResult:
    ok: bool
    content: str
    error: str = ""
    meta: Dict = field(default_factory=dict)


class MoonshotClient:
    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.moonshot.cn/v1",
        model: str = "kimi-k2-0905-preview",
        timeout_seconds: float = 120.0,
        top_p: float = 0.95,
        thinking_mode: str = "thinking",
        max_retries: int = 4,
        base_backoff_seconds: float = 1.2,
        min_interval_seconds: float = 0.45,
    ):
        self.api_key = normalize_text(api_key)
        self.base_url = normalize_text(base_url).rstrip("/")
        self.model = normalize_text(model) or "kimi-k2-0905-preview"
        self.timeout_seconds = float(timeout_seconds)
        try:
            self.top_p = float(top_p)
        except Exception:
            self.top_p = 0.95
        self.top_p = max(0.1, min(1.0, self.top_p))
        self.thinking_mode = normalize_text(thinking_mode).lower() or "thinking"
        self.max_retries = clamp_or_default(max_retries, 4, 0, 10)
        try:
            self.base_backoff_seconds = max(0.2, float(base_backoff_seconds))
        except Exception:
            self.base_backoff_seconds = 1.2
        try:
            self.min_interval_seconds = max(0.0, float(min_interval_seconds))
        except Exception:
            self.min_interval_seconds = 0.45
        self._rate_lock = threading.Lock()
        self._last_request_ts = 0.0

    def enabled(self) -> bool:
        return bool(self.api_key)

    def _validate_api_key(self) -> str:
        key = normalize_text(self.api_key)
        if not key:
            return "missing api key"
        try:
            key.encode("ascii")
        except Exception:
            return "invalid api key: contains non-ascii characters"
        if " " in key:
            return "invalid api key: contains whitespace"
        # 非强校验，只做低成本提示，避免把不同格式的合法 key 全拦掉
        if len(key) < 16:
            return "invalid api key: too short"
        return ""

    def _respect_min_interval(self):
        if self.min_interval_seconds <= 0:
            return
        with self._rate_lock:
            now = time.monotonic()
            wait_for = self.min_interval_seconds - (now - self._last_request_ts)
            if wait_for > 0:
                time.sleep(wait_for)
            self._last_request_ts = time.monotonic()

    def _compute_backoff(self, attempt: int, retry_after_header: str = "") -> float:
        retry_after = normalize_text(retry_after_header)
        if retry_after:
            try:
                seconds = float(retry_after)
                if seconds > 0:
                    return min(30.0, seconds)
            except Exception:
                pass
        expo = self.base_backoff_seconds * (2 ** max(0, attempt - 1))
        jitter = random.uniform(0.0, 0.35)
        return min(30.0, expo + jitter)

    def chat(
        self,
        messages: List[Dict],
        temperature: float = 0.7,
        max_tokens: int = 2048,
        model_override: str = "",
        timeout_seconds_override: float = 0.0,
        force_json_object: bool = False,
    ) -> LLMCallResult:
        started_at = time.monotonic()
        if not self.enabled():
            return LLMCallResult(
                ok=False,
                content="",
                error="missing api key",
                meta={"attempts": 0, "retry_count": 0, "duration_ms": 0, "model": normalize_text(model_override) or self.model},
            )
        key_error = self._validate_api_key()
        if key_error:
            return LLMCallResult(
                ok=False,
                content="",
                error=key_error,
                meta={"attempts": 0, "retry_count": 0, "duration_ms": 0, "model": normalize_text(model_override) or self.model},
            )

        model = normalize_text(model_override) or self.model
        try:
            timeout_seconds = float(timeout_seconds_override) if timeout_seconds_override else self.timeout_seconds
        except Exception:
            timeout_seconds = self.timeout_seconds
        timeout_seconds = max(15.0, timeout_seconds)
        base_payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "top_p": self.top_p,
            "max_tokens": max_tokens,
        }
        if self.thinking_mode in {"instant", "non-thinking", "disabled"}:
            base_payload["extra_body"] = {"thinking": {"type": "disabled"}}
        meta = {
            "model": model,
            "timeout_seconds": timeout_seconds,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "attempts": 0,
            "retry_count": 0,
            "retries": [],
            "request_id": "",
            "last_status_code": 0,
        }
        last_error = ""

        def _finish(ok: bool, content: str = "", error: str = "") -> LLMCallResult:
            meta["retry_count"] = len(meta.get("retries", []))
            meta["duration_ms"] = int((time.monotonic() - started_at) * 1000)
            if error:
                meta["last_error"] = normalize_text(error)[:420]
            return LLMCallResult(ok=ok, content=content, error=error, meta=meta)

        for attempt in range(1, self.max_retries + 2):
            meta["attempts"] = attempt
            self._respect_min_interval()
            payload = dict(base_payload)
            if force_json_object:
                payload["response_format"] = {"type": "json_object"}
            req = Request(
                f"{self.base_url}/chat/completions",
                method="POST",
                data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
            )
            try:
                with urlopen(req, timeout=timeout_seconds) as resp:
                    body = resp.read().decode("utf-8", errors="ignore")
                    data = json.loads(body or "{}")
                    meta["request_id"] = normalize_text(resp.headers.get("x-request-id") or resp.headers.get("request-id"))
                    status = getattr(resp, "status", 200)
                    meta["last_status_code"] = int(status) if status is not None else 200
                try:
                    message = data["choices"][0]["message"]
                    content = message.get("content", "")
                    if isinstance(content, list):
                        merged = []
                        for item in content:
                            if isinstance(item, dict) and item.get("type") == "text":
                                merged.append(item.get("text", ""))
                        content = "\n".join(merged).strip()
                    return _finish(ok=True, content=str(content), error="")
                except Exception as exc:
                    last_error = f"bad response format: {exc}"
                    if attempt <= self.max_retries:
                        delay = self._compute_backoff(attempt)
                        meta["retries"].append(
                            {
                                "attempt": attempt,
                                "reason": "bad_response_format",
                                "status_code": meta.get("last_status_code", 0),
                                "delay_seconds": round(delay, 3),
                            }
                        )
                        time.sleep(delay)
                        continue
                    return _finish(ok=False, error=last_error)
            except HTTPError as exc:
                body = ""
                try:
                    body = exc.read().decode("utf-8", errors="ignore")
                except Exception:
                    body = ""
                last_error = f"HTTP {exc.code}: {body[:360]}".strip()
                meta["last_status_code"] = int(exc.code)
                if force_json_object and exc.code == 400:
                    lowered = normalize_text(body).lower()
                    if "response_format" in lowered and ("unsupported" in lowered or "invalid" in lowered or "not support" in lowered):
                        force_json_object = False
                        if attempt <= self.max_retries:
                            delay = self._compute_backoff(attempt)
                            meta["retries"].append(
                                {
                                    "attempt": attempt,
                                    "reason": "response_format_unsupported",
                                    "status_code": int(exc.code),
                                    "delay_seconds": round(delay, 3),
                                }
                            )
                            time.sleep(delay)
                            continue
                retryable = exc.code in {408, 429, 500, 502, 503, 504}
                if retryable and attempt <= self.max_retries:
                    delay = self._compute_backoff(attempt, exc.headers.get("Retry-After", ""))
                    meta["retries"].append(
                        {
                            "attempt": attempt,
                            "reason": f"http_{exc.code}",
                            "status_code": int(exc.code),
                            "delay_seconds": round(delay, 3),
                        }
                    )
                    time.sleep(delay)
                    continue
                return _finish(ok=False, error=last_error or str(exc))
            except json.JSONDecodeError as exc:
                last_error = f"json decode error: {exc}"
                if attempt <= self.max_retries:
                    delay = self._compute_backoff(attempt)
                    meta["retries"].append(
                        {
                            "attempt": attempt,
                            "reason": "json_decode_error",
                            "status_code": meta.get("last_status_code", 0),
                            "delay_seconds": round(delay, 3),
                        }
                    )
                    time.sleep(delay)
                    continue
                return _finish(ok=False, error=last_error)
            except (URLError, TimeoutError) as exc:
                last_error = str(exc)
                if attempt <= self.max_retries:
                    delay = self._compute_backoff(attempt)
                    meta["retries"].append(
                        {
                            "attempt": attempt,
                            "reason": "network_error",
                            "status_code": meta.get("last_status_code", 0),
                            "delay_seconds": round(delay, 3),
                        }
                    )
                    time.sleep(delay)
                    continue
                return _finish(ok=False, error=last_error)
            except socket.timeout as exc:
                last_error = str(exc) or "socket timeout"
                if attempt <= self.max_retries:
                    delay = self._compute_backoff(attempt)
                    meta["retries"].append(
                        {
                            "attempt": attempt,
                            "reason": "socket_timeout",
                            "status_code": meta.get("last_status_code", 0),
                            "delay_seconds": round(delay, 3),
                        }
                    )
                    time.sleep(delay)
                    continue
                return _finish(ok=False, error=last_error)
            except Exception as exc:
                last_error = str(exc)
                lowered = last_error.lower()
                if ("timed out" in lowered or "timeout" in lowered) and attempt <= self.max_retries:
                    delay = self._compute_backoff(attempt)
                    meta["retries"].append(
                        {
                            "attempt": attempt,
                            "reason": "timeout_error",
                            "status_code": meta.get("last_status_code", 0),
                            "delay_seconds": round(delay, 3),
                        }
                    )
                    time.sleep(delay)
                    continue
                return _finish(ok=False, error=last_error)

        return _finish(ok=False, error=last_error or "empty response after retries")


class NovelAgentOrchestrator:
    def __init__(self, llm_client: MoonshotClient):
        self.llm = llm_client
        self.fast_retry_enabled = to_bool(os.getenv("NOVEL_FAST_RETRY_ENABLED", "0"), False)

    def _resolve_agent_model(self, ctx: Dict, agent_name: str, fallback: str = "") -> str:
        model_map = ctx.get("agentModelMap") if isinstance(ctx, dict) else {}
        if isinstance(model_map, dict):
            key = normalize_text(agent_name).lower()
            model = normalize_text(model_map.get(key))
            if model:
                return model
        return normalize_text(fallback) or self.llm.model

    def _attempt_json_repair(
        self,
        agent_name: str,
        raw_text: str,
        fallback_payload: Dict,
        model_override: str,
        timeout_seconds_override: float,
    ) -> Tuple[Optional[Dict], Dict]:
        trace = {"attempted": False, "steps": []}
        raw = normalize_text(raw_text)
        if not raw or not self.llm.enabled():
            return None, trace

        trace["attempted"] = True
        schema_hint = json.dumps(fallback_payload if isinstance(fallback_payload, dict) else {}, ensure_ascii=False)[:1800]
        repair_rounds = [
            {
                "name": "repair_primary",
                "system": "你是JSON修复器。把输入改写成一个合法JSON对象。只能输出JSON对象，不要解释。",
                "user": (
                    f"目标agent：{agent_name}\n"
                    "请把下面内容转换为合法JSON对象，保留关键信息并尽量匹配参考结构。\n"
                    f"参考结构：{schema_hint}\n"
                    f"原始内容：\n{compact_text(raw, 5200)}"
                ),
                "max_tokens": 2200,
            }
        ]
        if self.fast_retry_enabled:
            repair_rounds.append(
                {
                    "name": "repair_strict",
                    "system": "只允许输出单个 JSON 对象。不能有 markdown、注释、解释、前后缀文本。",
                    "user": (
                        f"agent={agent_name}\n"
                        f"schema={schema_hint}\n"
                        f"input={compact_text(raw, 3600)}\n"
                        "返回一个合法 JSON 对象。"
                    ),
                    "max_tokens": 1700,
                }
            )
        for cfg in repair_rounds:
            repair_result = self.llm.chat(
                messages=[
                    {"role": "system", "content": cfg["system"]},
                    {"role": "user", "content": cfg["user"]},
                ],
                temperature=0.0,
                max_tokens=cfg["max_tokens"],
                model_override=model_override,
                timeout_seconds_override=max(18.0, min(45.0, float(timeout_seconds_override or self.llm.timeout_seconds))),
                force_json_object=True,
            )
            step = {
                "name": cfg["name"],
                "ok": bool(repair_result.ok),
                "error": normalize_text(repair_result.error),
                "call_meta": repair_result.meta if isinstance(repair_result.meta, dict) else {},
            }
            if repair_result.ok:
                parsed = safe_json_loads(repair_result.content)
                if isinstance(parsed, dict) and parsed:
                    step["parsed"] = True
                    trace["steps"].append(step)
                    return parsed, trace
                step["parsed"] = False
            trace["steps"].append(step)
        return None, trace

    def _build_fast_retry_messages(
        self,
        agent_name: str,
        system_prompt: str,
        user_prompt: str,
        fallback_payload: Dict,
        error_hint: str,
    ) -> Tuple[str, str]:
        schema_hint = json.dumps(fallback_payload if isinstance(fallback_payload, dict) else {}, ensure_ascii=False)[:1500]
        fast_system = (
            f"{compact_text(system_prompt, 900)}\n"
            "你必须只输出一个合法 JSON 对象，不得输出解释、markdown、代码块。"
        )
        fast_user = (
            f"agent={agent_name}\n"
            f"失败原因={compact_text(error_hint or 'unknown', 280)}\n"
            f"任务（压缩）={compact_text(user_prompt, 2800)}\n"
            f"参考结构={schema_hint}\n"
            "请直接返回合法 JSON 对象。"
        )
        return fast_system, fast_user

    def _classify_model_error(self, error_text: str) -> str:
        text = normalize_text(error_text).lower()
        if not text:
            return "none"
        if "llm disabled" in text or "missing api key" in text:
            return "disabled"
        if "non-json" in text or "bad response format" in text or "json" in text:
            return "non_json"
        if "429" in text or "rate limit" in text or "too many requests" in text:
            return "rate_limit"
        if "timeout" in text or "timed out" in text or "socket timeout" in text:
            return "timeout"
        if "503" in text or "502" in text or "504" in text or "temporarily unavailable" in text:
            return "transient_server"
        if "401" in text or "403" in text or "invalid api key" in text:
            return "auth"
        return "other"

    def _summarize_invoke_trace(self, invoke_trace: List[Dict]) -> Dict:
        attempts = 0
        retry_count = 0
        duration_ms = 0
        status_codes = []
        request_ids = []
        for row in invoke_trace:
            if not isinstance(row, dict):
                continue
            meta = row.get("call_meta")
            if not isinstance(meta, dict):
                continue
            attempts += clamp_or_default(meta.get("attempts"), 0, 0, 100)
            retry_count += clamp_or_default(meta.get("retry_count"), 0, 0, 100)
            duration_ms += clamp_or_default(meta.get("duration_ms"), 0, 0, 999999)
            code = clamp_or_default(meta.get("last_status_code"), 0, 0, 999)
            if code:
                status_codes.append(code)
            request_id = normalize_text(meta.get("request_id"))
            if request_id:
                request_ids.append(request_id)
        return {
            "steps": len(invoke_trace),
            "attempts": attempts,
            "retry_count": retry_count,
            "duration_ms": duration_ms,
            "status_codes": status_codes[:12],
            "request_ids": request_ids[:8],
        }

    def _invoke_agent(
        self,
        agent_name: str,
        system_prompt: str,
        user_prompt: str,
        fallback_payload: Dict,
        temperature: float = 0.7,
        max_tokens: int = 2048,
        model_override: str = "",
        timeout_seconds_override: float = 0.0,
    ) -> Dict:
        used_model = normalize_text(model_override) or self.llm.model
        invoke_trace: List[Dict] = []

        def push_trace(phase: str, result: LLMCallResult, parsed: bool = False):
            invoke_trace.append(
                {
                    "phase": phase,
                    "ok": bool(result.ok),
                    "parsed": bool(parsed),
                    "error": normalize_text(result.error),
                    "call_meta": result.meta if isinstance(result.meta, dict) else {},
                }
            )

        def push_repair_trace(prefix: str, repair_trace: Dict):
            steps = repair_trace.get("steps") if isinstance(repair_trace, dict) else []
            if not isinstance(steps, list):
                return
            for step in steps:
                if not isinstance(step, dict):
                    continue
                invoke_trace.append(
                    {
                        "phase": f"{prefix}:{normalize_text(step.get('name')) or 'repair'}",
                        "ok": bool(step.get("ok")),
                        "parsed": bool(step.get("parsed")),
                        "error": normalize_text(step.get("error")),
                        "call_meta": step.get("call_meta") if isinstance(step.get("call_meta"), dict) else {},
                    }
                )

        def build_result(
            payload: Dict,
            fallback: bool,
            error: str,
            raw: str = "",
            repaired: bool = False,
            recovered: bool = False,
        ) -> Dict:
            return {
                "agent": agent_name,
                "model": used_model,
                "payload": payload,
                "fallback": fallback,
                "repaired": repaired,
                "recovered": recovered,
                "error": error,
                "error_class": self._classify_model_error(error),
                "raw": raw,
                "call_meta": self._summarize_invoke_trace(invoke_trace),
                "invoke_trace": invoke_trace[:16],
            }

        if not self.llm.enabled():
            return build_result(payload=fallback_payload, fallback=True, error="llm disabled", raw="")

        result = self.llm.chat(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=temperature,
            max_tokens=max_tokens,
            model_override=used_model,
            timeout_seconds_override=timeout_seconds_override,
            force_json_object=True,
        )
        push_trace("primary", result, parsed=False)

        if result.ok:
            parsed = safe_json_loads(result.content)
            if parsed:
                invoke_trace[-1]["parsed"] = True
                return build_result(payload=parsed, fallback=False, error="", raw=result.content)

            repaired, repair_trace = self._attempt_json_repair(
                agent_name=agent_name,
                raw_text=result.content,
                fallback_payload=fallback_payload,
                model_override=used_model,
                timeout_seconds_override=timeout_seconds_override,
            )
            push_repair_trace("primary", repair_trace)
            if isinstance(repaired, dict) and repaired:
                return build_result(payload=repaired, fallback=False, error="", raw=result.content, repaired=True)

            if self.fast_retry_enabled:
                fast_system, fast_user = self._build_fast_retry_messages(
                    agent_name=agent_name,
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    fallback_payload=fallback_payload,
                    error_hint=f"{agent_name} returned non-json response",
                )
                retry_result = self.llm.chat(
                    messages=[
                        {"role": "system", "content": fast_system},
                        {"role": "user", "content": fast_user},
                    ],
                    temperature=min(0.35, max(0.0, float(temperature))),
                    max_tokens=max(600, min(int(max_tokens), 1800)),
                    model_override=used_model,
                    timeout_seconds_override=max(12.0, min(28.0, float(timeout_seconds_override or self.llm.timeout_seconds) * 0.9)),
                    force_json_object=True,
                )
                push_trace("fast_retry_non_json", retry_result, parsed=False)
                if retry_result.ok:
                    parsed_retry = safe_json_loads(retry_result.content)
                    if parsed_retry:
                        invoke_trace[-1]["parsed"] = True
                        return build_result(payload=parsed_retry, fallback=False, error="", raw=retry_result.content, recovered=True)
                    repaired_retry, repair_trace_retry = self._attempt_json_repair(
                        agent_name=agent_name,
                        raw_text=retry_result.content,
                        fallback_payload=fallback_payload,
                        model_override=used_model,
                        timeout_seconds_override=timeout_seconds_override,
                    )
                    push_repair_trace("fast_retry_non_json", repair_trace_retry)
                    if isinstance(repaired_retry, dict) and repaired_retry:
                        return build_result(
                            payload=repaired_retry,
                            fallback=False,
                            error="",
                            raw=retry_result.content,
                            repaired=True,
                            recovered=True,
                        )
            else:
                retry_result = LLMCallResult(ok=False, content="", error="")
            combined = f"{agent_name} returned non-json response"
            retry_error = normalize_text(retry_result.error)
            if retry_error:
                combined = f"{combined} | retry: {retry_error}"
            return build_result(payload=fallback_payload, fallback=True, error=combined, raw=result.content)

        primary_error = normalize_text(result.error)
        if self.fast_retry_enabled and self._is_transient_model_error(primary_error):
            fast_system, fast_user = self._build_fast_retry_messages(
                agent_name=agent_name,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                fallback_payload=fallback_payload,
                error_hint=primary_error,
            )
            retry_result = self.llm.chat(
                messages=[
                    {"role": "system", "content": fast_system},
                    {"role": "user", "content": fast_user},
                ],
                temperature=min(0.35, max(0.0, float(temperature))),
                max_tokens=max(600, min(int(max_tokens), 1800)),
                model_override=used_model,
                timeout_seconds_override=max(12.0, min(28.0, float(timeout_seconds_override or self.llm.timeout_seconds) * 0.9)),
                force_json_object=True,
            )
            push_trace("fast_retry_transient", retry_result, parsed=False)
            if retry_result.ok:
                parsed_retry = safe_json_loads(retry_result.content)
                if parsed_retry:
                    invoke_trace[-1]["parsed"] = True
                    return build_result(payload=parsed_retry, fallback=False, error="", raw=retry_result.content, recovered=True)
                repaired_retry, repair_trace_retry = self._attempt_json_repair(
                    agent_name=agent_name,
                    raw_text=retry_result.content,
                    fallback_payload=fallback_payload,
                    model_override=used_model,
                    timeout_seconds_override=timeout_seconds_override,
                )
                push_repair_trace("fast_retry_transient", repair_trace_retry)
                if isinstance(repaired_retry, dict) and repaired_retry:
                    return build_result(
                        payload=repaired_retry,
                        fallback=False,
                        error="",
                        raw=retry_result.content,
                        repaired=True,
                        recovered=True,
                    )
            retry_error = normalize_text(retry_result.error)
            combined_error = primary_error
            if retry_error:
                combined_error = f"{primary_error} | retry: {retry_error}" if primary_error else retry_error
            return build_result(payload=fallback_payload, fallback=True, error=combined_error or "transient model error", raw="")

        return build_result(payload=fallback_payload, fallback=True, error=primary_error or "llm invoke failed", raw="")

    def _raise_if_strict_fallback(self, strict_llm: bool, agent_name: str, result: Dict, allow_transient: bool = False):
        if not strict_llm:
            return
        if not isinstance(result, dict):
            raise RuntimeError(f"{agent_name} 返回格式异常")
        if not bool(result.get("fallback")):
            return
        reason = normalize_text(result.get("error")) or "agent fallback"
        if allow_transient and self._is_transient_model_error(reason):
            return
        raise RuntimeError(f"{agent_name} 使用 Kimi 失败：{reason}")

    def _is_transient_model_error(self, error_text: str) -> bool:
        text = normalize_text(error_text).lower()
        if not text:
            return False
        keywords = [
            "429",
            "503",
            "502",
            "504",
            "timeout",
            "timed out",
            "connection reset",
            "temporarily unavailable",
            "temporarily overloaded",
            "bad gateway",
            "rate limit",
            "too many requests",
            "non-json response",
            "returned non-json",
        ]
        return any(key in text for key in keywords)

    def _build_model_route_plan(self, ctx: Dict, deep_primary_model: str, deep_secondary_model: str, deep_referee_model: str) -> Dict:
        return {
            "framework": self._resolve_agent_model(ctx, "framework"),
            "character": self._resolve_agent_model(ctx, "character"),
            "scene": self._resolve_agent_model(ctx, "scene"),
            "deep_primary": deep_primary_model,
            "deep_secondary": deep_secondary_model,
            "deep_referee": deep_referee_model,
            "writer": self._resolve_agent_model(ctx, "writer"),
            "qa": self._resolve_agent_model(ctx, "qa"),
            "memory_extractor": self._resolve_agent_model(ctx, "memory_extractor"),
            "chapter_logic_audit": self._resolve_agent_model(ctx, "chapter_logic_audit"),
            "global_logic_audit": self._resolve_agent_model(ctx, "global_logic_audit"),
            "deep_quality_audit": self._resolve_agent_model(
                ctx,
                "deep_quality_audit",
                self._resolve_agent_model(ctx, "deep_referee"),
            ),
            "rewrite": self._resolve_agent_model(ctx, "rewrite", self._resolve_agent_model(ctx, "writer")),
        }

    def _build_model_observability(self, route_plan: Dict, agent_bundle: Dict, rewrite_trace: List[Dict]) -> Dict:
        agent_calls = []
        fallback_count = 0
        repaired_count = 0
        recovered_count = 0
        transient_count = 0
        total_attempts = 0
        total_retries = 0
        total_duration_ms = 0
        for name, value in (agent_bundle or {}).items():
            if not isinstance(value, dict):
                continue
            if name == "rewrite_rounds":
                continue
            error = normalize_text(value.get("error"))
            error_class = normalize_text(value.get("error_class")) or self._classify_model_error(error)
            call_meta = value.get("call_meta") if isinstance(value.get("call_meta"), dict) else {}
            attempts = clamp_or_default(call_meta.get("attempts"), 0, 0, 999)
            retries = clamp_or_default(call_meta.get("retry_count"), 0, 0, 999)
            duration = clamp_or_default(call_meta.get("duration_ms"), 0, 0, 999999)
            total_attempts += attempts
            total_retries += retries
            total_duration_ms += duration
            fallback = bool(value.get("fallback"))
            repaired = bool(value.get("repaired"))
            recovered = bool(value.get("recovered"))
            if fallback:
                fallback_count += 1
            if repaired:
                repaired_count += 1
            if recovered:
                recovered_count += 1
            if self._is_transient_model_error(error):
                transient_count += 1
            agent_calls.append(
                {
                    "agent": name,
                    "route_model": normalize_text(route_plan.get(name)) or normalize_text(value.get("model")),
                    "actual_model": normalize_text(value.get("model")),
                    "fallback": fallback,
                    "repaired": repaired,
                    "recovered": recovered,
                    "error_class": error_class,
                    "error": error[:300],
                    "attempts": attempts,
                    "retries": retries,
                    "duration_ms": duration,
                    "status_codes": call_meta.get("status_codes") if isinstance(call_meta.get("status_codes"), list) else [],
                }
            )
        return {
            "route_plan": route_plan,
            "summary": {
                "agent_count": len(agent_calls),
                "fallback_count": fallback_count,
                "repaired_count": repaired_count,
                "recovered_count": recovered_count,
                "transient_error_count": transient_count,
                "total_attempts": total_attempts,
                "total_retries": total_retries,
                "total_duration_ms": total_duration_ms,
            },
            "agent_calls": agent_calls,
            "rewrite_trace": rewrite_trace[:8],
        }

    def _base_context(self, req: Dict) -> Dict:
        chapter_index = clamp_int(req.get("chapterIndex", 1), 1, 999)
        total_chapters = clamp_int(req.get("totalChapters", 20), 1, 999)
        hero_stage = stage_for_chapter(chapter_index, total_chapters)
        ai_low, ai_high = ai_capability_band(hero_stage)
        student_profile = normalize_student_profile(req.get("studentProfile"))
        routing_strategy = build_routing_strategy(
            profile=student_profile,
            hero_stage=hero_stage,
            chapter_index=chapter_index,
            total_chapters=total_chapters,
        )
        project_state = normalize_project_state(req.get("projectState"))
        recent_chapters = req.get("recentChapters") if isinstance(req.get("recentChapters"), list) else []
        previous_summary = normalize_text(req.get("previousSummary"))
        if not previous_summary:
            previous_summary = normalize_text(project_state.get("summary_for_next_chapter"))
        target_word_count = clamp_or_default(req.get("targetWordCount", 3200), 3200, 1200, 12000)
        min_word_count = clamp_or_default(req.get("minWordCount", int(target_word_count * 0.82)), int(target_word_count * 0.82), 900, 12000)
        detail_density = clamp_or_default(req.get("detailDensity", 8), 8, 1, 10)
        timeout_base = clamp_or_default(req.get("moonshotTimeoutSeconds", 75), 75, 20, 600)
        outline_timeout = clamp_or_default(req.get("outlineTimeoutSeconds", int(timeout_base * 1.4)), int(timeout_base * 1.4), 40, 900)
        writer_timeout = clamp_or_default(req.get("writerTimeoutSeconds", int(timeout_base * 1.1)), int(timeout_base * 1.1), 35, 900)
        agent_timeout = clamp_or_default(req.get("agentTimeoutSeconds", int(timeout_base * 0.85)), int(timeout_base * 0.85), 25, 600)
        agent_model_map = parse_agent_model_map(req.get("agentModelMap"))
        deep_committee_models = parse_model_list(req.get("deepCommitteeModels"))
        if not deep_committee_models:
            deep_primary = normalize_text(agent_model_map.get("deep_primary")) or normalize_text(agent_model_map.get("deep"))
            deep_secondary = normalize_text(agent_model_map.get("deep_secondary"))
            deep_referee = normalize_text(agent_model_map.get("deep_referee"))
            deep_committee_models = [item for item in [deep_primary, deep_secondary, deep_referee] if item]
        if not deep_committee_models:
            deep_committee_models = [self.llm.model]
        multi_model_collab = to_bool(req.get("multiModelCollab"), True)
        first_layer_workers = clamp_or_default(req.get("firstLayerWorkers", 2), 2, 1, 4)
        return {
            "projectName": normalize_text(req.get("projectName")) or "未命名项目",
            "premise": compact_text(normalize_text(req.get("premise")), 4800),
            "chapterIndex": chapter_index,
            "totalChapters": total_chapters,
            "heroStage": hero_stage,
            "heroStageDesc": STAGE_DEFINITIONS.get(hero_stage, ""),
            "aiBandLow": ai_low,
            "aiBandHigh": ai_high,
            "protagonistProfile": compact_text(normalize_text(req.get("protagonistProfile")), 1200),
            "aiProfile": compact_text(normalize_text(req.get("aiProfile")), 1200)
            or (
                "深瞳：毒舌导师型AI，核心任务是训练主角深度思考，"
                "不会直接给终局答案，会逼主角自己突破。"
            ),
            "studentProfile": student_profile,
            "routingStrategy": routing_strategy,
            "writingStyle": normalize_text(req.get("writingStyle")) or "现实向热血爽文",
            "previousSummary": previous_summary,
            "projectState": project_state,
            "recentChapters": recent_chapters[-40:],
            "deepThinkingCard": compact_text(normalize_text(req.get("deepThinkingCard")), 3200) or DEFAULT_DEEP_THINKING_CARD,
            "energyBefore": clamp_int(req.get("energyBefore", 0), 0, 100000),
            "targetWordCount": target_word_count,
            "minWordCount": min(min_word_count, target_word_count),
            "detailDensity": detail_density,
            "agentModelMap": agent_model_map,
            "deepCommitteeModels": deep_committee_models[:3],
            "multiModelCollab": multi_model_collab,
            "firstLayerWorkers": first_layer_workers,
            "timeoutBaseSeconds": timeout_base,
            "outlineTimeoutSeconds": outline_timeout,
            "writerTimeoutSeconds": writer_timeout,
            "agentTimeoutSeconds": agent_timeout,
        }

    def _fallback_framework(self, ctx: Dict) -> Dict:
        return {
            "chapter_goal": f"第{ctx['chapterIndex']}章：主角在学习与尊严冲突中第一次主动做选择",
            "core_conflict": "按学校旧流程死学 vs 以深度思考做高效突破",
            "cool_points": [
                "在同学质疑中公开展示新方法效果",
                "短时间可见进步，形成打脸反差",
                "结尾抛出更高难度挑战",
            ],
            "plot_beats": [
                "触发：被嘲讽/被否定",
                "对抗：深瞳逼主角提出白痴问题并拆解",
                "反转：主角放弃低效作业，腾出核心时间",
                "兑现：阶段性成绩爆发",
                "钩子：新敌对关系升级",
            ],
        }

    def _fallback_character(self, ctx: Dict) -> Dict:
        return {
            "current_fear": "害怕被老师和同学否定，害怕一旦特立独行就彻底失败",
            "ego_mask": "用拖延和自嘲掩饰无力感",
            "breakthrough_choice": "顶着压力，第一次主动放弃无效作业并自建学习节奏",
            "emotion_curve": ["羞耻", "犹豫", "被激怒", "专注", "小胜后的克制兴奋"],
            "dialogue_tone": "主角前半段怂、后半段更坚定，语言逐步有主见",
        }

    def _fallback_deep(self, ctx: Dict) -> Dict:
        base_gain = 30 + ctx["heroStage"] * 8
        return {
            "white_question": "我为什么要把所有作业都做完，真的每一份都指向提分吗？",
            "five_whys": [
                "为什么成绩起不来？因为时间被低价值任务吃掉。",
                "为什么会被吃掉？因为不敢违背权威安排。",
                "为什么不敢违背？因为害怕被评价为不努力。",
                "为什么怕评价？因为把自我价值绑定在外界认可。",
                "为什么要外界认可？因为内心没有主体性和安全感。",
            ],
            "primary_contradiction": "有限时间与低效执行之间的矛盾",
            "first_principles": ["时间是稀缺资源", "记忆效率取决于可理解性与检索次数", "提分取决于高频高价值知识点命中"],
            "task_for_hero": "当天完成一轮词根拆解+语境阅读，并记录3条可复用规律",
            "task_metrics": ["单词回忆正确率>=75%", "当天输出3条可迁移方法", "次日抽查复现率>=70%"],
            "anti_self_deception": ["不许只抄笔记不实操", "不许拿努力感替代结果验证"],
            "energy_gain_suggestion": clamp_int(base_gain, 18, 95),
            "ai_upgrade_hint": "当主角能独立找到主要矛盾时，深瞳解锁更强题目拆解能力",
        }

    def _fallback_deep_consensus(self, primary: Dict, secondary: Dict) -> Dict:
        p = primary if isinstance(primary, dict) else {}
        s = secondary if isinstance(secondary, dict) else {}
        winner = p if len(p.get("five_whys", []) if isinstance(p.get("five_whys"), list) else []) >= len(
            s.get("five_whys", []) if isinstance(s.get("five_whys"), list) else []
        ) else s
        payload = dict(winner)
        payload.setdefault("task_metrics", ["完成一次可验证实操并复盘"])
        payload.setdefault("anti_self_deception", ["避免空谈，要有结果证据"])
        payload["consensus_notes"] = "由双模型深度思考结果融合，优先保留可执行与可验证部分。"
        return payload

    def _build_deep_consensus_prompts(self, ctx: Dict, primary: Dict, secondary: Dict) -> Tuple[str, str]:
        system_prompt = "你是深度思考总裁判，负责融合两份推理并去伪存真。只输出 JSON。"
        user_prompt = (
            f"项目：{ctx['projectName']}\n"
            f"章节：第{ctx['chapterIndex']}/{ctx['totalChapters']}章\n"
            f"深度思考卡：{ctx['deepThinkingCard']}\n"
            "任务：融合两份深度思考方案，输出最强版本。要求：\n"
            "1) 必须给出>=5层 why 链路；\n"
            "2) 必须明确主要矛盾且可映射到本章行动；\n"
            "3) 给出至少3条第一性原理；\n"
            "4) 给出可量化任务指标，避免空泛鸡汤。\n"
            f"候选A：{json.dumps(primary, ensure_ascii=False)}\n"
            f"候选B：{json.dumps(secondary, ensure_ascii=False)}\n"
            "输出 JSON 键：white_question, five_whys(数组), primary_contradiction, first_principles(数组), "
            "task_for_hero, task_metrics(数组), anti_self_deception(数组), energy_gain_suggestion, "
            "ai_upgrade_hint, consensus_notes。"
        )
        return system_prompt, user_prompt

    def _fallback_scene(self, ctx: Dict) -> Dict:
        return {
            "time_space": "高三晚自习后到夜间自习室",
            "environment_trigger": "班级月考排名张贴引发集体焦虑",
            "supporting_roles": [
                "班主任：代表旧秩序压力",
                "学霸同桌：代表结果导向与怀疑",
                "校花：代表新的关系线与价值确认",
            ],
            "pacing_notes": ["前30%压迫感", "中段高强度对话与推理", "后段用结果反转并留钩子"],
        }

    def _expand_fallback_chapter_text(self, ctx: Dict, merged: Dict, base_text: str) -> str:
        text = normalize_text(base_text)
        if not text:
            return text

        length_constraints = build_length_constraints(ctx.get("targetWordCount", 3200))
        min_required = length_constraints.get("min_required", 1800)
        if count_effective_chars(text) >= min_required:
            return text

        deep_payload = merged.get("deep") if isinstance(merged.get("deep"), dict) else {}
        scene_payload = merged.get("scene") if isinstance(merged.get("scene"), dict) else {}
        framework_payload = merged.get("framework") if isinstance(merged.get("framework"), dict) else {}
        character_payload = merged.get("character") if isinstance(merged.get("character"), dict) else {}

        white_question = normalize_text(deep_payload.get("white_question")) or "我到底在为谁学习"
        primary_contradiction = normalize_text(deep_payload.get("primary_contradiction")) or "求稳依赖与主动选择之间的冲突"
        chapter_goal = normalize_text(framework_payload.get("chapter_goal")) or "在一次公开压力场中完成主动突破"
        current_fear = normalize_text(character_payload.get("current_fear")) or "害怕被否定"
        time_space = normalize_text(scene_payload.get("time_space")) or "晚自习后的教室与走廊"

        expansion_blocks = [
            (
                f"第二轮晚自习开始前，林渊把自己的复盘本摊开，按“现象-本质-行动-反馈”四栏重写。"
                f"他把今天最刺痛自己的场景写成一句话：在{time_space}里，自己听到嘲笑就想退回旧轨道。"
                f"深瞳没有安慰，只让他把{current_fear}拆成可验证命题："
                f"“如果你继续迎合所有人，七天后分数会怎样；如果你按新策略执行，七天后会怎样？”"
                f"林渊第一次把情绪问题转成实验问题，手抖着写下对照组与实验组。"
            ),
            (
                f"走廊尽头的风很冷，林渊盯着本子上的{white_question}。"
                f"他继续往下追问，直到看见真正卡点并不是“记不住”，而是“怕显得不合群”。"
                f"深瞳把这句圈出来，直接下结论：这就是你本章的主要矛盾——{primary_contradiction}。"
                f"“你不是不会学，你是不敢选。”这句话像钉子一样钉进他脑子。"
            ),
            (
                "第三天小测前，林渊把英语和数学错题各挑了十道，按知识点最小单元重组。"
                "英语只抓高频词根与语境映射，数学只抓函数单调性和导数符号链，不再泛刷。"
                "他给自己定了硬指标：每道题必须写出“为什么这一步成立”，写不出就判定为没学会。"
                "这让进度一开始变慢，但错误率在当晚就出现拐点。"
            ),
            (
                "第四天中午，班主任把他叫到办公室。林渊照旧礼貌、克制，但这次不再用“我会努力”糊弄，"
                "而是递上一页策略看板：主要矛盾、单点歼灭计划、每日验证数据。"
                "老师先是皱眉，随后问了三个细节问题。林渊一一回答，甚至承认自己方案里两处可能失败点。"
                "办公室气氛从质疑慢慢变成了观察，这种变化让他第一次体会到“用结果争取自由度”。"
            ),
            (
                f"到周测当天，林渊按{chapter_goal}把节奏压到极致：先拿稳基础分，再冲中档题，最后留十分钟总复盘。"
                "出成绩那刻，提升幅度还不算夸张，却足够打破“他只会嘴硬”的标签。"
                "更关键的是，他在复盘里写下：真正有效的不是某个技巧，而是每次都回到本质，"
                "用可验证行动去替代情绪化自证。深瞳只回了四个字：“继续加码。”"
            ),
        ]

        idx = 0
        while count_effective_chars(text) < min_required and idx < len(expansion_blocks):
            text += "\n\n" + expansion_blocks[idx]
            idx += 1

        tail_idx = 1
        while count_effective_chars(text) < min_required and tail_idx <= 4:
            text += (
                "\n\n"
                f"【阶段复盘{tail_idx}】林渊把当日行动写成闭环：问题定义、主要矛盾、最小行动、结果验证、明日修正。"
                "他要求自己每一步都可复查，不再允许“我感觉我很努力”这种空话。"
            )
            tail_idx += 1
        return text

    def _fallback_writer(self, ctx: Dict, merged: Dict) -> Dict:
        fw = merged["framework"]
        ch = merged["character"]
        dp = merged["deep"]
        sc = merged["scene"]
        gain = clamp_or_default(dp.get("energy_gain_suggestion", 38), 38, 10, 120)
        energy_after = ctx["energyBefore"] + gain
        ai_level = clamp_int(ctx["heroStage"] + 1 + energy_after // 220, 1, 10)

        content = (
            f"晚自习铃声落下时，林渊盯着黑板角落里那张月考排名，手心全是汗。"
            f"他知道自己又在下游。{sc['environment_trigger']}像一把锤子，把他上一世那种“努力却无用”的羞耻感全砸醒。\n\n"
            f"“废物，你又准备靠抄作业麻醉自己？”深瞳的声音在脑海里炸开。"
            f"林渊下意识想反驳，却只挤出一句：“不跟着老师走，我会死得更快。”\n\n"
            f"深瞳冷笑：“那就先问一个白痴问题：{dp['white_question']}”"
            f"林渊沉默了十几秒，第一次没有急着找借口，而是拿笔写下五层追问。"
            f"写到最后，他盯着结论发呆：自己怕的不是学习，而是被人说“不合群”。\n\n"
            f"“主要矛盾是什么？”深瞳逼问。"
            f"“是时间不够，不是我不够苦。”林渊抬起头，喉咙发紧，“我把时间浪费在低价值任务上了。”\n\n"
            f"那晚他做了一个以前绝不敢做的选择：把三份机械抄写作业直接砍掉，"
            f"腾出九十分钟只做词根拆解和英文短文精读。每遇到一个生词，他不再死记，"
            f"而是拆成“词根+语境+可检索线索”，并强迫自己写一句可迁移的规则。\n\n"
            f"第二天早读抽查，班里大多数人卡在第三十个单词时，林渊已经顺着语义网络连到第九十个。"
            f"同桌盯着他，像第一次见到另一个人。班主任皱眉，问他昨晚是不是背答案了。"
            f"林渊低头道歉，态度恭敬，却把笔记本翻开递过去：每个单词后面都不是中文释义，"
            f"而是一条“为什么这样记更稳”的逻辑链。\n\n"
            f"办公室里短暂沉默。老师没夸他，只说“继续观察”。"
            f"但林渊走出门时，脚步比昨天稳了很多。他忽然明白，真正的反叛不是和谁吵赢，"
            f"而是把命运的方向盘从“别人怎么说”里拿回来。\n\n"
            f"深瞳淡淡开口：“今天只是开胃菜。下一关，我要你十天把3500词过一轮，"
            f"并且每晚输出结构化复盘。做得到，我给你‘单词逻辑速记法完整版’。”"
            f"林渊抬眼看向教学楼外漆黑的天，第一次觉得那不是黑，而是深。"
        )
        content = self._expand_fallback_chapter_text(ctx, merged, content)

        return {
            "chapter_title": f"第{ctx['chapterIndex']}章：第一次夺回方向盘",
            "chapter_summary": "主角在羞耻与恐惧中第一次用深度思考做主动选择，获得小胜并解锁下阶段挑战。",
            "chapter_text": content,
            "deep_thinking_checkpoints": [
                "提出白痴问题",
                "完成5Why追问",
                "识别主要矛盾",
                "基于第一性原理重构学习动作",
            ],
            "energy_gain": gain,
            "energy_after": energy_after,
            "hero_stage": ctx["heroStage"],
            "ai_capability_level": ai_level,
            "ending_hook": "深瞳发布“十天3500词”硬核挑战，下一章进入高压实战。",
        }

    def _fallback_qa(self, ctx: Dict, writer_payload: Dict) -> Dict:
        text = normalize_text(writer_payload.get("chapter_text"))
        issues = []
        length_constraints = build_length_constraints(ctx.get("targetWordCount", 3200))
        effective_chars = count_effective_chars(text)
        if effective_chars < length_constraints["min_required"]:
            issues.append(
                f"章节正文偏短（当前约{effective_chars}字，至少需要{length_constraints['min_required']}字）。"
            )
        if "主要矛盾" not in text and "矛盾" not in text:
            issues.append("深度思考术语出现不足，建议补一段“主要矛盾”分析。")
        if "深瞳" not in text:
            issues.append("AI角色存在感不足。")

        score = 90
        if issues:
            score = max(58, 90 - len(issues) * 10)
        return {
            "passed": len(issues) == 0,
            "score": score,
            "issues": issues,
            "must_fix": issues[:2],
        }

    def _build_agent_prompts(self, ctx: Dict, knowledge_prompt: str) -> Dict[str, Dict[str, str]]:
        route_text = json.dumps(ctx.get("routingStrategy") or {}, ensure_ascii=False)
        profile_text = json.dumps(ctx.get("studentProfile") or {}, ensure_ascii=False)
        state_text = compact_project_state_for_prompt(ctx.get("projectState"))
        recent_text = compact_recent_chapters_for_prompt(ctx.get("recentChapters") or [])
        base = (
            f"项目：{ctx['projectName']}\n"
            f"前提：{ctx['premise']}\n"
            f"章节：第{ctx['chapterIndex']}/{ctx['totalChapters']}章\n"
            f"主角阶段：{ctx['heroStage']}（{ctx['heroStageDesc']}）\n"
            f"AI能力范围：{ctx['aiBandLow']}~{ctx['aiBandHigh']}\n"
            f"主角设定：{ctx['protagonistProfile']}\n"
            f"AI设定：{ctx['aiProfile']}\n"
            f"学生画像：{profile_text}\n"
            f"自动分流策略：{route_text}\n"
            f"风格：{ctx['writingStyle']}\n"
            f"上一章摘要：{ctx['previousSummary'] or '无'}\n"
            f"历史章节摘要：\n{recent_text}\n"
            f"项目状态：\n{state_text}\n"
            f"深度思考卡：{ctx['deepThinkingCard']}\n"
            f"知识库片段：\n{knowledge_prompt}\n"
        )

        return {
            "framework": {
                "system": "你是网文剧情架构师，只输出 JSON。",
                "user": (
                    f"{base}\n"
                    "任务：给出本章爽文结构。输出 JSON 键："
                    "chapter_goal, core_conflict, cool_points(数组), plot_beats(数组), ending_hook。"
                ),
            },
            "character": {
                "system": "你是人物弧线设计师，只输出 JSON。",
                "user": (
                    f"{base}\n"
                    "任务：设计主角本章心理与行为突破。输出 JSON 键："
                    "current_fear, ego_mask, breakthrough_choice, emotion_curve(数组), dialogue_tone。"
                ),
            },
            "deep": {
                "system": "你是深度思考导师，融合矛盾论+第一性原理，只输出 JSON。",
                "user": (
                    f"{base}\n"
                    "任务：给出本章“深度思考实战”。输出 JSON 键："
                    "white_question, five_whys(数组), primary_contradiction, "
                    "first_principles(数组), task_for_hero, task_metrics(数组), anti_self_deception(数组), "
                    "energy_gain_suggestion, ai_upgrade_hint。\n"
                    "硬性要求：five_whys 至少5条；task_metrics 至少3条且可量化。"
                ),
            },
            "scene": {
                "system": "你是场景与叙事节奏导演，只输出 JSON。",
                "user": (
                    f"{base}\n"
                    "任务：设计本章时空、角色关系、节奏推进。输出 JSON 键："
                    "time_space, environment_trigger, supporting_roles(数组), pacing_notes(数组)。"
                ),
            },
        }

    def _build_writer_prompts(self, ctx: Dict, merged: Dict, knowledge_prompt: str) -> Tuple[str, str]:
        route_text = json.dumps(ctx.get("routingStrategy") or {}, ensure_ascii=False)
        profile_text = json.dumps(ctx.get("studentProfile") or {}, ensure_ascii=False)
        state_text = compact_project_state_for_prompt(ctx.get("projectState"))
        recent_text = compact_recent_chapters_for_prompt(ctx.get("recentChapters") or [])
        length_constraints = build_length_constraints(ctx.get("targetWordCount", 3200))
        system_prompt = (
            "你是长篇连载小说写作总控，擅长把多Agent输入融合成真实、有代入感、有爽点的章节。"
            "只输出 JSON，不要输出额外解释。"
        )
        user_prompt = (
            f"项目：{ctx['projectName']}\n"
            f"前提：{ctx['premise']}\n"
            f"章节：第{ctx['chapterIndex']}/{ctx['totalChapters']}章\n"
            f"目标字数：约{ctx['targetWordCount']}字中文\n"
            f"风格：{ctx['writingStyle']}\n"
            f"主角阶段：{ctx['heroStage']}（{ctx['heroStageDesc']}）\n"
            f"AI能力范围：{ctx['aiBandLow']}~{ctx['aiBandHigh']}\n"
            f"AI能量起点：{ctx['energyBefore']}\n"
            f"细节密度等级：{ctx.get('detailDensity', 8)}/10\n"
            f"多模型协作：{'开启' if ctx.get('multiModelCollab') else '关闭'}\n"
            f"深度委员会模型：{', '.join(ctx.get('deepCommitteeModels') or [])}\n"
            f"学生画像：{profile_text}\n"
            f"自动分流策略：{route_text}\n"
            f"历史章节摘要：\n{recent_text}\n"
            f"项目状态：\n{state_text}\n"
            f"深度思考卡：{ctx['deepThinkingCard']}\n"
            f"知识库：\n{knowledge_prompt}\n\n"
            "请融合以下四个Agent结果写出完整章节：\n"
            f"剧情架构：{json.dumps(merged.get('framework', {}), ensure_ascii=False)}\n"
            f"人物弧线：{json.dumps(merged.get('character', {}), ensure_ascii=False)}\n"
            f"深度思考：{json.dumps(merged.get('deep', {}), ensure_ascii=False)}\n"
            f"场景节奏：{json.dumps(merged.get('scene', {}), ensure_ascii=False)}\n\n"
            "硬性要求：\n"
            "1) 主角必须真实地怯懦、犹豫，但做出一个可验证的突破。\n"
            "2) 深瞳（AI）要毒舌但有效，至少出现2轮引导式对话。\n"
            "3) 深度思考必须包含“白痴问题->追问->主要矛盾->行动重构”。\n"
            "3.1) 必须把 task_metrics 写进剧情里，给出本章可验证的执行结果数据。\n"
            "3.2) 必须体现 anti_self_deception（如何防止主角自我欺骗）。\n"
            "4) 结果要有现实可复刻性，避免玄幻跳级。\n"
            "5) 必须延续已建立的人物关系、时间线与世界规则，不得前后矛盾。\n"
            "6) 至少写出6个有动作推进的场景段，每段包含：场景目标、冲突动作、心理反应、小结果。\n"
            f"7) 正文字数下限：{length_constraints['min_required']}字（不足视为失败）。\n"
            "8) 结尾留下下一章强钩子。\n\n"
            "输出 JSON 键："
            "chapter_title, chapter_summary, chapter_text, deep_thinking_checkpoints(数组), "
            "energy_gain, hero_stage, ai_capability_level, ending_hook。"
        )
        return system_prompt, user_prompt

    def _build_qa_prompts(self, ctx: Dict, writer_payload: Dict) -> Tuple[str, str]:
        length_constraints = build_length_constraints(ctx.get("targetWordCount", 3200))
        system_prompt = "你是网文质检编辑，只输出 JSON。"
        user_prompt = (
            f"请审阅第{ctx['chapterIndex']}章草稿，重点看：逻辑、自洽、爽点、深度思考落地性。\n"
            f"字数要求：至少{length_constraints['min_required']}字，理想不低于{length_constraints['ideal_low']}字。\n"
            "必须检查是否存在“只讲结论不写过程”的大纲化跳跃。\n"
            f"草稿：{json.dumps(writer_payload, ensure_ascii=False)}\n"
            "输出 JSON 键：passed(bool), score(0-100), issues(数组), must_fix(数组)。"
        )
        return system_prompt, user_prompt

    def _fallback_memory_delta(self, ctx: Dict, writer_payload: Dict) -> Dict:
        chapter_idx = ctx["chapterIndex"]
        protagonist_name = "林渊"
        text = normalize_text(writer_payload.get("chapter_text"))
        loop_desc = normalize_text(writer_payload.get("ending_hook")) or "新挑战待完成"
        chars = [
            {
                "name": protagonist_name,
                "role": "主角",
                "traits": ["犹豫", "渴望逆袭", "正在建立主体性"],
                "status": normalize_text(writer_payload.get("chapter_summary"))[:80],
                "goals": ["提分", "突破恐惧"],
            },
            {
                "name": "深瞳",
                "role": "AI导师",
                "traits": ["毒舌", "高压追问", "反捷径"],
                "status": "能量随主角深度思考提升",
                "goals": ["训练深度思考能力"],
            },
        ]
        relationships = [
            {"a": protagonist_name, "b": "深瞳", "type": "导师-学员", "status": "强化", "notes": "每章通过任务积累能量"}
        ]
        if "班主任" in text:
            relationships.append({"a": protagonist_name, "b": "班主任", "type": "师生博弈", "status": "试探", "notes": "表面顺从、实则争取学习自主权"})
        return {
            "characters": chars,
            "relationships": relationships,
            "timeline": [
                {
                    "chapter": chapter_idx,
                    "event": normalize_text(writer_payload.get("chapter_title")) or f"第{chapter_idx}章推进",
                    "impact": normalize_text(writer_payload.get("chapter_summary")),
                }
            ],
            "world_rules": [
                "AI能力升级依赖主角完成深度思考任务",
                "深度思考路径：白痴问题->追问->主要矛盾->重构行动",
            ],
            "open_loops": [
                {
                    "id": f"loop-{chapter_idx:03d}",
                    "description": loop_desc,
                    "status": "open",
                    "introduced_in": chapter_idx,
                    "updated_in": chapter_idx,
                }
            ],
            "stage_progress": [
                {
                    "chapter": chapter_idx,
                    "hero_stage": ctx["heroStage"],
                    "milestone": normalize_text(writer_payload.get("chapter_summary"))[:120],
                }
            ],
            "summary_for_next_chapter": normalize_text(writer_payload.get("ending_hook")),
        }

    def _build_memory_prompts(self, ctx: Dict, writer_payload: Dict) -> Tuple[str, str]:
        system_prompt = "你是小说连续性记忆提取器。只输出 JSON。"
        user_prompt = (
            f"项目：{ctx['projectName']}\n"
            f"当前章节：第{ctx['chapterIndex']}章\n"
            f"已知项目状态：{compact_project_state_for_prompt(ctx.get('projectState'))}\n"
            f"当前章节内容：{json.dumps(writer_payload, ensure_ascii=False)}\n"
            "任务：提取本章新增/变化的连续性信息，用于后续章节避免矛盾。\n"
            "输出 JSON 键：characters(数组), relationships(数组), timeline(数组), world_rules(数组), "
            "open_loops(数组), stage_progress(数组), summary_for_next_chapter。\n"
            "字段规范：\n"
            "- characters: {name, role, traits[], status, goals[]}\n"
            "- relationships: {a, b, type, status, notes}\n"
            "- timeline: {chapter, event, impact}\n"
            "- open_loops: {id, description, status, introduced_in, updated_in}\n"
        )
        return system_prompt, user_prompt

    def _fallback_chapter_logic_audit(self, ctx: Dict, writer_payload: Dict) -> Dict:
        text = normalize_text(writer_payload.get("chapter_text"))
        issues = []
        contradictions = []
        if not text:
            issues.append("章节正文为空。")
        if "深瞳" not in text:
            issues.append("缺少AI导师出场，可能与主设定不一致。")
        if "白痴问题" not in text and "为什么" not in text:
            issues.append("深度思考链路不足。")
        if normalize_text(ctx.get("previousSummary")) and len(text) < 600:
            contradictions.append("与上一章衔接信息过少，可能出现断档。")

        score = 92 - len(issues) * 10 - len(contradictions) * 6
        return {
            "passed": len(issues) == 0 and len(contradictions) == 0,
            "score": clamp_int(score, 0, 100),
            "issues": issues,
            "contradictions": contradictions,
            "holes": issues,
            "must_fix": (contradictions + issues)[:3],
            "patch_suggestions": [
                "补一段与上一章结尾钩子的直接承接。",
                "补充人物动机因果链与时间标记。",
            ][: 1 if not issues and not contradictions else 2],
        }

    def _build_chapter_logic_prompts(self, ctx: Dict, writer_payload: Dict) -> Tuple[str, str]:
        system_prompt = "你是剧情逻辑审计员，专查当前章节与已知上下文矛盾。只输出 JSON。"
        user_prompt = (
            f"项目：{ctx['projectName']}\n"
            f"章节：第{ctx['chapterIndex']}章\n"
            f"上一章摘要：{ctx.get('previousSummary') or '无'}\n"
            f"历史章节：\n{compact_recent_chapters_for_prompt(ctx.get('recentChapters') or [])}\n"
            f"项目状态：{compact_project_state_for_prompt(ctx.get('projectState'))}\n"
            f"当前章节：{json.dumps(writer_payload, ensure_ascii=False)}\n"
            "审计目标：检查人物动机、时间线、世界规则、任务奖励是否自洽，指出漏洞与修复建议。\n"
            "输出 JSON 键：passed(bool), score, issues(数组), contradictions(数组), holes(数组), must_fix(数组), patch_suggestions(数组)。"
        )
        return system_prompt, user_prompt

    def _fallback_global_logic_audit(self, merged_state: Dict) -> Dict:
        chars = merged_state.get("characters", []) if isinstance(merged_state.get("characters"), list) else []
        rels = merged_state.get("relationships", []) if isinstance(merged_state.get("relationships"), list) else []
        timeline = merged_state.get("timeline", []) if isinstance(merged_state.get("timeline"), list) else []
        loops = merged_state.get("open_loops", []) if isinstance(merged_state.get("open_loops"), list) else []
        issues = []
        if len(chars) <= 1:
            issues.append("人物网络过薄，建议补充关键配角和关系演化。")
        if len(timeline) == 0:
            issues.append("时间线为空，无法进行全书一致性检查。")
        open_count = 0
        for row in loops:
            if not isinstance(row, dict):
                continue
            if normalize_text(row.get("status")) in {"open", "", "todo"}:
                open_count += 1
        score = clamp_int(90 - len(issues) * 12 - max(0, open_count - 12), 0, 100)
        return {
            "passed": len(issues) == 0,
            "score": score,
            "issues": issues,
            "character_consistency": "基本一致",
            "timeline_consistency": "基本一致",
            "rule_consistency": "基本一致",
            "unresolved_risks": [f"未回收伏笔数量：{open_count}"],
            "must_fix": issues[:3],
            "relationship_map_update": rels[-6:],
            "stage_progress_check": "阶段推进可追踪",
            "full_book_digest": {
                "character_count": len(chars),
                "relationship_count": len(rels),
                "timeline_count": len(timeline),
                "open_loop_count": open_count,
            },
        }

    def _build_global_logic_prompts(self, ctx: Dict, writer_payload: Dict, merged_state: Dict) -> Tuple[str, str]:
        system_prompt = "你是长篇连载总审计官，负责整本小说连续性与漏洞检查。只输出 JSON。"
        user_prompt = (
            f"项目：{ctx['projectName']}\n"
            f"当前章节：第{ctx['chapterIndex']}章\n"
            f"全书历史章节：\n{compact_recent_chapters_for_prompt(ctx.get('recentChapters') or [], max_items=20)}\n"
            f"最新项目状态：{compact_project_state_for_prompt(merged_state, max_chars=5000)}\n"
            f"当前章节摘要：{normalize_text(writer_payload.get('chapter_summary'))}\n"
            "任务：审查全书是否存在人物关系矛盾、时间线冲突、世界规则打架、阶段错乱、伏笔失控。\n"
            "输出 JSON 键：passed(bool), score, issues(数组), character_consistency, timeline_consistency, "
            "rule_consistency, unresolved_risks(数组), must_fix(数组), relationship_map_update(数组), "
            "stage_progress_check, full_book_digest(对象)。"
        )
        return system_prompt, user_prompt

    def _normalize_writer_payload(self, ctx: Dict, merged: Dict, writer_payload: Dict) -> Dict:
        payload = writer_payload if isinstance(writer_payload, dict) else {}
        gain = clamp_or_default(
            payload.get("energy_gain", merged.get("deep", {}).get("energy_gain_suggestion", 36)),
            36,
            5,
            160,
        )
        payload["energy_gain"] = gain
        payload["energy_after"] = ctx["energyBefore"] + gain
        payload["hero_stage"] = ctx["heroStage"]
        payload["ai_capability_level"] = clamp_or_default(
            payload.get("ai_capability_level", ctx["aiBandLow"]),
            ctx["aiBandLow"],
            ctx["aiBandLow"],
            10,
        )
        payload.setdefault("chapter_title", f"第{ctx['chapterIndex']}章")
        payload.setdefault("chapter_summary", "")
        payload.setdefault("ending_hook", merged.get("framework", {}).get("ending_hook", ""))
        if not isinstance(payload.get("deep_thinking_checkpoints"), list):
            payload["deep_thinking_checkpoints"] = [
                "提出问题",
                "追问本质",
                "识别主要矛盾",
                "重构行动",
            ]
        payload["effective_chars"] = count_effective_chars(normalize_text(payload.get("chapter_text")))
        return payload

    def _fallback_deep_quality_audit(self, merged: Dict, writer_payload: Dict) -> Dict:
        deep_payload = merged.get("deep") if isinstance(merged.get("deep"), dict) else {}
        text = normalize_text(writer_payload.get("chapter_text"))
        issues = []
        five_whys = deep_payload.get("five_whys") if isinstance(deep_payload.get("five_whys"), list) else []
        first_principles = deep_payload.get("first_principles") if isinstance(deep_payload.get("first_principles"), list) else []
        task_metrics = deep_payload.get("task_metrics") if isinstance(deep_payload.get("task_metrics"), list) else []
        if len(five_whys) < 5:
            issues.append("five_whys 不足5层，深度不够。")
        if len(first_principles) < 3:
            issues.append("第一性原理不足3条。")
        if len(task_metrics) < 2:
            issues.append("缺少可量化任务指标。")
        if "主要矛盾" not in text and "矛盾" not in text:
            issues.append("正文没有清晰呈现主要矛盾。")
        score = clamp_int(93 - len(issues) * 13, 0, 100)
        return {
            "passed": len(issues) == 0,
            "score": score,
            "issues": issues,
            "must_fix": issues[:3],
            "checkpoints": {
                "five_whys_count": len(five_whys),
                "first_principles_count": len(first_principles),
                "task_metrics_count": len(task_metrics),
            },
        }

    def _build_deep_quality_prompts(self, ctx: Dict, merged: Dict, writer_payload: Dict) -> Tuple[str, str]:
        system_prompt = "你是深度思考质检官，专查“是否真的在深度思考”，只输出 JSON。"
        user_prompt = (
            f"项目：{ctx['projectName']}\n"
            f"章节：第{ctx['chapterIndex']}章\n"
            f"深度思考卡：{ctx['deepThinkingCard']}\n"
            f"深度Agent结果：{json.dumps(merged.get('deep', {}), ensure_ascii=False)}\n"
            f"章节草稿：{json.dumps(writer_payload, ensure_ascii=False)}\n"
            "审计规则：\n"
            "1) five_whys 是否>=5层且有因果推进；\n"
            "2) 是否明确主要矛盾并映射到行动；\n"
            "3) 是否包含>=3条第一性原理；\n"
            "4) 是否给出量化任务指标并在正文兑现；\n"
            "5) 是否出现“喊口号、无实操”的空转。\n"
            "输出 JSON 键：passed(bool), score, issues(数组), must_fix(数组), checkpoints(对象)。"
        )
        return system_prompt, user_prompt

    def _evaluate_draft(
        self,
        ctx: Dict,
        merged: Dict,
        writer_payload: Dict,
        strict_llm: bool = False,
        allow_transient_fallback: bool = False,
    ) -> Dict:
        qa_fallback = self._fallback_qa(ctx, writer_payload)
        qa_system, qa_user = self._build_qa_prompts(ctx, writer_payload)
        qa_result = self._invoke_agent(
            agent_name="qa",
            system_prompt=qa_system,
            user_prompt=qa_user,
            fallback_payload=qa_fallback,
            temperature=0.2,
            max_tokens=900,
            model_override=self._resolve_agent_model(ctx, "qa"),
            timeout_seconds_override=ctx.get("agentTimeoutSeconds", 180),
        )
        self._raise_if_strict_fallback(strict_llm, "qa", qa_result, allow_transient=allow_transient_fallback)
        qa_payload = qa_result["payload"] if isinstance(qa_result.get("payload"), dict) else qa_fallback
        if "passed" not in qa_payload:
            qa_payload = qa_fallback

        memory_fallback = self._fallback_memory_delta(ctx, writer_payload)
        memory_system, memory_user = self._build_memory_prompts(ctx, writer_payload)
        memory_result = self._invoke_agent(
            agent_name="memory_extractor",
            system_prompt=memory_system,
            user_prompt=memory_user,
            fallback_payload=memory_fallback,
            temperature=0.3,
            max_tokens=1600,
            model_override=self._resolve_agent_model(ctx, "memory_extractor"),
            timeout_seconds_override=ctx.get("agentTimeoutSeconds", 180),
        )
        self._raise_if_strict_fallback(strict_llm, "memory_extractor", memory_result, allow_transient=allow_transient_fallback)
        memory_delta = memory_result["payload"] if isinstance(memory_result.get("payload"), dict) else memory_fallback
        merged_state = merge_project_state(
            previous=ctx.get("projectState"),
            delta=memory_delta,
            chapter_index=ctx["chapterIndex"],
            hero_stage=ctx["heroStage"],
        )

        chapter_logic_fallback = self._fallback_chapter_logic_audit(ctx, writer_payload)
        chapter_logic_system, chapter_logic_user = self._build_chapter_logic_prompts(ctx, writer_payload)
        chapter_logic_result = self._invoke_agent(
            agent_name="chapter_logic_audit",
            system_prompt=chapter_logic_system,
            user_prompt=chapter_logic_user,
            fallback_payload=chapter_logic_fallback,
            temperature=0.2,
            max_tokens=1400,
            model_override=self._resolve_agent_model(ctx, "chapter_logic_audit"),
            timeout_seconds_override=ctx.get("agentTimeoutSeconds", 180),
        )
        self._raise_if_strict_fallback(strict_llm, "chapter_logic_audit", chapter_logic_result, allow_transient=allow_transient_fallback)
        chapter_logic_payload = (
            chapter_logic_result["payload"]
            if isinstance(chapter_logic_result.get("payload"), dict)
            else chapter_logic_fallback
        )
        if "passed" not in chapter_logic_payload:
            chapter_logic_payload = chapter_logic_fallback

        global_logic_fallback = self._fallback_global_logic_audit(merged_state)
        global_logic_system, global_logic_user = self._build_global_logic_prompts(ctx, writer_payload, merged_state)
        global_logic_result = self._invoke_agent(
            agent_name="global_logic_audit",
            system_prompt=global_logic_system,
            user_prompt=global_logic_user,
            fallback_payload=global_logic_fallback,
            temperature=0.2,
            max_tokens=1800,
            model_override=self._resolve_agent_model(ctx, "global_logic_audit"),
            timeout_seconds_override=ctx.get("agentTimeoutSeconds", 180),
        )
        self._raise_if_strict_fallback(strict_llm, "global_logic_audit", global_logic_result, allow_transient=allow_transient_fallback)
        global_logic_payload = (
            global_logic_result["payload"]
            if isinstance(global_logic_result.get("payload"), dict)
            else global_logic_fallback
        )
        if "passed" not in global_logic_payload:
            global_logic_payload = global_logic_fallback

        deep_quality_fallback = self._fallback_deep_quality_audit(merged, writer_payload)
        deep_quality_system, deep_quality_user = self._build_deep_quality_prompts(ctx, merged, writer_payload)
        deep_quality_result = self._invoke_agent(
            agent_name="deep_quality_audit",
            system_prompt=deep_quality_system,
            user_prompt=deep_quality_user,
            fallback_payload=deep_quality_fallback,
            temperature=0.2,
            max_tokens=1300,
            model_override=self._resolve_agent_model(ctx, "deep_quality_audit", self._resolve_agent_model(ctx, "deep_referee")),
            timeout_seconds_override=ctx.get("agentTimeoutSeconds", 180),
        )
        self._raise_if_strict_fallback(strict_llm, "deep_quality_audit", deep_quality_result, allow_transient=allow_transient_fallback)
        deep_quality_payload = (
            deep_quality_result["payload"]
            if isinstance(deep_quality_result.get("payload"), dict)
            else deep_quality_fallback
        )
        if "passed" not in deep_quality_payload:
            deep_quality_payload = deep_quality_fallback

        qa_score = clamp_or_default(qa_payload.get("score"), 70, 0, 100)
        chapter_logic_score = clamp_or_default(chapter_logic_payload.get("score"), 70, 0, 100)
        global_logic_score = clamp_or_default(global_logic_payload.get("score"), 70, 0, 100)
        deep_quality_score = clamp_or_default(deep_quality_payload.get("score"), 70, 0, 100)
        final_score = clamp_int(
            int(round(qa_score * 0.28 + chapter_logic_score * 0.28 + global_logic_score * 0.24 + deep_quality_score * 0.20)),
            0,
            100,
        )
        final_passed = (
            bool(qa_payload.get("passed"))
            and bool(chapter_logic_payload.get("passed"))
            and bool(global_logic_payload.get("passed"))
            and bool(deep_quality_payload.get("passed"))
        )
        final_issues = []
        for source, payload in (
            ("writer_qa", qa_payload),
            ("chapter_logic", chapter_logic_payload),
            ("global_logic", global_logic_payload),
            ("deep_quality", deep_quality_payload),
        ):
            issues = payload.get("issues") if isinstance(payload.get("issues"), list) else []
            for issue in issues:
                text = normalize_text(issue)
                if text:
                    final_issues.append(f"[{source}] {text}")
        final_quality = {
            "passed": final_passed,
            "score": final_score,
            "issues": final_issues[:18],
            "must_fix": (
                (qa_payload.get("must_fix") if isinstance(qa_payload.get("must_fix"), list) else [])
                + (chapter_logic_payload.get("must_fix") if isinstance(chapter_logic_payload.get("must_fix"), list) else [])
                + (global_logic_payload.get("must_fix") if isinstance(global_logic_payload.get("must_fix"), list) else [])
                + (deep_quality_payload.get("must_fix") if isinstance(deep_quality_payload.get("must_fix"), list) else [])
            )[:10],
            "breakdown": {
                "writer_qa": qa_score,
                "chapter_logic": chapter_logic_score,
                "global_logic": global_logic_score,
                "deep_quality": deep_quality_score,
            },
        }
        length_constraints = build_length_constraints(ctx.get("targetWordCount", 3200))
        effective_chars = count_effective_chars(normalize_text(writer_payload.get("chapter_text")))
        final_quality["effective_chars"] = effective_chars
        final_quality["length_constraints"] = length_constraints
        if effective_chars < length_constraints["min_required"]:
            final_quality["passed"] = False
            final_quality["score"] = max(25, final_quality["score"] - 18)
            final_quality["issues"] = [f"[length] 字数不足：当前约{effective_chars}字，要求至少{length_constraints['min_required']}字。"] + final_quality["issues"]
            must_fix = final_quality.get("must_fix", [])
            if isinstance(must_fix, list):
                final_quality["must_fix"] = [f"扩写到至少{length_constraints['min_required']}字，补全场景细节。"] + must_fix
        return {
            "qa_result": qa_result,
            "qa_payload": qa_payload,
            "memory_result": memory_result,
            "memory_delta": memory_delta,
            "merged_state": merged_state,
            "chapter_logic_result": chapter_logic_result,
            "chapter_logic_payload": chapter_logic_payload,
            "global_logic_result": global_logic_result,
            "global_logic_payload": global_logic_payload,
            "deep_quality_result": deep_quality_result,
            "deep_quality_payload": deep_quality_payload,
            "final_quality": final_quality,
        }

    def _build_rewrite_prompts(
        self,
        ctx: Dict,
        merged: Dict,
        knowledge_prompt: str,
        draft_payload: Dict,
        evaluation: Dict,
        round_index: int,
    ) -> Tuple[str, str]:
        length_constraints = build_length_constraints(ctx.get("targetWordCount", 3200))
        system_prompt = "你是小说修订总编，擅长按审计意见精准改写章节，保留优点、修复漏洞。只输出 JSON。"
        user_prompt = (
            f"项目：{ctx['projectName']}\n"
            f"章节：第{ctx['chapterIndex']}/{ctx['totalChapters']}章\n"
            f"当前是自动改写第{round_index}轮\n"
            f"学生画像：{json.dumps(ctx.get('studentProfile') or {}, ensure_ascii=False)}\n"
            f"分流策略：{json.dumps(ctx.get('routingStrategy') or {}, ensure_ascii=False)}\n"
            f"历史章节：\n{compact_recent_chapters_for_prompt(ctx.get('recentChapters') or [])}\n"
            f"项目状态：{compact_project_state_for_prompt(evaluation.get('merged_state'), max_chars=5000)}\n"
            f"知识库：\n{knowledge_prompt}\n"
            f"剧情架构：{json.dumps(merged.get('framework', {}), ensure_ascii=False)}\n"
            f"人物弧线：{json.dumps(merged.get('character', {}), ensure_ascii=False)}\n"
            f"深度思考：{json.dumps(merged.get('deep', {}), ensure_ascii=False)}\n"
            f"场景节奏：{json.dumps(merged.get('scene', {}), ensure_ascii=False)}\n\n"
            f"当前草稿：{json.dumps(draft_payload, ensure_ascii=False)}\n"
            f"质量总评：{json.dumps(evaluation.get('final_quality') or {}, ensure_ascii=False)}\n"
            f"章节审计：{json.dumps(evaluation.get('chapter_logic_payload') or {}, ensure_ascii=False)}\n"
            f"全书审计：{json.dumps(evaluation.get('global_logic_payload') or {}, ensure_ascii=False)}\n\n"
            f"深度思考审计：{json.dumps(evaluation.get('deep_quality_payload') or {}, ensure_ascii=False)}\n\n"
            "修订要求：\n"
            "1) 必须逐条处理 must_fix，补齐因果与连续性。\n"
            "2) 保留已有爽点，不得把主角写成一步登天。\n"
            "3) 必须与人物关系、时间线、规则库一致。\n"
            "4) 保留深瞳高压引导风格，并且让行动可复刻。\n"
            "5) 把“大纲化叙述”改成“现场化叙述”：加入动作、对话、心理变化、感官细节。\n"
            f"6) 正文字数至少{length_constraints['min_required']}字，目标接近{length_constraints['target']}字。\n"
            "输出 JSON 键：chapter_title, chapter_summary, chapter_text, deep_thinking_checkpoints(数组), "
            "energy_gain, hero_stage, ai_capability_level, ending_hook。"
        )
        return system_prompt, user_prompt

    def _fallback_outline(self, ctx: Dict) -> Dict:
        chapters = []
        for idx in range(1, ctx["totalChapters"] + 1):
            stage = stage_for_chapter(idx, ctx["totalChapters"])
            chapters.append(
                {
                    "chapter_index": idx,
                    "stage": stage,
                    "title": f"第{idx}章：阶段{stage}推进",
                    "goal": "主角识别并突破一个具体恐惧点",
                    "conflict": "旧习惯与新认知冲突",
                    "deep_task": "完成一次白痴问题+5Why+行动重构",
                    "payoff": "可验证的小结果",
                }
            )
        return {
            "book_title": ctx["projectName"],
            "theme": "通过高考实战完成深度思考觉醒",
            "chapters": chapters,
        }

    def generate_outline(self, req: Dict, selected_knowledge_rows: List[Dict]) -> Dict:
        ctx = self._base_context(req)
        strict_llm = to_bool(req.get("requireLLM"), False)
        allow_transient_fallback = to_bool(req.get("allowTransientFallback"), True)
        outline_second_pass = to_bool(req.get("outlineSecondPass"), False)
        if strict_llm and not self.llm.enabled():
            raise RuntimeError("requireLLM=true，但当前未配置可用的 Kimi API Key。")
        knowledge_prompt = compact_knowledge_for_prompt(selected_knowledge_rows, max_items=4, max_chars_each=380)
        fallback = self._fallback_outline(ctx)
        system_prompt = "你是连载小说总策划，擅长爽文结构与成长弧线设计。只输出 JSON。"
        user_prompt = (
            f"项目：{ctx['projectName']}\n"
            f"前提：{ctx['premise']}\n"
            f"总章节：{ctx['totalChapters']}\n"
            f"主角设定：{ctx['protagonistProfile']}\n"
            f"AI设定：{ctx['aiProfile']}\n"
            f"风格：{ctx['writingStyle']}\n"
            f"深度思考卡：{ctx['deepThinkingCard']}\n"
            f"知识库：\n{knowledge_prompt}\n\n"
            "任务：输出可执行的全书大纲。必须覆盖 1-6 阶主线成长，7 阶以上仅作远景点到为止。\n"
            "输出 JSON 键：book_title, theme, chapters。\n"
            "chapters 为数组，每个元素包含：chapter_index, stage, title, goal, conflict, deep_task, payoff。"
        )
        result = self._invoke_agent(
            agent_name="outline",
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            fallback_payload=fallback,
            temperature=0.8,
            max_tokens=2600,
            model_override=self._resolve_agent_model(ctx, "outline"),
            timeout_seconds_override=ctx.get("outlineTimeoutSeconds", 260),
        )
        if outline_second_pass and bool(result.get("fallback")) and self._is_transient_model_error(result.get("error", "")):
            fast_system = "你是连载小说总策划。输出可执行20章JSON大纲，精炼但完整。只输出 JSON。"
            fast_user = (
                f"项目：{ctx['projectName']}\n"
                f"前提（压缩版）：{compact_text(ctx['premise'], 1800)}\n"
                f"总章节：{ctx['totalChapters']}\n"
                f"主角设定：{compact_text(ctx['protagonistProfile'], 500)}\n"
                f"AI设定：{compact_text(ctx['aiProfile'], 500)}\n"
                f"深度思考卡（压缩）：{compact_text(ctx['deepThinkingCard'], 900)}\n"
                f"知识库（压缩）：\n{compact_knowledge_for_prompt(selected_knowledge_rows, max_items=2, max_chars_each=180)}\n"
                "任务：输出 20 章大纲，每章必须有 goal/conflict/deep_task/payoff，阶段1-6递进。\n"
                "输出 JSON 键：book_title, theme, chapters。"
            )
            retry_result = self._invoke_agent(
                agent_name="outline_fast_retry",
                system_prompt=fast_system,
                user_prompt=fast_user,
                fallback_payload=fallback,
                temperature=0.35,
                max_tokens=1600,
                model_override=self._resolve_agent_model(ctx, "outline_fast_retry", self._resolve_agent_model(ctx, "outline")),
                timeout_seconds_override=max(90, int(ctx.get("outlineTimeoutSeconds", 260) * 1.15)),
            )
            if not bool(retry_result.get("fallback")):
                result = retry_result
            else:
                combined_error = f"{normalize_text(result.get('error'))} | retry: {normalize_text(retry_result.get('error'))}".strip(" |")
                if combined_error:
                    result["error"] = combined_error
        self._raise_if_strict_fallback(strict_llm, "outline", result, allow_transient=allow_transient_fallback)
        payload = result["payload"]
        if not isinstance(payload.get("chapters"), list) or not payload.get("chapters"):
            payload = fallback
            result["fallback"] = True
            result["error"] = (result.get("error") or "") + " | invalid outline chapters"
        warnings = []
        if bool(result.get("fallback")) and self._is_transient_model_error(result.get("error", "")):
            warnings.append("outline 使用Kimi时触发限流/超时，已降级为保底大纲以保证流程可继续。")
        return {
            "context": ctx,
            "studentProfile": ctx.get("studentProfile"),
            "routingStrategy": ctx.get("routingStrategy"),
            "knowledgeUsed": [
                {"id": row.get("id"), "title": row.get("title"), "tags": row.get("tags")}
                for row in selected_knowledge_rows
            ],
            "outline": payload,
            "agent": result,
            "warnings": warnings,
            "generatedAt": now_iso(),
            "model": {
                "provider": "moonshot" if self.llm.enabled() else "offline-fallback",
                "name": self.llm.model if self.llm.enabled() else "fallback-template",
            },
        }

    def generate_chapter(self, req: Dict, selected_knowledge_rows: List[Dict]) -> Dict:
        ctx = self._base_context(req)
        strict_llm = to_bool(req.get("requireLLM"), False)
        allow_transient_fallback = to_bool(req.get("allowTransientFallback"), True)
        if strict_llm and not self.llm.enabled():
            raise RuntimeError("requireLLM=true，但当前未配置可用的 Kimi API Key。")
        knowledge_prompt = compact_knowledge_for_prompt(selected_knowledge_rows)
        prompts = self._build_agent_prompts(ctx, knowledge_prompt)
        writer_max_tokens = estimate_generation_max_tokens(ctx.get("targetWordCount", 3200), rewrite=False)
        rewrite_max_tokens = estimate_generation_max_tokens(ctx.get("targetWordCount", 3200), rewrite=True)

        first_layer_specs = {
            "framework": {
                "fallback": self._fallback_framework(ctx),
                "temperature": 0.7,
                "max_tokens": 1400,
            },
            "character": {
                "fallback": self._fallback_character(ctx),
                "temperature": 0.75,
                "max_tokens": 1200,
            },
            "scene": {
                "fallback": self._fallback_scene(ctx),
                "temperature": 0.8,
                "max_tokens": 1200,
            },
        }
        deep_fallback = self._fallback_deep(ctx)
        deep_models = ctx.get("deepCommitteeModels") if isinstance(ctx.get("deepCommitteeModels"), list) else []
        deep_primary_model = self._resolve_agent_model(
            ctx,
            "deep_primary",
            (deep_models[0] if deep_models else self._resolve_agent_model(ctx, "deep")),
        )
        deep_secondary_model = self._resolve_agent_model(
            ctx,
            "deep_secondary",
            (deep_models[1] if len(deep_models) > 1 else ""),
        )
        if not to_bool(ctx.get("multiModelCollab"), True):
            deep_secondary_model = ""
        deep_referee_model = self._resolve_agent_model(
            ctx,
            "deep_referee",
            (deep_models[2] if len(deep_models) > 2 else deep_primary_model),
        )
        route_plan = self._build_model_route_plan(
            ctx=ctx,
            deep_primary_model=deep_primary_model,
            deep_secondary_model=deep_secondary_model,
            deep_referee_model=deep_referee_model,
        )

        first_layer_results = {}
        with ThreadPoolExecutor(max_workers=ctx.get("firstLayerWorkers", 2)) as executor:
            future_map = {}
            for name, prompt in prompts.items():
                if name == "deep":
                    continue
                spec = first_layer_specs[name]
                future = executor.submit(
                    self._invoke_agent,
                    name,
                    prompt["system"],
                    prompt["user"],
                    spec["fallback"],
                    spec["temperature"],
                    spec["max_tokens"],
                    self._resolve_agent_model(ctx, name),
                    ctx.get("agentTimeoutSeconds", 180),
                )
                future_map[future] = name
            deep_primary_future = executor.submit(
                self._invoke_agent,
                "deep_primary",
                prompts["deep"]["system"],
                prompts["deep"]["user"],
                deep_fallback,
                0.5,
                2200,
                deep_primary_model,
                ctx.get("writerTimeoutSeconds", 220),
            )
            future_map[deep_primary_future] = "deep_primary"
            if deep_secondary_model:
                deep_secondary_future = executor.submit(
                    self._invoke_agent,
                    "deep_secondary",
                    prompts["deep"]["system"],
                    prompts["deep"]["user"],
                    deep_fallback,
                    0.65,
                    2200,
                    deep_secondary_model,
                    ctx.get("writerTimeoutSeconds", 220),
                )
                future_map[deep_secondary_future] = "deep_secondary"

            for future in as_completed(future_map):
                name = future_map[future]
                try:
                    result = future.result()
                except Exception as exc:
                    fallback = deep_fallback if name in {"deep_primary", "deep_secondary"} else first_layer_specs[name]["fallback"]
                    model = deep_primary_model if name == "deep_primary" else (deep_secondary_model if name == "deep_secondary" else self._resolve_agent_model(ctx, name))
                    result = {
                        "agent": name,
                        "model": model,
                        "payload": fallback,
                        "fallback": True,
                        "error": str(exc),
                        "error_class": self._classify_model_error(str(exc)),
                        "raw": "",
                        "call_meta": {"steps": 0, "attempts": 0, "retry_count": 0, "duration_ms": 0, "status_codes": [], "request_ids": []},
                        "invoke_trace": [],
                    }
                first_layer_results[name] = result
        for name, result in first_layer_results.items():
            self._raise_if_strict_fallback(strict_llm, name, result, allow_transient=allow_transient_fallback)

        deep_primary_result = first_layer_results.get("deep_primary") or {
            "agent": "deep_primary",
            "model": deep_primary_model,
            "payload": deep_fallback,
            "fallback": True,
            "error": "missing deep_primary result",
            "raw": "",
        }
        deep_secondary_result = first_layer_results.get("deep_secondary") if deep_secondary_model else None
        deep_consensus_fallback = self._fallback_deep_consensus(
            deep_primary_result.get("payload"),
            deep_secondary_result.get("payload") if isinstance(deep_secondary_result, dict) else {},
        )
        deep_referee_result = None
        deep_final_result = deep_primary_result
        if isinstance(deep_secondary_result, dict):
            referee_system, referee_user = self._build_deep_consensus_prompts(
                ctx,
                deep_primary_result.get("payload"),
                deep_secondary_result.get("payload"),
            )
            deep_referee_result = self._invoke_agent(
                agent_name="deep_referee",
                system_prompt=referee_system,
                user_prompt=referee_user,
                fallback_payload=deep_consensus_fallback,
                temperature=0.25,
                max_tokens=2000,
                model_override=deep_referee_model,
                timeout_seconds_override=ctx.get("agentTimeoutSeconds", 180),
            )
            self._raise_if_strict_fallback(strict_llm, "deep_referee", deep_referee_result, allow_transient=allow_transient_fallback)
            deep_final_result = deep_referee_result

        deep_payload = deep_final_result.get("payload") if isinstance(deep_final_result.get("payload"), dict) else deep_consensus_fallback
        if not isinstance(deep_payload, dict) or not normalize_text(deep_payload.get("primary_contradiction")):
            deep_payload = deep_consensus_fallback
            deep_final_result = {
                "agent": "deep_consensus_fallback",
                "model": deep_referee_model,
                "payload": deep_payload,
                "fallback": True,
                "error": "deep consensus payload invalid",
                "error_class": "non_json",
                "raw": "",
                "call_meta": {"steps": 0, "attempts": 0, "retry_count": 0, "duration_ms": 0, "status_codes": [], "request_ids": []},
                "invoke_trace": [],
            }

        merged = {
            "framework": first_layer_results["framework"]["payload"],
            "character": first_layer_results["character"]["payload"],
            "deep": deep_payload,
            "scene": first_layer_results["scene"]["payload"],
        }

        writer_fallback = self._fallback_writer(ctx, merged)
        writer_system, writer_user = self._build_writer_prompts(ctx, merged, knowledge_prompt)
        writer_result = self._invoke_agent(
            agent_name="writer",
            system_prompt=writer_system,
            user_prompt=writer_user,
            fallback_payload=writer_fallback,
            temperature=1.0,
            max_tokens=writer_max_tokens,
            model_override=self._resolve_agent_model(ctx, "writer"),
            timeout_seconds_override=ctx.get("writerTimeoutSeconds", 240),
        )
        self._raise_if_strict_fallback(strict_llm, "writer", writer_result, allow_transient=allow_transient_fallback)
        writer_payload = writer_result["payload"] if isinstance(writer_result.get("payload"), dict) else writer_fallback

        if not normalize_text(writer_payload.get("chapter_text")):
            writer_payload = writer_fallback
            writer_result["fallback"] = True
            writer_result["error"] = (writer_result.get("error") or "") + " | empty chapter_text"

        writer_payload = self._normalize_writer_payload(ctx, merged, writer_payload)
        evaluation = self._evaluate_draft(
            ctx,
            merged,
            writer_payload,
            strict_llm=strict_llm,
            allow_transient_fallback=allow_transient_fallback,
        )

        auto_rewrite = to_bool(req.get("autoRewrite"), True)
        max_rewrite_rounds = clamp_or_default(req.get("maxRewriteRounds", 2), 2, 0, 5)
        rewrite_round_results = []
        rewrite_trace = []
        rewrite_triggered = False
        rewrite_rescue_attempted = False
        rewrite_rescue_improved = False
        stagnation_rounds = 0

        for round_idx in range(1, max_rewrite_rounds + 1):
            if not auto_rewrite:
                break
            if bool(evaluation["final_quality"].get("passed")):
                break
            rewrite_triggered = True
            before_score = clamp_or_default(evaluation["final_quality"].get("score"), 0, 0, 100)

            rewrite_system, rewrite_user = self._build_rewrite_prompts(
                ctx=ctx,
                merged=merged,
                knowledge_prompt=knowledge_prompt,
                draft_payload=writer_payload,
                evaluation=evaluation,
                round_index=round_idx,
            )
            rewrite_result = self._invoke_agent(
                agent_name="rewrite",
                system_prompt=rewrite_system,
                user_prompt=rewrite_user,
                fallback_payload=writer_payload,
                temperature=0.75,
                max_tokens=rewrite_max_tokens,
                model_override=self._resolve_agent_model(ctx, "rewrite", self._resolve_agent_model(ctx, "writer")),
                timeout_seconds_override=ctx.get("writerTimeoutSeconds", 240),
            )
            self._raise_if_strict_fallback(strict_llm, "rewrite", rewrite_result, allow_transient=allow_transient_fallback)
            rewritten_payload = rewrite_result["payload"] if isinstance(rewrite_result.get("payload"), dict) else writer_payload
            if not normalize_text(rewritten_payload.get("chapter_text")):
                rewritten_payload = writer_payload
                rewrite_result["fallback"] = True
                rewrite_result["error"] = (rewrite_result.get("error") or "") + " | empty rewritten chapter_text"

            rewritten_payload = self._normalize_writer_payload(ctx, merged, rewritten_payload)
            rewritten_eval = self._evaluate_draft(
                ctx,
                merged,
                rewritten_payload,
                strict_llm=strict_llm,
                allow_transient_fallback=allow_transient_fallback,
            )
            after_score = clamp_or_default(rewritten_eval["final_quality"].get("score"), 0, 0, 100)

            rewrite_trace.append(
                {
                    "round": round_idx,
                    "before_score": before_score,
                    "after_score": after_score,
                    "improved": after_score >= before_score,
                    "before_passed": bool(evaluation["final_quality"].get("passed")),
                    "after_passed": bool(rewritten_eval["final_quality"].get("passed")),
                    "must_fix_before": evaluation["final_quality"].get("must_fix", []),
                    "must_fix_after": rewritten_eval["final_quality"].get("must_fix", []),
                }
            )
            rewrite_round_results.append(
                {
                    "round": round_idx,
                    "result": rewrite_result,
                    "quality": rewritten_eval["final_quality"],
                }
            )
            writer_payload = rewritten_payload
            writer_result = rewrite_result
            evaluation = rewritten_eval
            if bool(evaluation["final_quality"].get("passed")):
                break
            if after_score <= before_score:
                stagnation_rounds += 1
            else:
                stagnation_rounds = 0
            if stagnation_rounds >= 2:
                break

        if auto_rewrite and not bool(evaluation["final_quality"].get("passed")):
            rewrite_rescue_attempted = True
            rewrite_triggered = True
            rescue_round = len(rewrite_trace) + 1
            before_score = clamp_or_default(evaluation["final_quality"].get("score"), 0, 0, 100)
            rescue_system, rescue_user = self._build_rewrite_prompts(
                ctx=ctx,
                merged=merged,
                knowledge_prompt=knowledge_prompt,
                draft_payload=writer_payload,
                evaluation=evaluation,
                round_index=rescue_round,
            )
            rescue_user = (
                rescue_user
                + "\n\n额外强制要求：\n"
                + "1) 必须逐条消灭 must_fix；\n"
                + "2) 每个审计问题都要在正文出现可核验修复；\n"
                + "3) 严禁解释性文本，只输出 JSON。"
            )
            rescue_result = self._invoke_agent(
                agent_name="rewrite_rescue",
                system_prompt=rescue_system,
                user_prompt=rescue_user,
                fallback_payload=writer_payload,
                temperature=0.35,
                max_tokens=rewrite_max_tokens,
                model_override=self._resolve_agent_model(ctx, "rewrite", self._resolve_agent_model(ctx, "writer")),
                timeout_seconds_override=max(120, int(ctx.get("writerTimeoutSeconds", 240) * 1.1)),
            )
            self._raise_if_strict_fallback(
                strict_llm,
                "rewrite_rescue",
                rescue_result,
                allow_transient=allow_transient_fallback,
            )
            rescue_payload = rescue_result["payload"] if isinstance(rescue_result.get("payload"), dict) else writer_payload
            if not normalize_text(rescue_payload.get("chapter_text")):
                rescue_payload = writer_payload
                rescue_result["fallback"] = True
                rescue_result["error"] = (rescue_result.get("error") or "") + " | empty rescue chapter_text"

            rescue_payload = self._normalize_writer_payload(ctx, merged, rescue_payload)
            rescue_eval = self._evaluate_draft(
                ctx,
                merged,
                rescue_payload,
                strict_llm=strict_llm,
                allow_transient_fallback=allow_transient_fallback,
            )
            after_score = clamp_or_default(rescue_eval["final_quality"].get("score"), 0, 0, 100)
            rewrite_rescue_improved = after_score > before_score or bool(rescue_eval["final_quality"].get("passed"))
            rewrite_trace.append(
                {
                    "round": rescue_round,
                    "type": "rescue",
                    "before_score": before_score,
                    "after_score": after_score,
                    "improved": rewrite_rescue_improved,
                    "before_passed": bool(evaluation["final_quality"].get("passed")),
                    "after_passed": bool(rescue_eval["final_quality"].get("passed")),
                    "must_fix_before": evaluation["final_quality"].get("must_fix", []),
                    "must_fix_after": rescue_eval["final_quality"].get("must_fix", []),
                }
            )
            rewrite_round_results.append(
                {
                    "round": rescue_round,
                    "type": "rescue",
                    "result": rescue_result,
                    "quality": rescue_eval["final_quality"],
                }
            )
            if rewrite_rescue_improved:
                writer_payload = rescue_payload
                writer_result = rescue_result
                evaluation = rescue_eval

        final_quality = evaluation["final_quality"]
        writer_payload["continuity_flag"] = "ok" if final_quality.get("passed") else "needs_fix"
        writer_payload["continuity_score"] = clamp_or_default(final_quality.get("score"), 0, 0, 100)
        warnings = []
        agent_bundle = {
            "framework": first_layer_results["framework"],
            "character": first_layer_results["character"],
            "deep_primary": deep_primary_result,
            "deep_secondary": deep_secondary_result,
            "deep_referee": deep_referee_result,
            "deep": deep_final_result,
            "scene": first_layer_results["scene"],
            "writer": writer_result,
            "qa": evaluation["qa_result"],
            "memory_extractor": evaluation["memory_result"],
            "chapter_logic_audit": evaluation["chapter_logic_result"],
            "global_logic_audit": evaluation["global_logic_result"],
            "deep_quality_audit": evaluation["deep_quality_result"],
            "rewrite_rounds": rewrite_round_results,
        }
        for key, value in agent_bundle.items():
            if not isinstance(value, dict):
                continue
            if not bool(value.get("fallback")):
                continue
            error_text = normalize_text(value.get("error"))
            if self._is_transient_model_error(error_text):
                warnings.append(f"{key} 遇到限流/超时，使用了降级结果。")
        if auto_rewrite and not bool(final_quality.get("passed")):
            warnings.append("自动改写已达到轮次上限，仍存在未收敛问题，请人工复核 must_fix。")

        model_observability = self._build_model_observability(
            route_plan=route_plan,
            agent_bundle=agent_bundle,
            rewrite_trace=rewrite_trace,
        )

        return {
            "context": ctx,
            "studentProfile": ctx.get("studentProfile"),
            "routingStrategy": ctx.get("routingStrategy"),
            "knowledgeUsed": [
                {
                    "id": row.get("id"),
                    "title": row.get("title"),
                    "tags": row.get("tags"),
                }
                for row in selected_knowledge_rows
            ],
            "agents": agent_bundle,
            "chapter": writer_payload,
            "quality": final_quality,
            "logicChecks": {
                "chapter": evaluation["chapter_logic_payload"],
                "global": evaluation["global_logic_payload"],
                "deep": evaluation["deep_quality_payload"],
            },
            "rewrites": {
                "autoRewrite": auto_rewrite,
                "triggered": rewrite_triggered,
                "maxRounds": max_rewrite_rounds,
                "completedRounds": len(rewrite_trace),
                "converged": bool(final_quality.get("passed")),
                "rescueAttempted": rewrite_rescue_attempted,
                "rescueImproved": rewrite_rescue_improved,
                "trace": rewrite_trace,
            },
            "projectState": {
                "previous": normalize_project_state(ctx.get("projectState")),
                "delta": normalize_project_state(evaluation["memory_delta"]),
                "merged": evaluation["merged_state"],
            },
            "warnings": warnings[:12],
            "generatedAt": now_iso(),
            "modelObservability": model_observability,
            "model": {
                "provider": "moonshot" if self.llm.enabled() else "offline-fallback",
                "name": self.llm.model if self.llm.enabled() else "fallback-template",
                "agent_model_map": ctx.get("agentModelMap") or {},
                "deep_committee_models": ctx.get("deepCommitteeModels") or [],
                "multi_model_collab": bool(ctx.get("multiModelCollab")),
            },
        }


def build_orchestrator_from_env() -> NovelAgentOrchestrator:
    key = os.getenv("MOONSHOT_API_KEY", "")
    base_url = os.getenv("MOONSHOT_BASE_URL", "https://api.moonshot.cn/v1")
    model = os.getenv("MOONSHOT_MODEL", "kimi-k2-0905-preview")
    timeout_seconds = float(os.getenv("MOONSHOT_TIMEOUT_SECONDS", "120"))
    top_p = float(os.getenv("MOONSHOT_TOP_P", "0.95"))
    thinking_mode = os.getenv("MOONSHOT_THINKING_MODE", "thinking")
    max_retries = int(os.getenv("MOONSHOT_MAX_RETRIES", "0"))
    base_backoff_seconds = float(os.getenv("MOONSHOT_BASE_BACKOFF_SECONDS", "1.2"))
    min_interval_seconds = float(os.getenv("MOONSHOT_MIN_INTERVAL_SECONDS", "0.45"))
    llm = MoonshotClient(
        api_key=key,
        base_url=base_url,
        model=model,
        timeout_seconds=timeout_seconds,
        top_p=top_p,
        thinking_mode=thinking_mode,
        max_retries=max_retries,
        base_backoff_seconds=base_backoff_seconds,
        min_interval_seconds=min_interval_seconds,
    )
    return NovelAgentOrchestrator(llm_client=llm)
