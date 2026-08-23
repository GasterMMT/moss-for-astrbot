"""幂等的 Provider 适配器注册。

背景：AstrBot 热重载插件时会重新执行插件模块代码，但
``provider_cls_map`` / ``provider_registry`` 是 AstrBot 进程级全局对象，
不会随插件卸载而清空。若直接再次调用 ``register_provider_adapter``，
会抛出「适配器已注册，可能发生命名冲突」。

本模块的 ``register_once`` 在检测到同名适配器已注册时，
原地更新注册表条目（指向新加载的类），从而让插件热重载可重复执行。
"""

from typing import Any

from astrbot.core.provider.register import (
    provider_cls_map,
    register_provider_adapter,
)


def register_once(
    provider_type_name: str,
    desc: str,
    provider_type: Any,
    default_config_tmpl: dict | None = None,
    provider_display_name: str | None = None,
):
    """幂等版 ``register_provider_adapter``，热重载时原地更新而非重复注册。"""

    def decorator(cls):
        existing = provider_cls_map.get(provider_type_name)
        if existing is not None:
            # 插件热重载：更新注册表条目，指向本次新导入的类
            setattr(existing, "cls_type", cls)
            setattr(existing, "provider_type", provider_type)
            setattr(existing, "desc", desc)
            if default_config_tmpl is not None:
                default_config_tmpl.setdefault("type", provider_type_name)
                default_config_tmpl.setdefault("enable", False)
                default_config_tmpl.setdefault("id", provider_type_name)
                setattr(existing, "default_config_tmpl", default_config_tmpl)
            if provider_display_name:
                setattr(existing, "provider_display_name", provider_display_name)
            return cls

        return register_provider_adapter(
            provider_type_name,
            desc,
            provider_type=provider_type,
            default_config_tmpl=default_config_tmpl,
            provider_display_name=provider_display_name,
        )(cls)

    return decorator
