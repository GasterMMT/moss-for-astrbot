"""插件页面（WebUI）后端接口。

通过 ``context.register_web_api`` 注册 REST 接口，供插件自定义页面
（pages/settings/index.html）通过 AstrBotPluginPage 桥接调用。

接口清单（前缀 /astrbot_plugin_moss_voice/page）：
- GET  /ping     页面 API 自检
- GET  /status   插件与 AstrBot 联动状态
- GET  /config   读取当前插件配置（直接读配置文件，与插件页「配置」标签共用同一份）
- POST /config   保存插件配置（写文件 + 更新内存 + 按需同步）
- POST /sync     立即把配置同步为服务提供商条目
- POST /test-tts 单人语音生成连通性测试（返回 base64 音频）
- POST /test-stt 音频转写连通性测试（TTS → STT 回路）
- GET  /voices   音色列表（优先拉取官方 GET /v1/audio/voices，失败回退内置列表）
- POST /clone    用本地参考音频克隆音色（POST /v1/audio/voices，audio_sample）

稳定性设计：
- 配置以磁盘文件（data/config/astrbot_plugin_moss_voice_config.json）为准，
  与 AstrBot 插件页「配置」标签完全一致，避免内存对象不同步；
- 请求体解析兼容 quart request 与 asgi_runtime request 两种上下文；
- 保存后的 Provider 同步带超时保护，绝不阻塞保存请求。
"""

from __future__ import annotations

import asyncio
import base64
import copy
import json
import os
from typing import Any

import httpx
from astrbot.api import logger
from astrbot.core.utils.astrbot_path import get_astrbot_config_path
from quart import request

from ..providers._mosi_api import MOSI_DEFAULT_API_BASE, mosi_error_message, mosi_headers
from .sync import (
    STT_PROVIDER_ID,
    TTS_PROVIDER_ID,
    build_stt_provider_config,
    build_tts_provider_config,
    sync_providers,
)

PLUGIN_NAME = "astrbot_plugin_moss_voice"
PLUGIN_VERSION = "2.1.0"
PAGE_PREFIX = f"/{PLUGIN_NAME}/page"
CONFIG_FILE_NAME = f"{PLUGIN_NAME}_config.json"

# 官方内置音色（来自官方文档「查询音色列表」页，供无网络时兜底展示）
BUILTIN_VOICES = [
    {"id": "806c9695-6160-404e-8722-4f788d935af3", "name": "轻快灵动女声", "style": "智能客服、热门玩法·轻快、活泼、自然"},
    {"id": "c6c0a40a-ea82-4468-9a21-333d3c4a76f6", "name": "曼波有口音版", "style": "动漫、角色配音·轻快、可爱、搞笑"},
    {"id": "f80b6698-0066-430b-88a0-f0fb8796db34", "name": "明太祖", "style": "角色配音、影视·高冷、沉稳、霸总"},
    {"id": "ddc6e38b-6f55-4415-b21b-a88cad2cc1d9", "name": "VOX AKUMA", "style": "播客、社交媒体·慵懒、磁性、专业"},
    {"id": "7662a8a1-700c-466a-b66b-57ece9e2e231", "name": "李白", "style": "影视、人物·古风、热血"},
    {"id": "f9a1416b-d006-4b77-9581-8f0e8ec1e401", "name": "旁白Jake", "style": "角色配音、人物·沉稳、磁性、专业"},
    {"id": "faf7f550-0627-4fc6-8db0-d3bfdad49358", "name": "经验女教师", "style": "教育、社交媒体·高冷、自然"},
    {"id": "fe85a513-9bf3-4ef7-aa0b-8b2d11e4db93", "name": "少年感人声（男）", "style": "有声书、旁白·温柔、磁性、自然"},
    {"id": "0804710c-8e5e-4b67-acda-5785ef13c309", "name": "历史解说男声", "style": "有声书、影视解说·沉稳、磁性"},
    {"id": "9d1e88e9-3b9c-4992-a414-7a1cb3ff7ab5", "name": "优雅英国女士", "style": "影视、人物·温柔、磁性、自然"},
    {"id": "2fdf194e-c16e-4587-9027-0d3464e09b4e", "name": "诗词朗读", "style": "教育、旁白·沉稳、磁性、专业"},
    {"id": "133bd03b-d717-4a55-8974-7ffc9afc1b51", "name": "故宫纪录片", "style": "纪录片、旁白·沉稳、磁性、专业"},
    {"id": "26838557-6890-4505-bc7c-e8198443a141", "name": "东北虎哥", "style": "娱乐、社交媒体·搞笑、慵懒"},
    {"id": "19411508-8731-4b68-901d-7e4b8a98e23f", "name": "忧伤的秋", "style": "影视、人物·温柔、慵懒"},
    {"id": "944eb93b-3820-49f3-b2c0-4e37a31d1161", "name": "三农农业旁白", "style": "纪录片、旁白·轻快、磁性、专业"},
]


def _mask_key(api_key: str) -> str:
    if not api_key:
        return ""
    if len(api_key) <= 8:
        return "****"
    return f"{api_key[:4]}****{api_key[-4:]}"


def _config_path() -> str:
    """插件配置文件路径（与 AstrBot 插件页「配置」标签共用同一份）。"""
    return os.path.join(get_astrbot_config_path(), CONFIG_FILE_NAME)


def _read_config_file() -> dict:
    try:
        with open(_config_path(), encoding="utf-8-sig") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception as exc:
        logger.warning(f"[moss_voice] 读取插件配置文件失败: {exc}")
        return {}


def _write_config_file(data: dict) -> None:
    path = _config_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


async def _get_json_payload() -> dict:
    """兼容读取 JSON 请求体：优先 quart request，失败回退 asgi_runtime 代理。"""
    try:
        payload = await request.get_json(silent=True)
        if isinstance(payload, dict):
            return payload
    except Exception:
        pass
    try:
        from astrbot.dashboard.asgi_runtime import request as dash_request

        payload = await dash_request.get_json(silent=True)
        if isinstance(payload, dict):
            return payload
    except Exception:
        pass
    return {}


class MossPageApi:
    """MOSS 语音插件页面 API。"""

    def __init__(self, plugin: Any) -> None:
        self.plugin = plugin

    # ------------------------------------------------------------------ 注册

    def register_routes(self) -> None:
        register = self.plugin.context.register_web_api
        register(f"{PAGE_PREFIX}/ping", self.ping, ["GET"], "MOSS 页面 API 自检")
        register(f"{PAGE_PREFIX}/status", self.status, ["GET"], "MOSS 插件联动状态")
        register(f"{PAGE_PREFIX}/config", self.get_config, ["GET"], "读取插件配置")
        register(f"{PAGE_PREFIX}/config", self.save_config, ["POST"], "保存插件配置")
        register(f"{PAGE_PREFIX}/sync", self.sync, ["POST"], "同步 MOSS 服务提供商")
        register(f"{PAGE_PREFIX}/test-tts", self.test_tts, ["POST"], "TTS 连通性测试")
        register(f"{PAGE_PREFIX}/test-stt", self.test_stt, ["POST"], "STT 连通性测试")
        register(f"{PAGE_PREFIX}/voices", self.list_voices, ["GET"], "查询音色列表")
        register(f"{PAGE_PREFIX}/clone", self.clone_voice, ["POST"], "克隆音色")

    # ------------------------------------------------------------------ 自检

    async def ping(self) -> dict:
        cfg = _read_config_file()
        return {
            "ok": True,
            "plugin": PLUGIN_NAME,
            "version": PLUGIN_VERSION,
            "config_file": _config_path(),
            "config_file_exists": os.path.isfile(_config_path()),
            "config_keys": sorted(cfg.keys()),
        }

    # ------------------------------------------------------------------ 配置

    async def get_config(self) -> dict:
        """返回当前插件配置（直接读配置文件，保证与插件页「配置」标签一致）。"""
        cfg = _read_config_file()
        logger.info(f"[moss_voice] GET /page/config -> {sorted(cfg.keys())}")
        return copy.deepcopy(cfg)

    async def save_config(self) -> dict:
        """保存插件配置：写文件 + 更新内存对象 + 按需同步 Provider。"""
        payload = await _get_json_payload()
        if not payload:
            logger.warning("[moss_voice] POST /page/config 收到空请求体")
            return {"ok": False, "error": "请求体为空或格式错误"}

        sanitized = copy.deepcopy(payload)
        for section in ("cloud", "stt", "sync"):
            value = sanitized.get(section)
            if value is not None and not isinstance(value, dict):
                sanitized[section] = {}

        # 1) 写配置文件（与插件页共用，保证两边一致）
        try:
            merged = {**_read_config_file(), **sanitized}
            _write_config_file(merged)
        except Exception as exc:
            logger.error(f"[moss_voice] 写插件配置文件失败: {exc}", exc_info=True)
            return {"ok": False, "error": f"写配置文件失败: {exc}"}

        # 2) 更新内存中的配置对象（尽力而为）
        try:
            cfg = getattr(self.plugin, "plugin_config", None)
            if isinstance(cfg, dict):
                cfg.clear()
                cfg.update(merged)
                if hasattr(cfg, "save_config"):
                    cfg.save_config(replace_config=sanitized)
        except Exception as exc:
            logger.warning(f"[moss_voice] 更新内存配置对象失败（不影响文件保存）: {exc}")

        # 3) 按需同步 Provider（带超时保护，绝不阻塞保存响应）
        sync_result = None
        sync_cfg = sanitized.get("sync") or {}
        cloud = sanitized.get("cloud") or {}
        if sync_cfg.get("auto_sync", True) and str(cloud.get("api_key") or "").strip():
            try:
                sync_result = await asyncio.wait_for(
                    sync_providers(self.plugin), timeout=30
                )
            except asyncio.TimeoutError:
                sync_result = {"error": "同步超时（30s），配置已保存，可稍后手动点击「同步到服务提供商」"}
            except Exception as exc:
                logger.error(f"[moss_voice] 保存后同步失败: {exc}", exc_info=True)
                sync_result = {"error": str(exc)}

        logger.info(f"[moss_voice] POST /page/config 保存成功: {sorted(merged.keys())}")
        return {"ok": True, "saved": sorted(merged.keys()), "synced": sync_result}

    async def sync(self) -> dict:
        try:
            result = await asyncio.wait_for(sync_providers(self.plugin), timeout=30)
            logger.info(f"[moss_voice] POST /page/sync -> {result}")
            return {"ok": True, **result}
        except asyncio.TimeoutError:
            return {"ok": False, "error": "同步超时（30s），请稍后重试"}
        except Exception as exc:
            logger.error(f"[moss_voice] 手动同步失败: {exc}", exc_info=True)
            return {"ok": False, "error": str(exc)}

    # ------------------------------------------------------------------ 状态

    async def status(self) -> dict:
        cfg = _read_config_file()
        cloud = cfg.get("cloud") or {}
        api_key = str(cloud.get("api_key") or "")

        pm = self.plugin.context.provider_manager
        provider_list = pm.acm.default_conf.get("provider", [])

        def find_entry(pid: str) -> dict | None:
            return next((p for p in provider_list if p.get("id") == pid), None)

        tts_entry = find_entry(TTS_PROVIDER_ID)
        stt_entry = find_entry(STT_PROVIDER_ID)
        tts_settings = dict(pm.provider_tts_settings or {})
        stt_settings = dict(pm.provider_stt_settings or {})

        def is_loaded(pid: str, inst_list: list) -> bool:
            for inst in inst_list or []:
                try:
                    if inst.meta().id == pid:
                        return True
                except Exception:
                    continue
            return False

        return {
            "plugin_version": PLUGIN_VERSION,
            "api_key_configured": bool(api_key.strip()),
            "api_key_masked": _mask_key(api_key.strip()),
            "api_base": str(cloud.get("api_base") or MOSI_DEFAULT_API_BASE),
            "providers": {
                "tts_entry_exists": tts_entry is not None,
                "stt_entry_exists": stt_entry is not None,
                "tts_loaded": is_loaded(TTS_PROVIDER_ID, pm.tts_provider_insts),
                "stt_loaded": is_loaded(STT_PROVIDER_ID, pm.stt_provider_insts),
            },
            "astrbot_tts": {
                "enabled": bool(tts_settings.get("enable")),
                "provider_id": tts_settings.get("provider_id") or "",
                "using_moss": tts_settings.get("provider_id") == TTS_PROVIDER_ID,
            },
            "astrbot_stt": {
                "enabled": bool(stt_settings.get("enable")),
                "provider_id": stt_settings.get("provider_id") or "",
                "using_moss": stt_settings.get("provider_id") == STT_PROVIDER_ID,
            },
        }

    # ------------------------------------------------------------------ 音色

    async def _fetch_voices(self) -> list[dict]:
        """调用官方 GET /v1/audio/voices 拉取当前账号可用音色。"""
        cloud = _read_config_file().get("cloud") or {}
        api_key = str(cloud.get("api_key") or "").strip()
        api_base = str(cloud.get("api_base") or MOSI_DEFAULT_API_BASE).rstrip("/")
        proxy = str(cloud.get("proxy") or "")
        if not api_key:
            return []

        kwargs: dict = {"timeout": 15.0}
        if proxy:
            kwargs["proxy"] = proxy
        try:
            async with httpx.AsyncClient(**kwargs) as client:
                response = await client.get(
                    f"{api_base}/v1/audio/voices",
                    headers=mosi_headers(api_key),
                    params={"limit": 150},
                )
                response.raise_for_status()
                data = response.json()
                error_msg = mosi_error_message(data, response.status_code)
                if error_msg:
                    raise RuntimeError(error_msg)
                voices = []
                for item in (data.get("data") or []):
                    if not isinstance(item, dict) or not item.get("id"):
                        continue
                    voices.append(
                        {
                            "id": str(item["id"]),
                            "name": str(item.get("name") or ""),
                        }
                    )
                return voices
        except Exception as exc:
            logger.warning(f"[moss_voice] 拉取官方音色列表失败（回退内置列表）: {exc}")
            return []

    async def list_voices(self) -> dict:
        live = await self._fetch_voices()
        if live:
            voices = live
            source = "api"
        else:
            voices = BUILTIN_VOICES
            source = "builtin"
        return {"source": source, "voices": voices}

    async def clone_voice(self) -> dict:
        """官方克隆音色：POST /v1/audio/voices，参考音频用 multipart audio_sample 字段。"""
        payload = await _get_json_payload()
        if not isinstance(payload, dict):
            return {"ok": False, "error": "请求体格式错误"}

        audio_path = str(payload.get("audio_path") or "").strip()
        name = str(payload.get("name") or "").strip()
        if not audio_path:
            return {"ok": False, "error": "请填写参考音频的本地路径（AstrBot 所在机器可读）"}
        if not os.path.isfile(audio_path):
            return {"ok": False, "error": f"参考音频文件不存在: {audio_path}"}

        cloud = _read_config_file().get("cloud") or {}
        api_key = str(cloud.get("api_key") or "").strip()
        api_base = str(cloud.get("api_base") or MOSI_DEFAULT_API_BASE).rstrip("/")
        proxy = str(cloud.get("proxy") or "")
        if not api_key:
            return {"ok": False, "error": "未配置 API Key，请先保存配置"}

        kwargs: dict = {"timeout": 120.0}
        if proxy:
            kwargs["proxy"] = proxy
        try:
            async with httpx.AsyncClient(**kwargs) as client:
                form: dict = {}
                if name:
                    form["name"] = name
                with open(audio_path, "rb") as f:
                    response = await client.post(
                        f"{api_base}/v1/audio/voices",
                        headers=mosi_headers(api_key),
                        data=form,
                        files={"audio_sample": (os.path.basename(audio_path), f, "audio/wav")},
                    )
                response.raise_for_status()
                data = response.json()
                error_msg = mosi_error_message(data, response.status_code)
                if error_msg:
                    raise RuntimeError(error_msg)
                voice_id = data.get("id") if isinstance(data, dict) else None
                if not voice_id:
                    raise RuntimeError(f"克隆响应缺少 id: {str(data)[:300]}")
                return {
                    "ok": True,
                    "voice_id": str(voice_id),
                    "name": str(data.get("name") or name or ""),
                }
        except Exception as exc:
            logger.error(f"[moss_voice] 克隆音色失败: {exc}", exc_info=True)
            return {"ok": False, "error": str(exc)}

    # ------------------------------------------------------------------ 测试

    async def _make_tts_provider(self):
        from ..providers.moss_tts_cloud import MossTTSCloudProvider

        provider_config = build_tts_provider_config(_read_config_file())
        if not str(provider_config.get("api_key") or "").strip():
            raise RuntimeError(
                "未配置 API Key：请先填写 MossAPI 控制台创建的 API Key 并保存。"
            )
        return MossTTSCloudProvider(provider_config, {})

    async def test_tts(self) -> dict:
        try:
            provider = await self._make_tts_provider()
        except Exception as exc:
            return {"ok": False, "error": str(exc)}
        try:
            path = await provider.get_audio(
                "你好！我是 MOSS 语音助手，这是一段语音合成测试。"
            )
            with open(path, "rb") as f:
                b64 = base64.b64encode(f.read()).decode("ascii")
            ext = os.path.splitext(path)[1].lstrip(".") or "mp3"
            return {
                "ok": True,
                "audio_base64": b64,
                "audio_mime": f"audio/{ext}",
                "audio_path": path,
            }
        except Exception as exc:
            logger.error(f"[moss_voice] TTS 测试失败: {exc}", exc_info=True)
            return {"ok": False, "error": str(exc)}
        finally:
            await provider.terminate()

    async def test_stt(self) -> dict:
        try:
            tts = await self._make_tts_provider()
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

        from ..providers.moss_stt_cloud import MossSTTCloudProvider

        stt = MossSTTCloudProvider(build_stt_provider_config(_read_config_file()), {})
        try:
            wav_path = await tts.get_audio("你好，这是 MOSS 语音识别测试。")
            text = await stt.get_text(wav_path)
            return {"ok": True, "text": text}
        except Exception as exc:
            logger.error(f"[moss_voice] STT 测试失败: {exc}", exc_info=True)
            return {"ok": False, "error": str(exc)}
        finally:
            await tts.terminate()
            await stt.terminate()
