"""把插件配置同步为 AstrBot 服务提供商（Provider）条目。

插件配置（WebUI 插件页面配置表单）是唯一事实来源：
- ``moss_tts_cloud`` / ``moss_stt_cloud`` 两个服务提供商条目按需创建/更新；
- 可选地把 AstrBot 的默认语音合成/语音识别切换到这两个提供商并开启。

启动期（provider 尚未加载）只改配置，由 AstrBot 统一加载；
运行期（插件热重载 / 页面点击同步）走 create_provider / update_provider 即时生效。
"""

from typing import Any

from astrbot.api import logger

from ..providers._mosi_api import MOSI_DEFAULT_API_BASE

TTS_PROVIDER_ID = "moss_tts_cloud"
STT_PROVIDER_ID = "moss_stt_cloud"
DEFAULT_TTS_MODEL = "moss-tts"
DEFAULT_STT_MODEL = "moss-transcribe-diarize"
# 官方内置音色（轻快灵动女声，智能客服向），voice_id 为官方接口必填
DEFAULT_VOICE_ID = "806c9695-6160-404e-8722-4f788d935af3"


def build_tts_provider_config(plugin_config: dict) -> dict:
    """根据插件配置生成 moss_tts_cloud 服务提供商配置（对齐官方请求字段）。"""
    cloud = plugin_config.get("cloud") or {}
    return {
        "id": TTS_PROVIDER_ID,
        "type": TTS_PROVIDER_ID,
        "provider_type": "text_to_speech",
        "enable": True,
        "api_base": str(cloud.get("api_base") or MOSI_DEFAULT_API_BASE),
        "api_key": str(cloud.get("api_key") or ""),
        "model": str(cloud.get("model") or DEFAULT_TTS_MODEL),
        "version": str(cloud.get("version") or ""),
        "voice_id": str(cloud.get("voice_id") or DEFAULT_VOICE_ID),
        "response_format": str(cloud.get("response_format") or "mp3"),
        "delivery_method": str(cloud.get("delivery_method") or "audio"),
        "timeout": cloud.get("timeout") or 120,
        "proxy": str(cloud.get("proxy") or ""),
    }


def build_stt_provider_config(plugin_config: dict) -> dict:
    """根据插件配置生成 moss_stt_cloud 服务提供商配置（对齐官方请求字段）。"""
    cloud = plugin_config.get("cloud") or {}
    stt = plugin_config.get("stt") or {}
    return {
        "id": STT_PROVIDER_ID,
        "type": STT_PROVIDER_ID,
        "provider_type": "speech_to_text",
        "enable": True,
        "api_base": str(cloud.get("api_base") or MOSI_DEFAULT_API_BASE),
        "api_key": str(cloud.get("api_key") or ""),
        "model": str(stt.get("model") or DEFAULT_STT_MODEL),
        "version": str(stt.get("version") or ""),
        "diarize": bool(stt.get("diarize", True)),
        "response_format": str(stt.get("response_format") or "json"),
        "include_speaker": bool(stt.get("include_speaker", True)),
        "include_timestamp": bool(stt.get("include_timestamp", False)),
        "timeout": cloud.get("timeout") or 300,
        "proxy": str(cloud.get("proxy") or ""),
    }


def is_boot_time(provider_manager: Any) -> bool:
    """provider 实例列表为空 → 尚处于启动期（provider 还未统一加载）。"""
    return not (
        getattr(provider_manager, "provider_insts", None)
        or getattr(provider_manager, "stt_provider_insts", None)
        or getattr(provider_manager, "tts_provider_insts", None)
    )


def upsert_provider_config(provider_list: list, new_config: dict) -> tuple[str, str]:
    """在配置列表中就地插入或替换条目，返回 (动作, provider id)。"""
    for idx, provider in enumerate(provider_list):
        if provider.get("id") == new_config["id"]:
            provider_list[idx] = new_config
            return "updated", new_config["id"]
    provider_list.append(new_config)
    return "created", new_config["id"]


async def sync_providers(plugin: Any) -> dict:
    """把插件配置同步到 AstrBot 服务提供商，返回结果摘要。"""
    plugin_config = plugin.plugin_config if hasattr(plugin, "plugin_config") else {}
    cloud = plugin_config.get("cloud") or {}
    sync_cfg = plugin_config.get("sync") or {}
    api_key = str(cloud.get("api_key") or "").strip()

    pm = plugin.context.provider_manager
    acm_config = pm.acm.default_conf
    provider_list = acm_config["provider"]

    plans = [
        build_tts_provider_config(plugin_config),
        build_stt_provider_config(plugin_config),
    ]

    results: list[dict] = []
    boot = is_boot_time(pm)
    for plan in plans:
        exists = any(p.get("id") == plan["id"] for p in provider_list)
        try:
            if boot:
                # 启动期：只改配置，交给 provider_manager.initialize() 统一加载
                action, pid = upsert_provider_config(provider_list, plan)
                results.append({"action": action + "(boot)", "provider_id": pid})
            elif exists:
                await pm.update_provider(plan["id"], plan)
                results.append({"action": "updated", "provider_id": plan["id"]})
            else:
                await pm.create_provider(plan)
                results.append({"action": "created", "provider_id": plan["id"]})
        except Exception as exc:
            logger.error(
                f"[moss_voice] 同步 Provider {plan['id']} 失败: {exc}", exc_info=True
            )
            results.append({"action": "failed", "provider_id": plan["id"], "error": str(exc)})

    # 可选：把 AstrBot 默认配置 + 所有配置组（abconf_*.json）的
    # 默认 TTS/STT 指向切换为 MOSS 并启用，保证任何会话/平台绑定的
    # 配置组都使用 MOSS（而不是用户历史导入的 mimo 等）。
    auto_enable = bool(sync_cfg.get("auto_enable", True))
    tts_enabled = stt_enabled = False
    confs = getattr(pm.acm, "confs", None)
    if not isinstance(confs, dict) or not confs:
        confs = {"default": acm_config}
    for conf in confs.values():
        tts_settings = conf.get("provider_tts_settings")
        if isinstance(tts_settings, dict):
            if auto_enable:
                tts_settings["enable"] = True
            tts_settings["provider_id"] = TTS_PROVIDER_ID
            tts_enabled = True
        stt_settings = conf.get("provider_stt_settings")
        if isinstance(stt_settings, dict):
            if auto_enable:
                stt_settings["enable"] = True
            stt_settings["provider_id"] = STT_PROVIDER_ID
            stt_enabled = True
        try:
            conf.save_config()
        except Exception as exc:
            logger.warning(f"[moss_voice] 保存配置 {getattr(conf, 'config_path', '?')} 失败: {exc}")

    return {
        "api_key_configured": bool(api_key),
        "results": results,
        "auto_enable": auto_enable,
        "tts_enabled": tts_enabled,
        "stt_enabled": stt_enabled,
        "boot": boot,
    }


async def auto_sync_providers(plugin: Any) -> None:
    """插件初始化时按配置自动同步（可被 auto_sync 开关关闭）。"""
    plugin_config = plugin.plugin_config if hasattr(plugin, "plugin_config") else {}
    sync_cfg = plugin_config.get("sync") or {}
    if not sync_cfg.get("auto_sync", True):
        logger.info("[moss_voice] 已关闭启动自动同步（sync.auto_sync=false）。")
        return

    cloud = plugin_config.get("cloud") or {}
    if not str(cloud.get("api_key") or "").strip():
        logger.info("[moss_voice] 未配置云端 API Key，跳过 Provider 自动同步。")
        return

    try:
        result = await sync_providers(plugin)
        logger.info(f"[moss_voice] Provider 自动同步完成: {result}")
    except Exception as exc:
        logger.error(f"[moss_voice] Provider 自动同步失败: {exc}", exc_info=True)
