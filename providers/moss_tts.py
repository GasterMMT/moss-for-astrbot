"""MOSS 官方单人语音合成 Provider。"""

from __future__ import annotations

import os
from astrbot.api import logger
from astrbot.core.provider.entities import ProviderType
from astrbot.core.provider.provider import TTSProvider

from ..core.client import MossAPIError, MossClient
from ..core.config import get_api_key, normalize_config
from ._register import register_once


def _temp_path(extension: str) -> str:
    try:
        from astrbot.core.utils.astrbot_path import get_astrbot_temp_path

        directory = get_astrbot_temp_path()
    except Exception:
        import tempfile

        directory = tempfile.gettempdir()
    os.makedirs(directory, exist_ok=True)
    from uuid import uuid4

    return os.path.join(directory, f"moss_tts_{uuid4().hex}.{extension}")


@register_once(
    "moss_tts",
    "MOSS 官方单人语音合成（api.mosi.cn /v1/audio/speech）",
    provider_type=ProviderType.TEXT_TO_SPEECH,
    provider_display_name="MOSS 官方语音合成",
    default_config_tmpl={
        "id": "moss_tts",
        "type": "moss_tts",
        "provider_type": "text_to_speech",
        "enable": False,
        "api_base": "https://api.mosi.cn",
        "api_key": "",
        "proxy": "",
        "timeout": 120,
        "model": "moss-tts-1.5-flash",
        "voice_id": "",
        "language": "",
        "response_format": "mp3",
        "max_chars": 5000,
    },
)
class MossTTSProvider(TTSProvider):
    def __init__(self, provider_config: dict, provider_settings: dict | None = None) -> None:
        super().__init__(provider_config, provider_settings or {})
        config = normalize_config(
            {
                "connection": {
                    "api_key": provider_config.get("api_key", ""),
                    "api_base": provider_config.get("api_base", "https://api.mosi.cn"),
                    "proxy": provider_config.get("proxy", ""),
                    "timeout": provider_config.get("timeout", 120),
                },
                "tts": {
                    "model": provider_config.get("model", "moss-tts-1.5-flash"),
                    "voice_id": provider_config.get("voice_id", ""),
                    "language": provider_config.get("language", ""),
                    "response_format": provider_config.get("response_format", "mp3"),
                    "max_chars": provider_config.get("max_chars", 5000),
                },
            }
        )
        conn = config["connection"]
        key, _ = get_api_key(config)
        self.tts_config = config["tts"]
        self.max_chars = int(self.tts_config.get("max_chars") or 5000)
        self.client = MossClient(
            key,
            api_base=conn["api_base"],
            timeout=conn["timeout"],
            proxy=conn["proxy"],
        )
        self.set_model(str(self.tts_config["model"]))

    async def get_audio(self, text: str) -> str:
        content = (text or "").strip()
        if not content:
            raise MossAPIError("待合成文本为空。")
        if len(content) > self.max_chars:
            logger.warning(
                "[moss_tts] 文本 %s 字符超过上限 %s，已截断",
                len(content),
                self.max_chars,
            )
            content = content[: self.max_chars]

        voice_id = str(self.tts_config.get("voice_id") or "").strip()
        if not voice_id:
            raise MossAPIError(
                "尚未填写音色 ID。请到 MOSS Create 克隆音色后复制 voice_id 填入。"
            )
        result = await self.client.synthesize(
            text=content,
            model=self.model_name,
            voice_id=voice_id,
            language=str(self.tts_config.get("language") or ""),
            response_format=str(self.tts_config.get("response_format") or "mp3"),
        )
        extension = result.audio_format if result.audio_format in {"mp3", "wav"} else "mp3"
        path = _temp_path(extension)
        with open(path, "wb") as file:
            file.write(result.data)
        logger.info(
            "[moss_tts] 合成完成 model=%s voice=%s bytes=%s",
            self.model_name,
            result.voice_id,
            len(result.data),
        )
        return path

    async def terminate(self) -> None:
        try:
            await self.client.close()
        except Exception:
            pass
