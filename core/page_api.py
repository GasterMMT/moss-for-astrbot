"""插件 WebUI 后端接口。

路由前缀：/astrbot_plugin_moss_voice/page
前端通过 AstrBot 的 AstrBotPluginView bridge 调用。
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import inspect
import time
from typing import Any

from astrbot.api import logger

from . import __version__
from .audio import AudioInputError, prepare_audio_from_bytes
from .client import MossAPIError, MossClient
from .config import (
    STT_MODELS,
    TTS_MODELS,
    TTS_FORMATS,
    deep_merge,
    get_api_key,
    mask_key,
    normalize_config,
    public_config,
)
from .formatting import format_transcript, result_segments
from .provider_sync import provider_status, sync_providers

PLUGIN_NAME = "astrbot_plugin_moss_voice"
PAGE_PREFIX = f"/{PLUGIN_NAME}/page"

try:  # AstrBot 新版本推荐的 web API 封装
    from astrbot.api.web import (  # type: ignore
        error_response,
        json_response,
        request as web_request,
    )

    _WEB_V2 = True
except Exception:  # 兼容旧版 Quart 请求上下文
    from quart import request as web_request  # type: ignore

    error_response = None  # type: ignore
    json_response = None  # type: ignore
    _WEB_V2 = False


def _ok(data: Any) -> Any:
    if _WEB_V2 and json_response is not None:
        return json_response(data)
    return data


def _fail(message: str, *, status: int = 400, data: Any = None) -> Any:
    if _WEB_V2 and error_response is not None:
        return error_response(message, status_code=status, data=data)
    return {"status": "error", "message": message, "data": data}, status


def _content_type() -> str:
    try:
        return str(getattr(web_request, "content_type", "") or "")
    except Exception:
        return ""


async def _json_body() -> dict:
    try:
        if _WEB_V2:
            payload = await web_request.json(default={})
        else:
            payload = await web_request.get_json(silent=True)
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


async def _files() -> Any:
    try:
        if _WEB_V2:
            return await web_request.files()
        files = web_request.files
        if inspect.isawaitable(files):
            files = await files
        return files
    except Exception:
        return None


async def _read_upload(upload: Any) -> tuple[bytes, str, str]:
    data = upload.read()
    if inspect.isawaitable(data):
        data = await data
    return (
        bytes(data or b""),
        str(getattr(upload, "filename", "") or "audio"),
        str(getattr(upload, "content_type", "") or ""),
    )


async def _first_upload() -> tuple[bytes, str, str] | None:
    files = await _files()
    if not files:
        return None
    upload = None
    try:
        upload = files.get("file")
    except Exception:
        upload = None
    if upload is None:
        try:
            upload = next(iter(files.values()))
        except Exception:
            upload = None
    if upload is None:
        return None
    return await _read_upload(upload)


def _decode_b64(value: str) -> bytes:
    raw = str(value or "").strip()
    if raw.startswith("data:"):
        raw = raw.split(",", 1)[-1]
    try:
        return base64.b64decode(raw, validate=False)
    except (ValueError, binascii.Error) as exc:
        raise AudioInputError("base64 音频解码失败。") from exc


class MossPageApi:
    def __init__(self, plugin: Any) -> None:
        self.plugin = plugin

    # ------------------------------------------------------------------ 注册

    def register_routes(self) -> None:
        register = self.plugin.context.register_web_api
        routes = (
            ("/status", self.status, ["GET"], "MOSS 插件状态"),
            ("/config", self.get_config, ["GET"], "读取 MOSS 配置"),
            ("/config", self.save_config, ["POST"], "保存 MOSS 配置"),
            ("/test", self.test_connection, ["POST"], "测试 MOSS 连接"),
            ("/voices", self.list_voices, ["GET"], "读取音色列表"),
            ("/tts", self.synthesize, ["POST"], "TTS 测试"),
            ("/stt", self.transcribe, ["POST"], "STT 测试"),
            ("/sync", self.sync, ["POST"], "写入 AstrBot Provider"),
        )
        for suffix, handler, methods, desc in routes:
            register(f"{PAGE_PREFIX}{suffix}", handler, methods, desc)

    # ------------------------------------------------------------------ 配置

    def _cfg(self) -> dict:
        value = getattr(self.plugin, "config", None)
        return normalize_config(value if isinstance(value, dict) else {})

    async def _persist(self, cfg: dict) -> None:
        current = getattr(self.plugin, "config", None)
        if not isinstance(current, dict):
            logger.warning("[moss_voice] 当前插件没有可保存的配置对象。")
            return
        current.clear()
        current.update(cfg)
        saver = getattr(current, "save_config_async", None)
        if callable(saver):
            await saver()
            return
        saver = getattr(current, "save_config", None)
        if callable(saver):
            await asyncio.to_thread(saver)

    async def status(self) -> Any:
        cfg = self._cfg()
        key, source = get_api_key(cfg)
        return _ok(
            {
                "version": __version__,
                "config": public_config(cfg),
                "api_key_source": source,
                "providers": provider_status(self.plugin),
            }
        )

    async def get_config(self) -> Any:
        cfg = self._cfg()
        return _ok({"config": public_config(cfg, include_key=True)})

    async def save_config(self) -> Any:
        payload = await _json_body()
        incoming = payload.get("config") if isinstance(payload.get("config"), dict) else payload
        if not isinstance(incoming, dict) or not incoming:
            return _fail("请求体为空，无法保存配置。")
        base = self._cfg()
        merged = deep_merge(base, incoming)
        cfg = normalize_config(merged)
        try:
            await self._persist(cfg)
        except Exception as exc:
            logger.error("[moss_voice] 保存插件配置失败: %s", exc, exc_info=True)
            return _fail(f"保存配置失败：{exc}", status=500)

        sync_result = None
        key, _ = get_api_key(cfg)
        if key and cfg["routing"].get("auto_sync", True):
            try:
                sync_result = await asyncio.wait_for(
                    sync_providers(self.plugin), timeout=45
                )
            except asyncio.TimeoutError:
                sync_result = {
                    "ok": False,
                    "error": "同步 Provider 超时（45 秒），配置已保存。",
                }
            except Exception as exc:
                logger.error("[moss_voice] 保存后同步失败: %s", exc, exc_info=True)
                sync_result = {"ok": False, "error": str(exc)}

        return _ok(
            {
                "config": public_config(cfg, include_key=True),
                "providers": provider_status(self.plugin),
                "synced": sync_result,
            }
        )

    # ------------------------------------------------------------------ 连接

    async def test_connection(self) -> Any:
        payload = await _json_body()
        cfg = self._cfg()
        override = payload.get("connection")
        if isinstance(override, dict):
            cfg = normalize_config(deep_merge(cfg, {"connection": override}))
        key, _ = get_api_key(cfg)
        if not key:
            return _fail("请先填写 API Key。")

        started = time.monotonic()
        client = MossClient(
            key,
            api_base=cfg["connection"]["api_base"],
            timeout=min(30, cfg["connection"]["timeout"]),
            proxy=cfg["connection"]["proxy"],
        )
        try:
            info = await asyncio.wait_for(client.test_connection(), timeout=35)
        except asyncio.TimeoutError:
            return _fail("连接 MOSS 超时。", status=502)
        except MossAPIError as exc:
            return _fail(exc.user_message(), status=502, data={"code": exc.code})
        except Exception as exc:
            logger.error("[moss_voice] 测试连接失败: %s", exc, exc_info=True)
            return _fail(f"测试连接失败：{exc}", status=502)
        finally:
            await client.close()

        return _ok(
            {
                "latency_ms": int((time.monotonic() - started) * 1000),
                "api_key_masked": mask_key(key),
                "sample_voice": info.get("first_voice"),
                "has_more": info.get("has_more"),
            }
        )

    # ------------------------------------------------------------------ 音色

    async def list_voices(self) -> Any:
        cfg = self._cfg()
        key, _ = get_api_key(cfg)
        if not key:
            return _ok(
                {
                    "voices": [],
                    "source": "none",
                    "notice": "未配置 API Key，无法读取账号音色。",
                }
            )
        client = MossClient(
            key,
            api_base=cfg["connection"]["api_base"],
            timeout=min(30, cfg["connection"]["timeout"]),
            proxy=cfg["connection"]["proxy"],
        )
        try:
            voices = await asyncio.wait_for(client.list_voices(limit=300), timeout=35)
        except Exception as exc:
            logger.warning("[moss_voice] 拉取音色失败: %s", exc)
            return _ok(
                {
                    "voices": [],
                    "source": "error",
                    "error": str(exc),
                    "notice": "在线音色读取失败。",
                }
            )
        finally:
            await client.close()
        return _ok({"voices": voices, "source": "api", "count": len(voices)})

    # ------------------------------------------------------------------ 合成

    async def synthesize(self) -> Any:
        payload = await _json_body()
        text = str(payload.get("text") or "").strip()
        if not text:
            return _fail("请先输入要合成的文本。")
        cfg = self._cfg()
        tts = cfg["tts"]
        model = str(payload.get("model") or tts["model"])
        if model not in TTS_MODELS:
            return _fail(f"不支持的 TTS 模型：{model}")
        voice_id = str(payload.get("voice_id") or tts["voice_id"]).strip()
        if not voice_id:
            return _fail("请选择音色。")
        language = str(
            payload.get("language") or ""
            if "language" in payload
            else tts["language"]
        )
        fmt = str(payload.get("format") or tts["response_format"])
        if fmt not in TTS_FORMATS:
            fmt = "mp3"
        if len(text) > int(tts["max_chars"]):
            return _fail(f"文本超过 {tts['max_chars']} 字上限。")

        key, _ = get_api_key(cfg)
        if not key:
            return _fail("请先在“接线”里保存 API Key。")

        client = MossClient(
            key,
            api_base=cfg["connection"]["api_base"],
            timeout=cfg["connection"]["timeout"],
            proxy=cfg["connection"]["proxy"],
        )
        started = time.monotonic()
        try:
            result = await asyncio.wait_for(
                client.synthesize(
                    text=text,
                    model=model,
                    voice_id=voice_id,
                    language=language,
                    response_format=fmt,
                ),
                timeout=min(300, cfg["connection"]["timeout"] + 10),
            )
        except asyncio.TimeoutError:
            return _fail("语音合成超时。", status=504)
        except MossAPIError as exc:
            return _fail(exc.user_message(), status=502, data={"code": exc.code})
        except Exception as exc:
            logger.error("[moss_voice] TTS 失败: %s", exc, exc_info=True)
            return _fail(f"语音合成失败：{exc}", status=502)
        finally:
            await client.close()

        if len(result.data) > 25 * 1024 * 1024:
            return _fail("合成结果超过 25 MB，无法在页面播放。")
        return _ok(
            {
                "audio_base64": base64.b64encode(result.data).decode("ascii"),
                "mime": result.content_type,
                "format": result.audio_format,
                "bytes": len(result.data),
                "elapsed_ms": int((time.monotonic() - started) * 1000),
                "model": model,
                "voice_id": voice_id,
                "request_id": result.meta.get("request_id", ""),
            }
        )

    # ------------------------------------------------------------------ 转写

    async def transcribe(self) -> Any:
        cfg = self._cfg()
        key, _ = get_api_key(cfg)
        if not key:
            return _fail("请先在“接线”里保存 API Key。")

        content_type = _content_type()
        body: dict = {}
        filename = "audio"
        file_type = ""
        data = b""
        use_saved_settings = False

        if "multipart/form-data" in content_type.lower():
            uploaded = await _first_upload()
            if uploaded is None:
                return _fail("没有收到音频文件。")
            data, filename, file_type = uploaded
            use_saved_settings = True
        else:
            body = await _json_body()
            filename = str(body.get("filename") or "audio")
            file_type = str(body.get("content_type") or "")
            encoded = body.get("data") or body.get("audio_base64") or ""
            if not encoded:
                return _fail("没有收到音频。")
            try:
                data = _decode_b64(str(encoded))
            except AudioInputError as exc:
                return _fail(str(exc))

        if use_saved_settings:
            stt = cfg["stt"]
            model = str(stt["model"])
            diarize = bool(stt["diarize"])
            keyterms = list(stt["keyterms"])
            include_speaker = bool(stt["include_speaker"])
            include_timestamp = bool(stt["include_timestamp"])
        else:
            model = str(body.get("model") or cfg["stt"]["model"])
            diarize = bool(body.get("diarize", cfg["stt"]["diarize"]))
            keyterms = body.get("keyterms", cfg["stt"]["keyterms"])
            if isinstance(keyterms, str):
                keyterms = [item.strip() for item in keyterms.replace("，", ",").split(",")]
            if not isinstance(keyterms, list):
                keyterms = []
            include_speaker = bool(
                body.get("include_speaker", cfg["stt"]["include_speaker"])
            )
            include_timestamp = bool(
                body.get("include_timestamp", cfg["stt"]["include_timestamp"])
            )
        if model not in STT_MODELS:
            return _fail(f"不支持的 STT 模型：{model}")

        max_bytes = int(cfg["stt"]["max_upload_mb"]) * 1024 * 1024
        try:
            prepared = await prepare_audio_from_bytes(
                data,
                filename=filename,
                content_type=file_type,
                max_bytes=max_bytes,
            )
        except AudioInputError as exc:
            return _fail(str(exc))
        except Exception as exc:
            return _fail(f"处理音频失败：{exc}")

        client = MossClient(
            key,
            api_base=cfg["connection"]["api_base"],
            timeout=max(cfg["connection"]["timeout"], 180),
            proxy=cfg["connection"]["proxy"],
        )
        started = time.monotonic()
        try:
            payload = await asyncio.wait_for(
                client.transcribe(
                    data=prepared.data,
                    filename=prepared.filename,
                    content_type=prepared.content_type,
                    model=model,
                    diarize=diarize,
                    keyterms=list(keyterms or []),
                    response_format="json",
                ),
                timeout=max(200, cfg["connection"]["timeout"] + 60),
            )
        except asyncio.TimeoutError:
            return _fail("音频转写超时。", status=504)
        except MossAPIError as exc:
            return _fail(exc.user_message(), status=502, data={"code": exc.code})
        except Exception as exc:
            logger.error("[moss_voice] STT 失败: %s", exc, exc_info=True)
            return _fail(f"音频转写失败：{exc}", status=502)
        finally:
            await client.close()

        formatted = format_transcript(
            payload,
            include_speaker=include_speaker,
            include_timestamp=include_timestamp,
        )
        if not formatted:
            return _fail("转写完成，但结果为空。", status=502)
        return _ok(
            {
                "text": formatted,
                "raw_text": payload.get("text", ""),
                "segments": result_segments(payload),
                "model": model,
                "diarized": bool(diarize and "diarize" in model),
                "elapsed_ms": int((time.monotonic() - started) * 1000),
                "bytes": len(prepared.data),
                "format": prepared.audio_format,
                "converted": prepared.converted,
            }
        )

    # ------------------------------------------------------------------ 同步

    async def sync(self) -> Any:
        try:
            result = await asyncio.wait_for(sync_providers(self.plugin), timeout=45)
        except asyncio.TimeoutError:
            return _fail("同步 Provider 超时（45 秒）。", status=504)
        except Exception as exc:
            logger.error("[moss_voice] 手动同步失败: %s", exc, exc_info=True)
            return _fail(f"同步失败：{exc}", status=500)
        if not result.get("ok"):
            return _ok(
                {
                    **result,
                    "providers": provider_status(self.plugin),
                }
            )
        return _ok({**result, "providers": provider_status(self.plugin)})
