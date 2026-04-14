import base64
import json
import os
from pathlib import Path
from urllib.request import Request, urlopen


class AliyunReviewError(Exception):
    pass


class AliyunSegmentReviewer:
    """
    阿里云低置信复核适配层。

    为避免把阿里云鉴权细节硬编码在仓库里，这里使用可配置网关方式：
    - 必填：ALIYUN_ASR_ACCESS_KEY_ID / ALIYUN_ASR_ACCESS_KEY_SECRET / ALIYUN_ASR_APP_KEY
    - 复核网关：ALIYUN_ASR_REVIEW_ENDPOINT
    - 可选：ALIYUN_ASR_BEARER_TOKEN

    网关返回 JSON 需至少包含 text 字段，可选 confidence 字段。
    """

    def __init__(self):
        self.access_key_id = str(os.getenv("ALIYUN_ASR_ACCESS_KEY_ID", "")).strip()
        self.access_key_secret = str(os.getenv("ALIYUN_ASR_ACCESS_KEY_SECRET", "")).strip()
        self.app_key = str(os.getenv("ALIYUN_ASR_APP_KEY", "")).strip()
        self.region = str(os.getenv("ALIYUN_ASR_REGION", "cn-shanghai")).strip() or "cn-shanghai"
        self.endpoint = str(os.getenv("ALIYUN_ASR_REVIEW_ENDPOINT", "")).strip()
        self.bearer_token = str(os.getenv("ALIYUN_ASR_BEARER_TOKEN", "")).strip()

    def is_configured(self):
        return bool(self.access_key_id and self.access_key_secret and self.app_key)

    def is_ready(self):
        return self.is_configured() and bool(self.endpoint)

    def _extract_text_confidence(self, payload):
        if not isinstance(payload, dict):
            return "", 0.0

        for key in ("text", "transcript", "result", "sentence", "recognized_text"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                conf = payload.get("confidence", payload.get("score", 0.0))
                try:
                    conf_value = float(conf)
                except Exception:
                    conf_value = 0.0
                return value.strip(), max(0.0, min(1.0, conf_value))

        for value in payload.values():
            if isinstance(value, dict):
                text, conf = self._extract_text_confidence(value)
                if text:
                    return text, conf

        return "", 0.0

    def review_chunk_audio(self, chunk_audio_path, language="zh"):
        if not self.is_configured():
            raise AliyunReviewError("阿里云复核未配置，缺少 AK/SK/AppKey")
        if not self.endpoint:
            raise AliyunReviewError("缺少 ALIYUN_ASR_REVIEW_ENDPOINT，无法发起复核请求")

        path = Path(chunk_audio_path)
        if not path.exists() or not path.is_file():
            raise AliyunReviewError("复核音频片段不存在")

        audio_bytes = path.read_bytes()
        if not audio_bytes:
            raise AliyunReviewError("复核音频片段为空")

        payload = {
            "appKey": self.app_key,
            "region": self.region,
            "language": str(language or "zh").strip().lower() or "zh",
            "format": "wav",
            "sampleRate": 16000,
            "audioBase64": base64.b64encode(audio_bytes).decode("ascii"),
        }

        headers = {
            "Content-Type": "application/json",
            "X-Aliyun-Access-Key-Id": self.access_key_id,
            "X-Aliyun-Access-Key-Secret": self.access_key_secret,
        }
        if self.bearer_token:
            headers["Authorization"] = f"Bearer {self.bearer_token}"

        req = Request(
            self.endpoint,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers=headers,
            method="POST",
        )

        try:
            with urlopen(req, timeout=45) as resp:
                body = resp.read().decode("utf-8", errors="ignore")
        except Exception as exc:
            raise AliyunReviewError(f"阿里云复核请求失败：{exc}") from exc

        try:
            data = json.loads(body)
        except Exception as exc:
            raise AliyunReviewError("阿里云复核返回非 JSON 响应") from exc

        text, confidence = self._extract_text_confidence(data)
        if not text:
            raise AliyunReviewError("阿里云复核结果缺少 text 字段")

        return {"text": text, "confidence": confidence}
