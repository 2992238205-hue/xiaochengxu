import json
import mimetypes
import os
import tempfile
import uuid
import wave
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

try:
    from backend.transcription_service import (
        TranscriptionError,
        extract_audio_segment,
        extract_audio_to_wav,
        normalize_language,
        parse_float,
    )
except Exception:
    from transcription_service import (
        TranscriptionError,
        extract_audio_segment,
        extract_audio_to_wav,
        normalize_language,
        parse_float,
    )


class KimiCloudError(TranscriptionError):
    pass


class KimiCloudTranscriber:
    """
    使用 Moonshot/Kimi 云端接口做音频转写。

    默认调用 OpenAI 兼容的 audio transcriptions endpoint：
    {MOONSHOT_BASE_URL}/audio/transcriptions
    """

    def __init__(self):
        self.api_key = str(os.getenv("MOONSHOT_API_KEY", os.getenv("KIMI_API_KEY", ""))).strip()
        self.base_url = str(os.getenv("MOONSHOT_BASE_URL", "https://api.moonshot.cn/v1")).strip().rstrip("/")
        self.model = self._normalize_model_name(
            str(
            os.getenv(
                "TRANSCRIBE_KIMI_MODEL",
                os.getenv("KIMI_25_MODEL", "kimi-thinking-preview"),
            )
        ).strip() or "kimi-thinking-preview")
        self.audio_path = str(os.getenv("TRANSCRIBE_KIMI_AUDIO_PATH", "/audio/transcriptions")).strip() or "/audio/transcriptions"
        if not self.audio_path.startswith("/"):
            self.audio_path = f"/{self.audio_path}"
        self.timeout_seconds = max(30.0, parse_float(os.getenv("TRANSCRIBE_KIMI_TIMEOUT_SECONDS", "240"), 240))
        self.chunk_seconds = max(60.0, parse_float(os.getenv("TRANSCRIBE_KIMI_CHUNK_SECONDS", "600"), 600))
        self.response_format = str(os.getenv("TRANSCRIBE_KIMI_RESPONSE_FORMAT", "verbose_json")).strip() or "verbose_json"

    def _normalize_model_name(self, raw_model):
        model = str(raw_model or "").strip()
        lowered = model.lower()
        alias_map = {
            "kimi2.5": "kimi-thinking-preview",
            "kimi 2.5": "kimi-thinking-preview",
            "kimi-2.5": "kimi-thinking-preview",
            "kimi_2.5": "kimi-thinking-preview",
            "kimi2_5": "kimi-thinking-preview",
            "2.5": "kimi-thinking-preview",
        }
        return alias_map.get(lowered, model or "kimi-thinking-preview")

    def is_ready(self):
        return bool(self.api_key)

    def provider_label(self):
        return f"Kimi Cloud ({self.model})"

    def _build_multipart(self, fields, file_field_name, file_path):
        boundary = f"----CodexBoundary{uuid.uuid4().hex}"
        data = bytearray()

        for key, value in fields.items():
            if value is None:
                continue
            text = str(value)
            data.extend(f"--{boundary}\r\n".encode("utf-8"))
            data.extend(f'Content-Disposition: form-data; name="{key}"\r\n\r\n'.encode("utf-8"))
            data.extend(text.encode("utf-8"))
            data.extend(b"\r\n")

        path = Path(file_path)
        mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        file_bytes = path.read_bytes()

        data.extend(f"--{boundary}\r\n".encode("utf-8"))
        data.extend(
            (
                f'Content-Disposition: form-data; name="{file_field_name}"; '
                f'filename="{path.name}"\r\n'
            ).encode("utf-8")
        )
        data.extend(f"Content-Type: {mime}\r\n\r\n".encode("utf-8"))
        data.extend(file_bytes)
        data.extend(b"\r\n")

        data.extend(f"--{boundary}--\r\n".encode("utf-8"))
        return f"multipart/form-data; boundary={boundary}", bytes(data)

    def _call_audio_transcription(self, audio_path, language):
        if not self.is_ready():
            raise KimiCloudError("未配置 MOONSHOT_API_KEY，请先配置 Kimi API Key")

        url = f"{self.base_url}{self.audio_path}"
        fields = {
            "model": self.model,
            "language": normalize_language(language),
            "response_format": self.response_format,
            "temperature": "0",
        }
        content_type, body = self._build_multipart(fields=fields, file_field_name="file", file_path=audio_path)

        req = Request(
            url,
            method="POST",
            data=body,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": content_type,
            },
        )
        try:
            with urlopen(req, timeout=self.timeout_seconds) as resp:
                raw = resp.read().decode("utf-8", errors="ignore")
        except HTTPError as exc:
            body_text = ""
            try:
                body_text = exc.read().decode("utf-8", errors="ignore")
            except Exception:
                body_text = ""
            raise KimiCloudError(
                f"Kimi 转写请求失败 HTTP {exc.code}: {body_text[:360] or 'no body'}"
            ) from exc
        except URLError as exc:
            raise KimiCloudError(f"Kimi 转写网络错误: {exc}") from exc
        except Exception as exc:
            raise KimiCloudError(f"Kimi 转写请求异常: {exc}") from exc

        raw = raw.strip()
        if not raw:
            raise KimiCloudError("Kimi 转写返回空响应")

        try:
            return json.loads(raw)
        except Exception:
            return {"text": raw}

    def _to_confidence(self, segment):
        conf = segment.get("confidence")
        if conf is not None:
            value = parse_float(conf, 0.9)
            return max(0.0, min(1.0, value))
        avg_logprob = segment.get("avg_logprob")
        if avg_logprob is not None:
            value = 1.0 + parse_float(avg_logprob, -0.2) / 2.0
            return max(0.0, min(1.0, value))
        return 0.9

    def _normalize_response_segments(self, payload, offset_sec, chunk_end_sec):
        items = []
        if isinstance(payload, dict):
            segments = payload.get("segments")
            if isinstance(segments, list):
                for idx, seg in enumerate(segments):
                    if not isinstance(seg, dict):
                        continue
                    text = str(seg.get("text", "") or "").strip()
                    if not text:
                        continue
                    start = offset_sec + max(0.0, parse_float(seg.get("start"), 0.0))
                    end = offset_sec + max(parse_float(seg.get("end"), 0.0), parse_float(seg.get("start"), 0.0))
                    if end < start:
                        end = start
                    items.append(
                        {
                            "segment_index": idx,
                            "start_sec": start,
                            "end_sec": end,
                            "text": text,
                            "confidence": self._to_confidence(seg),
                            "engine": "kimi_cloud",
                        }
                    )

            if not items:
                text = str(payload.get("text", "") or "").strip()
                if text:
                    items.append(
                        {
                            "segment_index": 0,
                            "start_sec": offset_sec,
                            "end_sec": max(offset_sec, float(chunk_end_sec)),
                            "text": text,
                            "confidence": 0.9,
                            "engine": "kimi_cloud",
                        }
                    )

        if not items:
            raise KimiCloudError("Kimi 转写返回结果缺少 text/segments")
        return items

    def _wav_duration(self, wav_path):
        with wave.open(str(wav_path), "rb") as wav:
            frames = wav.getnframes()
            frame_rate = wav.getframerate() or 16000
            return float(frames) / float(frame_rate)

    def transcribe_media(self, source_media_path, language="zh", progress_callback=None):
        if not self.is_ready():
            raise KimiCloudError("未配置 MOONSHOT_API_KEY，请先设置后再转写")

        language = normalize_language(language)

        if progress_callback:
            progress_callback(5.0)

        with tempfile.TemporaryDirectory(prefix="transcribe_kimi_") as tmp_dir:
            tmp = Path(tmp_dir)
            full_audio = tmp / "full_16k.wav"
            extract_audio_to_wav(source_media_path, full_audio)
            duration_sec = self._wav_duration(full_audio)

            if progress_callback:
                progress_callback(12.0)

            chunks = []
            if duration_sec <= self.chunk_seconds:
                chunks.append((0.0, duration_sec))
            else:
                start = 0.0
                while start < duration_sec:
                    end = min(duration_sec, start + self.chunk_seconds)
                    chunks.append((start, end))
                    start = end

            merged = []
            total = max(1, len(chunks))
            for idx, (start_sec, end_sec) in enumerate(chunks, start=1):
                chunk_file = tmp / f"chunk_{idx:04d}.wav"
                extract_audio_segment(full_audio, start_sec=start_sec, end_sec=end_sec, segment_audio_path=chunk_file)
                payload = self._call_audio_transcription(chunk_file, language=language)
                chunk_segments = self._normalize_response_segments(
                    payload=payload,
                    offset_sec=start_sec,
                    chunk_end_sec=end_sec,
                )
                merged.extend(chunk_segments)

                if progress_callback:
                    progress_callback(12.0 + 78.0 * (idx / total))

            if not merged:
                raise KimiCloudError("Kimi 转写未返回可用文本")

            for i, seg in enumerate(merged):
                seg["segment_index"] = i

            if progress_callback:
                progress_callback(92.0)

            return {
                "segments": merged,
                "duration_sec": float(duration_sec),
                "provider_note": f"使用 {self.provider_label()} 完成云端转写",
            }
