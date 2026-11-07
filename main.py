"""MOSS 语音接入 —— AstrBot TTS / STT 插件入口。"""

from __future__ import annotations

from astrbot.api import logger
from astrbot.api.star import Context, Star

from .core import __version__
from .core.config import get_api_key, migrate_legacy_config, normalize_config
from .core.provider_sync import sync_providers

# 导入即注册 Provider（模块级注册，方便 AstrBot 在加载 Provider 前识别类型）
from .providers import moss_stt as _moss_stt
from .providers import moss_tts as _moss_tts

_PROVIDER_MODULES = (_moss_stt, _moss_tts)

PLUGIN_NAME = "astrbot_plugin_moss_voice"


class MossVoicePlugin(Star):
    def __init__(self, context: Context, config: dict | None = None) -> None:
        super().__init__(context)
        self.config = config if isinstance(config, dict) else {}
        self.page_api = None

    async def initialize(self) -> None:
        # 旧版 cloud / stt / sync 配置迁移到 v3 结构
        try:
            if migrate_legacy_config(self.config):
                cfg = normalize_config(self.config)
                self.config.clear()
                self.config.update(cfg)
                saver = getattr(self.config, "save_config_async", None)
                if callable(saver):
                    await saver()
                else:
                    saver = getattr(self.config, "save_config", None)
                    if callable(saver):
                        saver()
                logger.info("[moss_voice] 已迁移旧版插件配置。")
        except Exception as exc:
            logger.warning("[moss_voice] 旧配置迁移失败: %s", exc)

        try:
            from .core.page_api import MossPageApi

            self.page_api = MossPageApi(self)
            self.page_api.register_routes()
        except Exception as exc:
            logger.error("[moss_voice] 页面 API 注册失败: %s", exc, exc_info=True)

        cfg = normalize_config(self.config)
        key, _ = get_api_key(cfg)
        if key and cfg["routing"].get("auto_sync", True):
            try:
                result = await sync_providers(self)
                if result.get("ok"):
                    logger.info(
                        "[moss_voice] Provider 自动同步完成：%s",
                        [item.get("action") for item in result.get("results", [])],
                    )
                else:
                    logger.warning("[moss_voice] Provider 自动同步未完成：%s", result.get("error"))
            except Exception as exc:
                logger.warning("[moss_voice] Provider 自动同步失败: %s", exc, exc_info=True)

        logger.info(
            "[moss_voice] v%s 已加载（TTS: moss_tts / STT: moss_stt）。",
            __version__,
        )
