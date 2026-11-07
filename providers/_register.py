"""幂等的 Provider 适配器注册。

AstrBot 热重载插件时模块会重新执行，但 provider_cls_map 是进程级全局对象。
重复调用 register_provider_adapter 会抛「适配器已注册」，这里改为更新原条目。
"""

from __future__ import annotations

from typing import Any

from astrbot.core.provider.register import (
    provider_cls_map,
    provider_registry,
    register_provider_adapter,
)


def register_once(
    provider_type_name: str,
    desc: str,
    *,
    provider_type: Any,
    default_config_tmpl: dict | None = None,
    provider_display_name: str | None = None,
):
    def decorator(cls):
        existing = provider_cls_map.get(provider_type_name)
        if existing is not None:
            existing.cls_type = cls
            existing.provider_type = provider_type
            existing.desc = desc
            if provider_display_name:
                existing.provider_display_name = provider_display_name
            if default_config_tmpl is not None:
                default_config_tmpl.setdefault("type", provider_type_name)
                default_config_tmpl.setdefault("enable", False)
                default_config_tmpl.setdefault("id", provider_type_name)
                existing.default_config_tmpl = default_config_tmpl
            if existing not in provider_registry:
                provider_registry.append(existing)
            return cls

        try:
            return register_provider_adapter(
                provider_type_name,
                desc,
                provider_type=provider_type,
                default_config_tmpl=default_config_tmpl,
                provider_display_name=provider_display_name,
            )(cls)
        except TypeError:
            # 旧版 AstrBot 的 register_provider_adapter 没有 provider_display_name。
            return register_provider_adapter(
                provider_type_name,
                desc,
                provider_type=provider_type,
                default_config_tmpl=default_config_tmpl,
            )(cls)

    return decorator
