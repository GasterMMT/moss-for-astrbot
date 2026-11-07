"""MOSS 官方语音 API 异步客户端。

只依赖 httpx，不导入 AstrBot，便于单独测试。
文档：https://platform.mosi.cn/docs/reference
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import httpx

from . import __version__

USER_AGENT = f"astrbot-moss-voice/{__version__}"


class MossAPIError(RuntimeError):
    """MOSS API 或网络错误，保留可展示给用户的中文信息。"""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        code: str = "",
        error_type: str = "",
        param: str = "",
        body: Any = None,
    ) -> None:
        self.message = str(message or "MOSS API 请求失败").strip()
        self.status_code = status_code
        self.code = str(code or "")
        self.error_type = str(error_type or "")
        self.param = str(param or "")
        self.body = body
        super().__init__(self.user_message())

    def user_message(self) -> str:
        parts = [self.message]
        if self.code:
            parts.append(f"[{self.code}]")
        if self.status_code:
            parts.append(f"HTTP {self.status_code}")
        return " ".join(parts)


@dataclass(slots=True)
class SynthesisResult:
    data: bytes
    content_type: str
    audio_format: str
    model: str
    voice_id: str
    meta: dict = field(default_factory=dict)


@dataclass(slots=True)
class VoicePage:
    voices: list[dict]
    has_more: bool = False
    next_cursor: str = ""


def _error_from_payload(payload: Any, status_code: int | None) -> MossAPIError | None:
    if not isinstance(payload, dict):
        return None
    error = payload.get("error")
    if isinstance(error, dict):
        message = (
            error.get("message")
            or payload.get("message")
            or "MOSS API 返回错误"
        )
        return MossAPIError(
            message,
            status_code=status_code,
            code=str(error.get("code") or ""),
            error_type=str(error.get("type") or ""),
            param=str(error.get("param") or ""),
            body=payload,
        )
    if isinstance(error, str) and error.strip():
        return MossAPIError(error, status_code=status_code, body=payload)
    if payload.get("status") in {"FAILED", "ERROR", "failed", "error"}:
        return MossAPIError(
            payload.get("message") or payload.get("detail") or "MOSS 任务失败",
            status_code=status_code,
            code=str(payload.get("code") or ""),
            body=payload,
        )
    return None


def _format_from_content_type(content_type: str) -> str:
    ctype = (content_type or "").split(";", 1)[0].strip().lower()
    mapping = {
        "audio/mpeg": "mp3",
        "audio/mp3": "mp3",
        "audio/wav": "wav",
        "audio/wave": "wav",
        "audio/x-wav": "wav",
        "audio/flac": "flac",
        "audio/aac": "aac",
        "audio/ogg": "ogg",
        "audio/opus": "opus",
        "audio/webm": "webm",
        "audio/mp4": "m4a",
    }
    if ctype in mapping:
        return mapping[ctype]
    if ctype.startswith("audio/"):
        return ctype.split("/", 1)[1]
    return ""


class MossClient:
    """一个轻量的 MOSS 客户端，页面 API 与 Provider 共用。"""

    def __init__(
        self,
        api_key: str,
        *,
        api_base: str = "https://api.mosi.cn",
        timeout: float = 120,
        proxy: str = "",
    ) -> None:
        self.api_key = str(api_key or "").strip()
        self.api_base = str(api_base or "https://api.mosi.cn").rstrip("/")
        self.timeout = max(10.0, min(600.0, float(timeout or 120)))
        self.proxy = str(proxy or "").strip()

        kwargs: dict[str, Any] = {
            "timeout": httpx.Timeout(self.timeout, connect=min(30.0, self.timeout)),
            "follow_redirects": True,
            "limits": httpx.Limits(max_connections=10, max_keepalive_connections=5),
        }
        if self.proxy:
            kwargs["proxy"] = self.proxy
        self._client = httpx.AsyncClient(**kwargs)

    async def __aenter__(self) -> "MossClient":
        return self

    async def __aexit__(self, *_: Any) -> None:
        await self.close()

    async def close(self) -> None:
        await self._client.aclose()

    # ------------------------------------------------------------------ 基础

    def _headers(self, *, json_body: bool = False) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
        }
        if json_body:
            headers["Content-Type"] = "application/json"
        return headers

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: dict | None = None,
        data: dict | None = None,
        files: dict | None = None,
        params: dict | None = None,
    ) -> httpx.Response:
        url = f"{self.api_base}{path}"
        try:
            response = await self._client.request(
                method,
                url,
                headers=self._headers(json_body=json_body is not None),
                json=json_body,
                data=data,
                files=files,
                params=params,
            )
        except httpx.TimeoutException as exc:
            raise MossAPIError(
                f"MOSS 请求超时（{int(self.timeout)} 秒），请检查网络或调大超时时间。"
            ) from exc
        except httpx.HTTPError as exc:
            raise MossAPIError(f"连接 MOSS 失败：{exc}") from exc

        if response.status_code >= 400:
            payload: Any = None
            try:
                payload = response.json()
            except Exception:
                payload = None
            error = _error_from_payload(payload, response.status_code)
            if error:
                raise error
            text = (response.text or "").strip()[:500]
            raise MossAPIError(
                text or f"MOSS 返回 HTTP {response.status_code}",
                status_code=response.status_code,
            )

        return response

    @staticmethod
    def _json(response: httpx.Response) -> dict:
        try:
            payload = response.json()
        except Exception as exc:
            text = (response.text or "").strip()[:500]
            raise MossAPIError(f"MOSS 返回了无法解析的内容：{text}") from exc
        error = _error_from_payload(payload, response.status_code)
        if error:
            raise error
        if not isinstance(payload, dict):
            raise MossAPIError("MOSS 返回的 JSON 不是对象。")
        return payload

    async def _download(self, url: str) -> tuple[bytes, str]:
        """下载结果文件。不向 CDN 发送 Authorization。"""
        if not url.startswith(("http://", "https://")):
            raise MossAPIError("MOSS 返回的音频地址无效。")
        kwargs: dict[str, Any] = {
            "timeout": httpx.Timeout(self.timeout, connect=20),
            "follow_redirects": True,
        }
        if self.proxy:
            kwargs["proxy"] = self.proxy
        try:
            async with httpx.AsyncClient(**kwargs) as client:
                response = await client.get(url)
                response.raise_for_status()
                return response.content, response.headers.get("content-type", "")
        except httpx.HTTPError as exc:
            raise MossAPIError(f"下载 MOSS 结果文件失败：{exc}") from exc

    # ------------------------------------------------------------------ 音色

    async def _list_voices_page(
        self, *, limit: int = 100, after: str = ""
    ) -> VoicePage:
        params: dict[str, Any] = {"limit": max(1, min(100, int(limit)))}
        if after:
            params["after"] = after
        response = await self._request("GET", "/v1/audio/voices", params=params)
        payload = self._json(response)
        raw = payload.get("data")
        voices: list[dict] = []
        if isinstance(raw, list):
            for item in raw:
                if not isinstance(item, dict) or not item.get("id"):
                    continue
                voices.append(
                    {
                        "id": str(item.get("id")),
                        "name": str(item.get("name") or "").strip(),
                        "created_at": item.get("created_at"),
                        "object": str(item.get("object") or "audio.voice"),
                    }
                )
        return VoicePage(
            voices=voices,
            has_more=bool(payload.get("has_more")),
            next_cursor=str(payload.get("next_cursor") or ""),
        )

    async def list_voices(self, limit: int = 300) -> list[dict]:
        voices: list[dict] = []
        cursor = ""
        for _ in range(6):
            page = await self._list_voices_page(limit=100, after=cursor)
            voices.extend(page.voices)
            if not page.has_more or not page.next_cursor or len(voices) >= limit:
                break
            cursor = page.next_cursor
        # 去重，保持原顺序
        seen: set[str] = set()
        unique: list[dict] = []
        for voice in voices:
            if voice["id"] in seen:
                continue
            seen.add(voice["id"])
            unique.append(voice)
        return unique[:limit]

    # ------------------------------------------------------------------ 语音合成

    async def synthesize(
        self,
        *,
        text: str,
        model: str,
        voice_id: str,
        language: str = "",
        response_format: str = "mp3",
    ) -> SynthesisResult:
        if not self.api_key:
            raise MossAPIError("未配置 MOSS API Key。")
        if not voice_id.strip():
            raise MossAPIError("未配置音色 ID（voice_id）。")
        if not text.strip():
            raise MossAPIError("待合成文本为空。")
        fmt = response_format if response_format in {"mp3", "wav"} else "mp3"
        payload: dict[str, Any] = {
            "model": model,
            "input": text,
            "voice_id": voice_id.strip(),
            "response_format": fmt,
            "delivery_method": "audio",
        }
        # language 只有 TTS 1.5 Flash 支持；Pro 传了会被严格校验拒绝。
        if language and model.startswith("moss-tts-1.5"):
            payload["language"] = language

        response = await self._request(
            "POST", "/v1/audio/speech", json_body=payload
        )
        content_type = response.headers.get("content-type", "")
        meta: dict[str, Any] = {
            "request_id": response.headers.get("x-request-id", ""),
        }

        if "json" in content_type.lower():
            data = self._json(response)
            url = data.get("url")
            if not url:
                raise MossAPIError(
                    "MOSS 返回 JSON 但没有音频 URL，请检查模型/音色配置。",
                    body=data,
                )
            audio, download_type = await self._download(str(url))
            content_type = download_type or str(
                data.get("content_type") or "audio/mpeg"
            )
            fmt = str(
                data.get("response_format") or fmt
            )
            meta.update(
                {
                    "status": data.get("status"),
                    "id": data.get("id"),
                    "remote_url": url,
                }
            )
        else:
            audio = response.content

        if not audio:
            raise MossAPIError("MOSS 返回了空音频。")

        audio_format = _format_from_content_type(content_type) or fmt
        if audio_format in {"mpeg", "mp3"}:
            audio_format = "mp3"
        if audio_format == "x-wav":
            audio_format = "wav"
        return SynthesisResult(
            data=audio,
            content_type=content_type or f"audio/{audio_format}",
            audio_format=audio_format,
            model=model,
            voice_id=voice_id,
            meta=meta,
        )

    # ------------------------------------------------------------------ 音频转写

    async def transcribe(
        self,
        *,
        data: bytes,
        filename: str,
        content_type: str,
        model: str,
        diarize: bool = False,
        keyterms: list[str] | None = None,
        response_format: str = "json",
    ) -> dict:
        if not self.api_key:
            raise MossAPIError("未配置 MOSS API Key。")
        if not data:
            raise MossAPIError("音频内容为空。")

        form: dict[str, str] = {
            "model": model,
            "response_format": response_format or "json",
        }
        is_diarize = "diarize" in model
        if diarize and is_diarize:
            form["diarize"] = "true"
        if keyterms and is_diarize:
            form["keyterms"] = json.dumps(
                [str(term) for term in keyterms if str(term).strip()],
                ensure_ascii=False,
            )

        response = await self._request(
            "POST",
            "/v1/audio/transcriptions",
            data=form,
            files={"file": (filename, data, content_type)},
        )
        content_type_header = response.headers.get("content-type", "").lower()
        text_body = (response.text or "").strip()
        if "json" not in content_type_header and not text_body.startswith(("{", "[")):
            return {"text": text_body}
        payload = self._json(response)
        if not payload.get("text") and not payload.get("segments"):
            raise MossAPIError("转写完成，但 MOSS 没有返回文本。", body=payload)
        return payload

    # ------------------------------------------------------------------ 自检

    async def test_connection(self) -> dict:
        page = await self._list_voices_page(limit=1)
        first = page.voices[0] if page.voices else None
        return {
            "voices_count_hint": len(page.voices),
            "has_more": page.has_more,
            "first_voice": first,
        }
