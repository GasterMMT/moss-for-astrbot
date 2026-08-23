"""MOSS 官方单人语音生成 Provider（MossAPI，https://api.mosi.cn）。

对齐官方文档「单人语音生成」接口：

- ``POST /v1/audio/speech``，请求体为 JSON，严格字段校验；
- 必填：``model``（moss-tts）、``input``（待合成文本）、``voice_id``（只接受音色 ID，
  不接受音色 URL / multipart / base64 / 参考音频）；
- 可选：``version``、``response_format``（mp3 / wav，默认 mp3）、
  ``delivery_method``（audio 默认返回音频二进制；url 返回 JSON 与结果 URL）、
  ``async``、``webhook_url``、``aigc_metadata``；
- ``input`` 支持内联停顿标记 ``[pause X.Ys]``（X.Y 取值 0.1 ~ 10.0）。

参考音频克隆音色请走官方流程：POST /v1/audio/voices（audio_sample）→ 得到 voice_id。

文档：https://platform.mosi.cn/docs/reference/speech
"""

import os

import httpx

from astrbot import logger
from astrbot.core.provider.entities import ProviderType
from astrbot.core.provider.provider import TTSProvider
from astrbot.core.utils.astrbot_path import get_astrbot_temp_path
from astrbot.core.utils.datetime_utils import generate_timestamp_id

from ._mosi_api import MOSI_DEFAULT_API_BASE, mosi_error_message, mosi_headers
from ._register import register_once

AUDIO_EXTENSIONS = {"mp3": ".mp3", "wav": ".wav", "pcm": ".pcm"}


@register_once(
    "moss_tts_cloud",
    "MOSS 官方单人语音生成（api.mosi.cn /v1/audio/speech，moss-tts）",
    provider_type=ProviderType.TEXT_TO_SPEECH,
    default_config_tmpl={
        "id": "moss_tts_cloud",
        "type": "moss_tts_cloud",
        "enable": False,
        # 官方 API 地址（https://api.mosi.cn）
        "api_base": MOSI_DEFAULT_API_BASE,
        # MossAPI 控制台「API 密钥」页创建的 Key
        "api_key": "",
        # 单人语音生成模型，官方取值为 moss-tts
        "model": "moss-tts",
        # 可指定已上线的模型版本，留空使用服务端默认
        "version": "",
        # 音色 ID（必填）。可通过 GET /v1/audio/voices 查询，
        # 或在插件 settings 页面一键选择内置音色 / 克隆音色
        "voice_id": "806c9695-6160-404e-8722-4f788d935af3",
        # 输出格式 mp3 / wav（官方推荐 mp3）
        "response_format": "mp3",
        # audio：直接返回音频二进制；url：返回 JSON 与结果 URL
        "delivery_method": "audio",
        "timeout": 120,
        "proxy": "",
    },
)
class MossTTSCloudProvider(TTSProvider):
    """MOSS 官方单人语音生成提供商。"""

    def __init__(self, provider_config: dict, provider_settings: dict) -> None:
        super().__init__(provider_config, provider_settings)

        self.api_base = str(
            provider_config.get("api_base") or MOSI_DEFAULT_API_BASE
        ).rstrip("/")
        self.api_key = str(provider_config.get("api_key") or "")
        self.version = str(provider_config.get("version") or "")
        self.voice_id = str(provider_config.get("voice_id") or "")
        self.response_format = str(provider_config.get("response_format") or "mp3")
        self.delivery_method = str(provider_config.get("delivery_method") or "audio")
        self.proxy = str(provider_config.get("proxy") or "")

        try:
            self.timeout = float(provider_config.get("timeout", 120))
        except (TypeError, ValueError):
            self.timeout = 120.0

        client_kwargs: dict = {"timeout": self.timeout}
        if self.proxy:
            client_kwargs["proxy"] = self.proxy
        self.client = httpx.AsyncClient(**client_kwargs)

        self.set_model(str(provider_config.get("model") or "moss-tts"))

    def _build_payload(self, text: str) -> dict:
        """按官方「单人语音生成」请求字段构造 payload（严格入参，不夹带未文档化字段）。"""
        payload: dict = {
            "model": self.model_name,
            "input": text,
            "voice_id": self.voice_id,
            "response_format": self.response_format,
            "delivery_method": self.delivery_method,
        }
        if self.version:
            payload["version"] = self.version
        return payload

    async def get_audio(self, text: str) -> str:
        """将文本合成为语音，返回本地音频文件路径。"""
        if not self.api_key:
            raise RuntimeError(
                "[MOSS-TTS] 未配置 api_key，请前往 MossAPI 控制台「API 密钥」页创建并填入配置。"
            )
        if not self.voice_id:
            raise RuntimeError(
                "[MOSS-TTS] 未配置 voice_id：官方接口要求必填音色 ID，"
                "可在插件 settings 页面选择内置音色或用参考音频克隆音色。"
            )

        url = f"{self.api_base}/v1/audio/speech"
        payload = self._build_payload(text)

        logger.info(
            f"[MOSS-TTS] 合成请求 -> voice_id={payload.get('voice_id')!r} "
            f"model={payload.get('model')!r} response_format={payload.get('response_format')!r} "
            f"delivery_method={payload.get('delivery_method')!r} text_len={len(text)}"
        )

        response = await self.client.post(
            url,
            headers=mosi_headers(self.api_key, json_body=True),
            json=payload,
        )
        response.raise_for_status()

        # delivery_method=url：JSON 携带结果 URL，需再次下载
        if self.delivery_method == "url":
            data = response.json()
            error_msg = mosi_error_message(data, response.status_code)
            if error_msg:
                raise RuntimeError(f"[MOSS-TTS] {error_msg}")
            result_url = data.get("url") if isinstance(data, dict) else None
            if not result_url:
                raise RuntimeError(f"[MOSS-TTS] 响应中缺少 url 字段: {str(data)[:300]}")
            audio_response = await self.client.get(result_url)
            audio_response.raise_for_status()
            audio_bytes = audio_response.content
            audio_format = str(data.get("response_format") or self.response_format)
        else:
            # delivery_method=audio：响应体即音频二进制
            content_type = (response.headers.get("content-type") or "").lower()
            if "json" in content_type:
                data = response.json()
                error_msg = mosi_error_message(data, response.status_code)
                if error_msg:
                    raise RuntimeError(f"[MOSS-TTS] {error_msg}")
                raise RuntimeError(
                    f"[MOSS-TTS] 返回了 JSON 而非音频: {str(data)[:300]}"
                )
            audio_bytes = response.content
            audio_format = self.response_format

        if not audio_bytes:
            raise RuntimeError("[MOSS-TTS] 服务端返回了空的音频内容。")

        ext = AUDIO_EXTENSIONS.get(audio_format, f".{audio_format}")
        temp_dir = get_astrbot_temp_path()
        os.makedirs(temp_dir, exist_ok=True)
        path = os.path.join(temp_dir, f"moss_tts_{generate_timestamp_id()}{ext}")
        with open(path, "wb") as f:
            f.write(audio_bytes)

        logger.info(f"[MOSS-TTS] 语音合成完成: {path} ({len(audio_bytes)} bytes)")
        return path

    async def terminate(self):
        try:
            await self.client.aclose()
        except Exception:
            pass
