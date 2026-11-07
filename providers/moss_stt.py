"""MOSS 官方音频转写 Provider。"""

from __future__ import annotations

from astrbot.api import logger
from astrbot.core.provider.entities import ProviderType
from astrbot.core.provider.provider import STTProvider

from ..core.audio import AudioInputError, prepare_audio
from ..core.client import MossAPIError, MossClient
from ..core.config import get_api_key, normalize_config
from ..core.formatting import format_transcript
from ._register import register_once


@register_once(
    "moss_stt",
    "MOSS 官方音频转写（api.mosi.cn /v1/audio/transcriptions）",
    provider_type=ProviderType.SPEECH_TO_TEXT,
    provider_display_name="MOSS 官方音频转写",
    default_config_tmpl={
        "id": "moss_stt",
        "type": "moss_stt",
        "provider_type": "speech_to_text",
        "enable": False,
        "api_base": "https://api.mosi.cn",
        "api_key": "",
        "proxy": "",
        "timeout": 180,
        "model": "moss-transcribe-1.0",
        "diarize": True,
        "keyterms": [],
        "include_speaker": True,
        "include_timestamp": False,
        "max_upload_mb": 100,
    },
)
class MossSTTProvider(STTProvider):
    def __init__(self, provider_config: dict, provider_settings: dict | None = None) -> None:
        super().__init__(provider_config, provider_settings or {})
        config = normalize_config(
            {
                "connection": {
                    "api_key": provider_config.get("api_key", ""),
                    "api_base": provider_config.get("api_base", "https://api.mosi.cn"),
                    "proxy": provider_config.get("proxy", ""),
                    "timeout": provider_config.get("timeout", 180),
                },
                "stt": {
                    "model": provider_config.get("model", "moss-transcribe-1.0"),
                    "diarize": provider_config.get("diarize", True),
                    "keyterms": provider_config.get("keyterms", []),
                    "include_speaker": provider_config.get("include_speaker", True),
                    "include_timestamp": provider_config.get("include_timestamp", False),
                    "max_upload_mb": provider_config.get("max_upload_mb", 100),
                },
            }
        )
        conn = config["connection"]
        key, _ = get_api_key(config)
        self.stt_config = config["stt"]
        self.max_upload_bytes = int(self.stt_config["max_upload_mb"]) * 1024 * 1024
        self.client = MossClient(
            key,
            api_base=conn["api_base"],
            timeout=conn["timeout"],
            proxy=conn["proxy"],
        )
        self.set_model(str(self.stt_config["model"]))

    async def get_text(self, audio_url: str) -> str:
        try:
            prepared = await prepare_audio(
                str(audio_url), max_bytes=self.max_upload_bytes
            )
        except AudioInputError:
            raise
        except Exception as exc:
            raise AudioInputError(f"读取音频失败：{exc}") from exc

        payload = await self.client.transcribe(
            data=prepared.data,
            filename=prepared.filename,
            content_type=prepared.content_type,
            model=self.model_name,
            diarize=bool(self.stt_config.get("diarize")),
            keyterms=list(self.stt_config.get("keyterms") or []),
            response_format="json",
        )
        text = format_transcript(
            payload,
            include_speaker=bool(self.stt_config.get("include_speaker", True)),
            include_timestamp=bool(self.stt_config.get("include_timestamp", False)),
        )
        if not text:
            raise MossAPIError("转写完成，但结果为空。", body=payload)
        logger.info(
            "[moss_stt] 转写完成 model=%s bytes=%s chars=%s",
            self.model_name,
            len(prepared.data),
            len(text),
        )
        return text

    async def terminate(self) -> None:
        try:
            await self.client.close()
        except Exception:
            pass
