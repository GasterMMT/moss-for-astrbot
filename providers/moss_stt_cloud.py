"""MOSS 官方音频转写 Provider（MossAPI，https://api.mosi.cn）。

对齐官方文档「音频转写」接口：

- ``POST /v1/audio/transcriptions``，请求体为 multipart/form-data 或 JSON；
- 模型：``moss-transcribe``（普通转写，同步返回 { text }）/
  ``moss-transcribe-diarize``（多说话人转写，diarize=true 返回结构化 segments）；
- 输入源四选一且只传一个：``file``（multipart）/ ``file_id`` / ``url`` / ``audio_url``。
  不支持 audio_data / Base64 / 内联音频；
- 可选：``version``、``diarize``、``stream``、``response_format``（json / text）、
  ``async``、``webhook_url``。

本适配器实现：本地/远程音频统一转成 WAV 后以 multipart ``file`` 上传（官方对
``url`` 有 localhost/回环/私网限制，file 方式最稳），同步等待结果。

文档：https://platform.mosi.cn/docs/reference/transcriptions
"""

import json

import httpx

from astrbot import logger
from astrbot.core.provider.entities import ProviderType
from astrbot.core.provider.provider import STTProvider
from astrbot.core.utils.media_utils import MediaResolver

from ._mosi_api import MOSI_DEFAULT_API_BASE, mosi_error_message, mosi_headers
from ._register import register_once

_RESPONSE_FORMATS = ("json", "text")
_SUPPORTED_MODELS = ("moss-transcribe", "moss-transcribe-diarize")


@register_once(
    "moss_stt_cloud",
    "MOSS 官方音频转写（api.mosi.cn /v1/audio/transcriptions）",
    provider_type=ProviderType.SPEECH_TO_TEXT,
    default_config_tmpl={
        "id": "moss_stt_cloud",
        "type": "moss_stt_cloud",
        "enable": False,
        # 官方 API 地址（https://api.mosi.cn）
        "api_base": MOSI_DEFAULT_API_BASE,
        # MossAPI 控制台「API 密钥」页创建的 Key
        "api_key": "",
        # moss-transcribe（普通转写）/ moss-transcribe-diarize（多说话人转写）
        "model": "moss-transcribe-diarize",
        # 可指定模型版本，留空使用服务端默认
        "version": "",
        # 多说话人转写时建议开启：返回结构化 segments（说话人 + 起止时间）
        "diarize": True,
        # json：返回 JSON；text：返回纯文本
        "response_format": "json",
        # —— 以下为插件侧结果格式化选项（非官方请求字段）——
        # 结果是否带说话人标注（如 "S01: ..."）
        "include_speaker": True,
        # 结果是否带 [ss.s-ss.s] 时间戳
        "include_timestamp": False,
        "timeout": 300,
        "proxy": "",
    },
)
class MossSTTCloudProvider(STTProvider):
    """MOSS 官方音频转写提供商。"""

    def __init__(self, provider_config: dict, provider_settings: dict) -> None:
        super().__init__(provider_config, provider_settings)

        self.api_base = str(
            provider_config.get("api_base") or MOSI_DEFAULT_API_BASE
        ).rstrip("/")
        self.api_key = str(provider_config.get("api_key") or "")
        self.version = str(provider_config.get("version") or "")
        self.diarize = bool(provider_config.get("diarize", False))
        self.response_format = str(provider_config.get("response_format") or "json")
        if self.response_format not in _RESPONSE_FORMATS:
            logger.warning(
                f"[MOSS-STT] response_format {self.response_format!r} 不合法，回退为 json"
            )
            self.response_format = "json"
        self.include_speaker = bool(provider_config.get("include_speaker", True))
        self.include_timestamp = bool(provider_config.get("include_timestamp", False))
        self.proxy = str(provider_config.get("proxy") or "")

        try:
            self.timeout = float(provider_config.get("timeout", 300))
        except (TypeError, ValueError):
            self.timeout = 300.0

        client_kwargs: dict = {"timeout": self.timeout}
        if self.proxy:
            client_kwargs["proxy"] = self.proxy
        self.client = httpx.AsyncClient(**client_kwargs)

        model = str(provider_config.get("model") or "moss-transcribe-diarize")
        if model not in _SUPPORTED_MODELS:
            logger.warning(f"[MOSS-STT] 未知模型 {model!r}，按官方文档仅支持 {_SUPPORTED_MODELS}")
        self.set_model(model)

    def _build_form_data(self) -> dict:
        """官方请求字段（file 使用 multipart，其余字段用表单键值）。"""
        data = {
            "model": self.model_name,
            "response_format": self.response_format,
        }
        if self.version:
            data["version"] = self.version
        # diarize 仅在多说话人转写时开启并传入
        if self.diarize and "diarize" in self.model_name:
            data["diarize"] = "true"
        return data

    @staticmethod
    def _format_seconds(value) -> str:
        try:
            seconds = float(value)
        except (TypeError, ValueError):
            return ""
        minutes, secs = divmod(seconds, 60)
        if minutes >= 1:
            return f"{int(minutes):02d}:{secs:04.1f}"
        return f"{secs:.1f}s"

    def _parse_result(self, response: httpx.Response) -> str:
        """按 response_format 与模型解析官方响应。"""
        if self.response_format == "text":
            return response.text.strip()

        data = response.json()

        # 多说话人转写：{task, duration, text, segments[{type,id,start,end,text,speaker}]}
        segments = data.get("segments") if isinstance(data, dict) else None
        if isinstance(segments, list) and segments:
            lines = []
            for seg in segments:
                if not isinstance(seg, dict):
                    continue
                text = str(seg.get("text") or "").strip()
                if not text:
                    continue
                parts = []
                if self.include_timestamp:
                    start = seg.get("start")
                    end = seg.get("end")
                    if start is not None and end is not None:
                        parts.append(f"[{self._format_seconds(start)}-{self._format_seconds(end)}]")
                speaker = str(seg.get("speaker") or "").strip()
                if self.include_speaker and speaker:
                    parts.append(f"{speaker}:")
                parts.append(text)
                lines.append(" ".join(parts))
            if lines:
                return "\n".join(lines)

        # 普通转写：{text}
        text = data.get("text") if isinstance(data, dict) else str(data)
        return str(text or "").strip()

    async def get_text(self, audio_url: str) -> str:
        """识别音频并返回文本。audio_url 可为本地路径或 http(s) URL。

        官方对 ``url`` 字段有 localhost/回环/私网限制，因此统一先把音频
        转成 WAV 后走 multipart ``file`` 上传（需要系统安装 ffmpeg）。
        """
        if not self.api_key:
            raise RuntimeError(
                "[MOSS-STT] 未配置 api_key，请前往 MossAPI 控制台「API 密钥」页创建并填入配置。"
            )

        url = f"{self.api_base}/v1/audio/transcriptions"
        data = self._build_form_data()

        async with MediaResolver(
            audio_url,
            media_type="audio",
            default_suffix=".wav",
        ).as_path(target_format="wav") as audio_path:
            with audio_path.open("rb") as audio_file:
                response = await self.client.post(
                    url,
                    headers=mosi_headers(self.api_key),
                    data=data,
                    files={"file": ("audio.wav", audio_file, "audio/wav")},
                )
                response.raise_for_status()

                if "json" not in (response.headers.get("content-type") or "").lower():
                    # 非 JSON 内容无法按结构化解析
                    if self.response_format == "text":
                        return response.text.strip()
                    raise RuntimeError(
                        f"[MOSS-STT] 响应不是 JSON: {response.text[:300]}"
                    )

                payload = response.json()
                error_msg = mosi_error_message(payload, response.status_code)
                if error_msg:
                    raise RuntimeError(f"[MOSS-STT] {error_msg}")

                text = self._parse_result(response)

        if not text:
            raise RuntimeError(
                "[MOSS-STT] 语音识别结果为空: "
                f"{json.dumps(payload, ensure_ascii=False)[:300]}"
            )

        logger.info(f"[MOSS-STT] 识别完成，共 {len(text)} 字符。")
        return text

    async def terminate(self):
        try:
            await self.client.aclose()
        except Exception:
            pass
