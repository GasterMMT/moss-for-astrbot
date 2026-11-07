"""把插件配置写入 AstrBot 的 TTS / STT Provider 体系。"""

from __future__ import annotations

import asyncio
from typing import Any

from astrbot.api import logger
from astrbot.core.provider.entities import ProviderType

from .config import (
    build_stt_provider_config,
    build_tts_provider_config,
    get_api_key,
    normalize_config,
)

TTS_PROVIDER_ID = "moss_tts"
STT_PROVIDER_ID = "moss_stt"


def _find_entry(entries: list, provider_id: str) -> dict | None:
    for entry in entries:
        if isinstance(entry, dict) and entry.get("id") == provider_id:
            return entry
    return None


def _upsert_entry(entries: list, plan: dict) -> str:
    existing = _find_entry(entries, plan["id"])
    if existing is None:
        entries.append(plan)
        return "created"
    if existing.get("type") not in (None, plan["type"]):
        raise ValueError(
            f"已存在同 ID 的不同类型 Provider：{plan['id']} / {existing.get('type')}"
        )
    if existing.get("provider_type") not in (None, plan["provider_type"]):
        raise ValueError(
            f"已存在同 ID 的不同能力 Provider：{plan['id']} / {existing.get('provider_type')}"
        )
    for idx, entry in enumerate(entries):
        if entry is existing:
            entries[idx] = plan
            break
    return "updated"


def _is_boot_time(pm: Any) -> bool:
    """ProviderManager 尚未 initialize 时，Config 列表还会被统一加载。"""
    return not getattr(pm, "inst_map", None)


async def sync_providers(plugin: Any) -> dict:
    cfg = normalize_config(getattr(plugin, "config", {}))
    key, key_source = get_api_key(cfg)
    if not key:
        return {
            "ok": False,
            "error": "未配置 API Key。",
            "results": [],
            "routing": {},
        }

    pm = getattr(plugin.context, "provider_manager", None)
    if pm is None:
        return {"ok": False, "error": "当前 AstrBot 没有 ProviderManager。", "results": []}

    tts_plan = build_tts_provider_config(cfg)
    stt_plan = build_stt_provider_config(cfg)
    if key_source == "env" and not tts_plan.get("api_key"):
        tts_plan["api_key"] = key
        stt_plan["api_key"] = key

    conf = pm.acm.default_conf
    entries = conf.setdefault("provider", [])
    boot = _is_boot_time(pm)
    results: list[dict] = []

    for plan in (tts_plan, stt_plan):
        try:
            existing = _find_entry(entries, plan["id"])
            if boot:
                action = _upsert_entry(entries, plan)
            elif existing is None:
                await pm.create_provider(plan)
                action = "created"
            else:
                await pm.update_provider(plan["id"], plan)
                action = "updated"
            results.append(
                {
                    "provider_id": plan["id"],
                    "provider_type": plan["provider_type"],
                    "action": action,
                }
            )
        except Exception as exc:
            logger.error(
                "[moss_voice] 同步 Provider %s 失败: %s",
                plan["id"],
                exc,
                exc_info=True,
            )
            results.append(
                {
                    "provider_id": plan["id"],
                    "provider_type": plan["provider_type"],
                    "action": "failed",
                    "error": str(exc),
                }
            )

    auto_enable = bool(cfg["routing"].get("auto_enable"))
    routing_result: dict[str, Any] = {"auto_enable": auto_enable, "switched": []}
    if auto_enable and all(item.get("action") != "failed" for item in results):
        tts_settings = conf.setdefault("provider_tts_settings", {})
        stt_settings = conf.setdefault("provider_stt_settings", {})
        tts_settings["provider_id"] = tts_plan["id"]
        tts_settings["enable"] = True
        stt_settings["provider_id"] = stt_plan["id"]
        stt_settings["enable"] = True

        if boot:
            # 启动阶段 Provider 还没加载，只能先把选择写入共享存储；
            # ProviderManager.initialize() 会读取这两个 key。
            try:
                from astrbot.core import sp

                await sp.put_async(
                    key="curr_provider_tts",
                    value=tts_plan["id"],
                    scope="global",
                    scope_id="global",
                )
                await sp.put_async(
                    key="curr_provider_stt",
                    value=stt_plan["id"],
                    scope="global",
                    scope_id="global",
                )
                routing_result["switched"] = [tts_plan["id"], stt_plan["id"]]
            except Exception as exc:
                logger.warning("[moss_voice] 启动期写入默认 Provider 失败: %s", exc)
        else:
            for provider_id, provider_type in (
                (tts_plan["id"], ProviderType.TEXT_TO_SPEECH),
                (stt_plan["id"], ProviderType.SPEECH_TO_TEXT),
            ):
                try:
                    await pm.set_provider(provider_id, provider_type)
                    routing_result["switched"].append(provider_id)
                except Exception as exc:
                    logger.warning(
                        "[moss_voice] 切换默认 Provider %s 失败: %s",
                        provider_id,
                        exc,
                    )
                    routing_result.setdefault("errors", []).append(
                        f"{provider_id}: {exc}"
                    )

    try:
        if hasattr(conf, "save_config"):
            await asyncio.to_thread(conf.save_config)
    except Exception as exc:
        logger.warning("[moss_voice] 保存 AstrBot 配置失败: %s", exc)
        return {
            "ok": False,
            "error": f"Provider 已加载，但保存配置失败：{exc}",
            "results": results,
            "routing": routing_result,
        }

    return {
        "ok": not any(item.get("action") == "failed" for item in results),
        "boot": boot,
        "results": results,
        "routing": routing_result,
    }


def provider_status(plugin: Any) -> dict:
    cfg = normalize_config(getattr(plugin, "config", {}))
    pm = getattr(plugin.context, "provider_manager", None)
    tts_id = cfg["routing"]["tts_provider_id"]
    stt_id = cfg["routing"]["stt_provider_id"]

    if pm is None:
        return {
            "available": False,
            "tts": {"id": tts_id, "exists": False, "loaded": False},
            "stt": {"id": stt_id, "exists": False, "loaded": False},
            "routing": {},
        }

    conf = pm.acm.default_conf
    entries = conf.get("provider", [])
    tts_entry = _find_entry(entries, tts_id)
    stt_entry = _find_entry(entries, stt_id)
    tts_settings = dict(conf.get("provider_tts_settings") or {})
    stt_settings = dict(conf.get("provider_stt_settings") or {})

    def one(entry: dict | None, settings: dict, provider_id: str) -> dict:
        return {
            "id": provider_id,
            "exists": entry is not None,
            "enabled": bool(entry.get("enable")) if entry else False,
            "loaded": provider_id in getattr(pm, "inst_map", {}),
            "selected": settings.get("provider_id") == provider_id,
            "routing_enabled": bool(settings.get("enable")),
            "model": (entry or {}).get("model", ""),
        }

    key, source = get_api_key(cfg)
    return {
        "available": True,
        "api_key_configured": bool(key),
        "api_key_source": source,
        "tts": one(tts_entry, tts_settings, tts_id),
        "stt": one(stt_entry, stt_settings, stt_id),
        "current_tts": tts_settings.get("provider_id", ""),
        "current_stt": stt_settings.get("provider_id", ""),
    }
