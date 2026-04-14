import math
import os
import re
import shutil
import subprocess
import tempfile
import threading
from datetime import datetime
from pathlib import Path


SUPPORTED_MEDIA_EXTS = {
    ".mp4",
    ".mov",
    ".m4v",
    ".avi",
    ".mkv",
    ".webm",
    ".mp3",
    ".wav",
    ".m4a",
    ".aac",
    ".flac",
    ".ogg",
}

DEFAULT_LOW_CONF_THRESHOLD = 0.62
DEFAULT_MODEL_SIZE = "large-v3"
DEFAULT_DEVICE = "auto"
DEFAULT_COMPUTE_TYPE = "int8"

_MODEL_LOCK = threading.Lock()
_MODEL_CACHE = {}
_FFMPEG_BIN_CACHE = None


class TranscriptionError(Exception):
    pass


def now_iso():
    return datetime.utcnow().isoformat(timespec="seconds")


def safe_filename(name):
    text = str(name or "").strip().replace("\\", "/")
    text = text.split("/")[-1]
    text = re.sub(r"[^A-Za-z0-9._-]", "_", text)
    text = re.sub(r"_+", "_", text).strip("._")
    return text or "media"


def normalize_language(language):
    text = str(language or "").strip().lower()
    if text in {"zh", "zh-cn", "zh_cn", "cn"}:
        return "zh"
    if text in {"en", "english"}:
        return "en"
    if text in {"ja", "jp", "japanese"}:
        return "ja"
    if text in {"ko", "korean"}:
        return "ko"
    return "zh"


def parse_float(value, default):
    try:
        return float(value)
    except Exception:
        return float(default)


def read_low_conf_threshold():
    return max(0.01, min(0.99, parse_float(os.getenv("TRANSCRIBE_LOW_CONF_THRESHOLD", DEFAULT_LOW_CONF_THRESHOLD), DEFAULT_LOW_CONF_THRESHOLD)))


def parse_term_text(term_text):
    lines = str(term_text or "").splitlines()
    pairs = []
    seen = set()
    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("#"):
            continue
        if "|" in line:
            source, replacement = line.split("|", 1)
        elif "\t" in line:
            source, replacement = line.split("\t", 1)
        else:
            continue
        source = source.strip()
        replacement = replacement.strip()
        if not source or not replacement:
            continue
        if source in seen:
            continue
        seen.add(source)
        pairs.append((source, replacement))
    return pairs


def merge_term_pairs(global_pairs, job_pairs):
    merged = {}
    for source, replacement in global_pairs:
        merged[str(source)] = str(replacement)
    for source, replacement in job_pairs:
        merged[str(source)] = str(replacement)
    ordered = sorted(merged.items(), key=lambda item: len(item[0]), reverse=True)
    return ordered


def _replace_word_boundary(text, source, replacement):
    pattern = re.compile(r"\b" + re.escape(source) + r"\b")
    return pattern.sub(replacement, text)


def apply_terms_to_text(text, term_pairs):
    updated = str(text or "")
    for source, replacement in term_pairs:
        if not source:
            continue
        if re.match(r"^[A-Za-z0-9_-]+$", source):
            updated = _replace_word_boundary(updated, source, replacement)
        else:
            updated = updated.replace(source, replacement)
    return re.sub(r"\s+", " ", updated).strip()


def apply_terms_to_segments(segments, term_pairs):
    if not term_pairs:
        return segments
    for segment in segments:
        segment["text"] = apply_terms_to_text(segment.get("text", ""), term_pairs)
    return segments


def _resolve_ffmpeg_bin():
    global _FFMPEG_BIN_CACHE
    if _FFMPEG_BIN_CACHE:
        return _FFMPEG_BIN_CACHE

    env_bin = str(os.getenv("TRANSCRIBE_FFMPEG_BIN", "")).strip()
    if env_bin and Path(env_bin).exists():
        _FFMPEG_BIN_CACHE = env_bin
        return _FFMPEG_BIN_CACHE

    system_bin = shutil.which("ffmpeg")
    if system_bin:
        _FFMPEG_BIN_CACHE = system_bin
        return _FFMPEG_BIN_CACHE

    try:
        import imageio_ffmpeg

        bundled_bin = imageio_ffmpeg.get_ffmpeg_exe()
        if bundled_bin and Path(bundled_bin).exists():
            _FFMPEG_BIN_CACHE = bundled_bin
            return _FFMPEG_BIN_CACHE
    except Exception:
        pass
    return ""


def ensure_ffmpeg_available():
    ffmpeg_bin = _resolve_ffmpeg_bin()
    if ffmpeg_bin:
        return ffmpeg_bin
    raise TranscriptionError(
        "未检测到 ffmpeg。已尝试系统 ffmpeg 与 imageio-ffmpeg 内置二进制，请先安装依赖："
        "./.venv/bin/python -m pip install imageio-ffmpeg"
    )


def _run_ffmpeg(args, error_prefix):
    try:
        subprocess.run(args, check=True, capture_output=True)
    except subprocess.CalledProcessError as exc:
        stderr = exc.stderr.decode("utf-8", errors="ignore") if exc.stderr else ""
        raise TranscriptionError(f"{error_prefix}：{stderr.strip() or 'ffmpeg 执行失败'}") from exc


def extract_audio_to_wav(source_media_path, audio_output_path):
    source_media = Path(source_media_path)
    audio_output = Path(audio_output_path)
    audio_output.parent.mkdir(parents=True, exist_ok=True)
    ffmpeg_bin = ensure_ffmpeg_available()
    args = [
        ffmpeg_bin,
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        str(source_media),
        "-vn",
        "-ac",
        "1",
        "-ar",
        "16000",
        str(audio_output),
    ]
    _run_ffmpeg(args, "抽取音频失败")
    return audio_output


def extract_audio_segment(full_audio_path, start_sec, end_sec, segment_audio_path):
    output = Path(segment_audio_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    ffmpeg_bin = ensure_ffmpeg_available()
    start = max(0.0, float(start_sec))
    end = max(start + 0.01, float(end_sec))
    args = [
        ffmpeg_bin,
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        str(full_audio_path),
        "-ss",
        f"{start:.3f}",
        "-to",
        f"{end:.3f}",
        "-ac",
        "1",
        "-ar",
        "16000",
        str(output),
    ]
    _run_ffmpeg(args, "切分低置信音频片段失败")
    return output


def _load_whisper_model(model_size, device, compute_type):
    try:
        from faster_whisper import WhisperModel
    except Exception as exc:
        raise TranscriptionError(f"缺少 faster-whisper 依赖：{exc}") from exc

    key = f"{model_size}|{device}|{compute_type}"
    with _MODEL_LOCK:
        if key in _MODEL_CACHE:
            return _MODEL_CACHE[key]
        model = WhisperModel(model_size, device=device, compute_type=compute_type)
        _MODEL_CACHE[key] = model
        return model


def _segment_confidence(segment):
    avg_logprob = getattr(segment, "avg_logprob", None)
    if avg_logprob is None:
        return 0.5
    try:
        confidence = 1.0 + float(avg_logprob) / 2.0
    except Exception:
        confidence = 0.5
    return max(0.0, min(1.0, confidence))


def transcribe_audio_local(audio_path, language="zh", low_conf_threshold=None, progress_callback=None):
    model_size = str(os.getenv("TRANSCRIBE_MODEL_SIZE", DEFAULT_MODEL_SIZE)).strip() or DEFAULT_MODEL_SIZE
    device = str(os.getenv("TRANSCRIBE_DEVICE", DEFAULT_DEVICE)).strip() or DEFAULT_DEVICE
    compute_type = str(os.getenv("TRANSCRIBE_COMPUTE_TYPE", DEFAULT_COMPUTE_TYPE)).strip() or DEFAULT_COMPUTE_TYPE
    threshold = read_low_conf_threshold() if low_conf_threshold is None else float(low_conf_threshold)

    model = _load_whisper_model(model_size=model_size, device=device, compute_type=compute_type)
    language = normalize_language(language)

    segments_iter, info = model.transcribe(
        str(audio_path),
        language=language,
        vad_filter=True,
        beam_size=5,
        best_of=5,
        temperature=0.0,
        condition_on_previous_text=True,
    )

    duration = float(getattr(info, "duration", 0.0) or 0.0)
    segments = []
    index = 0
    for segment in segments_iter:
        start_sec = max(0.0, float(getattr(segment, "start", 0.0) or 0.0))
        end_sec = max(start_sec, float(getattr(segment, "end", start_sec) or start_sec))
        text = re.sub(r"\s+", " ", str(getattr(segment, "text", "") or "")).strip()
        confidence = _segment_confidence(segment)
        row = {
            "segment_index": index,
            "start_sec": start_sec,
            "end_sec": end_sec,
            "text": text,
            "confidence": confidence,
            "engine": "local_whisper",
            "is_low_conf": 1 if confidence < threshold else 0,
        }
        segments.append(row)
        index += 1

        if progress_callback:
            progress_base = 20.0
            progress_span = 70.0
            if duration > 0:
                ratio = min(1.0, max(0.0, end_sec / duration))
            else:
                ratio = min(1.0, index / max(1, index + 2))
            progress_callback(progress_base + progress_span * ratio)

    if not segments:
        raise TranscriptionError("未识别出任何可用文本，请检查视频音轨是否正常")

    if duration <= 0 and segments:
        duration = max(float(seg.get("end_sec", 0.0)) for seg in segments)

    return {"segments": segments, "duration_sec": duration}


def transcribe_media_local(source_media_path, language="zh", term_pairs=None, low_conf_threshold=None, progress_callback=None):
    ensure_ffmpeg_available()

    if progress_callback:
        progress_callback(5.0)

    with tempfile.TemporaryDirectory(prefix="transcribe_local_") as tmp_dir:
        audio_path = Path(tmp_dir) / "audio_16k.wav"
        extract_audio_to_wav(source_media_path, audio_path)

        if progress_callback:
            progress_callback(15.0)

        result = transcribe_audio_local(
            audio_path=audio_path,
            language=language,
            low_conf_threshold=low_conf_threshold,
            progress_callback=progress_callback,
        )

    segments = result["segments"]
    if term_pairs:
        apply_terms_to_segments(segments, term_pairs)

    threshold = read_low_conf_threshold() if low_conf_threshold is None else float(low_conf_threshold)
    for segment in segments:
        segment["is_low_conf"] = 1 if float(segment.get("confidence", 0.0)) < threshold else 0

    if progress_callback:
        progress_callback(90.0)

    return {"segments": segments, "duration_sec": float(result.get("duration_sec", 0.0) or 0.0)}


def seconds_to_hms(seconds):
    total = max(0, int(float(seconds or 0)))
    h = total // 3600
    m = (total % 3600) // 60
    s = total % 60
    return f"{h:02d}:{m:02d}:{s:02d}"


def seconds_to_srt_timestamp(seconds):
    value = max(0.0, float(seconds or 0.0))
    ms_total = int(round(value * 1000.0))
    h = ms_total // 3600000
    m = (ms_total % 3600000) // 60000
    s = (ms_total % 60000) // 1000
    ms = ms_total % 1000
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def build_output_files(job_id, segments, output_dir):
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)

    md_path = output / f"{job_id}.md"
    txt_path = output / f"{job_id}.txt"
    srt_path = output / f"{job_id}.srt"

    lines_md = [
        "# 视频转写稿",
        "",
        f"- 任务ID: {job_id}",
        f"- 生成时间: {now_iso()}",
        "",
        "---",
        "",
    ]
    lines_txt = []
    lines_srt = []

    for idx, segment in enumerate(segments, start=1):
        start_sec = float(segment.get("start_sec", 0.0) or 0.0)
        end_sec = float(segment.get("end_sec", start_sec) or start_sec)
        text = str(segment.get("text", "") or "").strip()
        if not text:
            continue

        lines_md.append(f"[{seconds_to_hms(start_sec)}] {text}")
        lines_txt.append(text)

        lines_srt.extend(
            [
                str(idx),
                f"{seconds_to_srt_timestamp(start_sec)} --> {seconds_to_srt_timestamp(end_sec)}",
                text,
                "",
            ]
        )

    md_path.write_text("\n".join(lines_md).strip() + "\n", encoding="utf-8")
    txt_path.write_text("\n".join(lines_txt).strip() + "\n", encoding="utf-8")
    srt_path.write_text("\n".join(lines_srt).strip() + "\n", encoding="utf-8")

    return {
        "md_path": str(md_path),
        "txt_path": str(txt_path),
        "srt_path": str(srt_path),
    }


def review_low_conf_segments(source_media_path, segments, reviewer, language="zh", low_conf_threshold=None, progress_callback=None):
    threshold = read_low_conf_threshold() if low_conf_threshold is None else float(low_conf_threshold)
    low_conf_items = [seg for seg in segments if float(seg.get("confidence", 0.0) or 0.0) < threshold]
    if not low_conf_items:
        return {
            "segments": segments,
            "reviewed_count": 0,
            "updated_count": 0,
            "note": "没有低置信片段，无需复核",
        }

    ensure_ffmpeg_available()

    reviewed_count = 0
    updated_count = 0
    errors = []

    with tempfile.TemporaryDirectory(prefix="transcribe_review_") as tmp_dir:
        tmp = Path(tmp_dir)
        full_audio = tmp / "full.wav"
        extract_audio_to_wav(source_media_path, full_audio)

        total = len(low_conf_items)
        for index, segment in enumerate(low_conf_items, start=1):
            start_sec = float(segment.get("start_sec", 0.0) or 0.0)
            end_sec = float(segment.get("end_sec", start_sec) or start_sec)
            chunk_path = tmp / f"chunk_{int(segment.get('segment_index', index))}.wav"
            extract_audio_segment(full_audio, start_sec=start_sec, end_sec=end_sec, segment_audio_path=chunk_path)
            try:
                response = reviewer.review_chunk_audio(chunk_path, language=language)
                reviewed_count += 1
            except Exception as exc:
                errors.append(str(exc))
                continue

            reviewed_text = str((response or {}).get("text", "") or "").strip()
            reviewed_conf = parse_float((response or {}).get("confidence", 0.0), 0.0)
            current_text = str(segment.get("text", "") or "").strip()
            current_conf = parse_float(segment.get("confidence", 0.0), 0.0)

            should_replace = bool(reviewed_text) and (
                reviewed_conf > current_conf + 0.05
                or (current_text and reviewed_text and reviewed_text != current_text and current_conf < threshold)
            )
            if should_replace:
                segment["text"] = reviewed_text
                segment["confidence"] = max(current_conf, reviewed_conf)
                segment["engine"] = "aliyun_review"
                updated_count += 1

            segment["is_low_conf"] = 1 if float(segment.get("confidence", 0.0) or 0.0) < threshold else 0

            if progress_callback:
                progress_callback(90.0 + 8.0 * (index / max(1, total)))

    note = ""
    if errors:
        note = f"复核阶段有 {len(errors)} 个片段失败"

    return {
        "segments": segments,
        "reviewed_count": reviewed_count,
        "updated_count": updated_count,
        "note": note,
    }
