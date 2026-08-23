"""MOSS 语音插件主入口（MOSI 官方 MossAPI，https://api.mosi.cn）。

导入 providers 包即可把 MOSS 语音 Provider 适配器注册进 AstrBot 的
Provider 注册表。注册完成后，在 WebUI「服务提供商」页面即可像添加
内置提供商一样添加它们。

已注册的适配器：
- moss_tts_cloud —— MOSS 官方单人语音生成（POST /v1/audio/speech）
- moss_stt_cloud —— MOSS 官方音频转写（POST /v1/audio/transcriptions）

插件还提供：
- WebUI 配置表单（_conf_schema.json，插件页「配置」标签页）；
- 自定义页面「settings」（pages/settings/index.html）：状态、配置、音色选择、
  参考音频克隆音色、一键同步、连通性测试；
- 启动/重载时按配置自动同步并启用 MOSS 云端 TTS/STT 服务提供商。

官方文档：https://platform.mosi.cn/docs/getting-started/overview
"""

from typing import Any

from astrbot.api import logger
from astrbot.api.star import Context, Star

# 必须导入：模块导入时通过 @register_once 装饰器完成注册。
# noqa 注释仅为抑制 IDE 的“未使用导入”提示。
from .providers.moss_stt_cloud import (  # noqa: F401
    MossSTTCloudProvider as _MossSTTCloudProvider,
)
from .providers.moss_tts_cloud import (  # noqa: F401
    MossTTSCloudProvider as _MossTTSCloudProvider,
)

PLUGIN_NAME = "astrbot_plugin_moss_voice"
PLUGIN_VERSION = "2.1.0"


class MossVoicePlugin(Star):
    """AstrBot MOSS 语音插件（MOSI 官方 MossAPI）。"""

    def __init__(self, context: Context, config: dict | None = None):
        super().__init__(context)
        # 插件配置对象（AstrBotConfig，dict 子类），由 _conf_schema.json 定义结构
        self.plugin_config = config if isinstance(config, dict) else {}
        self.page_api = None

    async def initialize(self):
        logger.info(
            "[moss_voice] 插件已加载：已注册 MOSS 官方 Provider"
            "（moss_tts_cloud / moss_stt_cloud，接口 https://api.mosi.cn）。"
        )

        # 1) 注册插件页面（WebUI）后端 API
        try:
            if hasattr(self.context, "register_web_api"):
                from .core.page_api import MossPageApi

                self.page_api = MossPageApi(self)
                self.page_api.register_routes()
                logger.info("[moss_voice] 插件页面 API 已注册（/page/*）。")
            else:
                logger.warning(
                    "[moss_voice] 当前 AstrBot 版本不支持插件页面 API，自定义页面不可用。"
                )
        except Exception as exc:
            logger.warning(f"[moss_voice] 插件页面 API 注册失败: {exc}", exc_info=True)

        # 2) 按配置自动同步服务提供商（可关闭）
        try:
            from .core.sync import auto_sync_providers

            await auto_sync_providers(self)
        except Exception as exc:
            logger.warning(f"[moss_voice] Provider 自动同步失败: {exc}", exc_info=True)
