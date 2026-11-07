"""把平台语音/网页上传音频整理成 MOSS 能接受的文件。

MOSS 音频转写支持 AAC/AMR/FLAC/M4A/ALAC/MOV/MP3/MP4/MPG/OGG/OPUS/WAV/
WebM/WMA，所以常见格式直接上传，不再像旧版那样一律依赖 ffmpeg 转 WAV。
只有 QQ/微信的 silk 等少数格式才需要转换。
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import mimetypes
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urlparse

import httpx

SUPPORTED_FORMATS = {
    "aac",
    "alac",
    "amr",
    "flac",
    "m4a",
    "mov",
    "mp3",
    "mp4",
    "mpg",
    "ogg",
    "opus",
    "wav",
    "webm",
    "wma",
}
MIME_BY_FORMAT = {
    "aac": "audio/aac",
    "alac": "audio/mp4",
    "amr": "audio/amr",
    "flac": "audio/flac",
    "m4a": "audio/mp4",
    "mov": "video/quicktime",
    "mp3": "audio/mpeg",
    "mp4": "video/mp4",
    "mpg": "video/mpeg",
    "ogg": "audio/ogg",
    "opus": "audio/opus",
    "wav": "audio/wav",
    "webm": "audio/webm",
    "wma": "audio/x-ms-wma",
}
EXT_BY_MIME = {
    "audio/aac": "aac",
    "audio/x-aac": "aac",
    "audio/amr": "amr",
    "audio/flac": "flac",
    "audio/x-flac": "flac",
    "audio/mp4": "m4a",
    "audio/x-m4a": "m4a",
    "audio/mpeg": "mp3",
    "audio/mp3": "mp3",
    "audio/ogg": "ogg",
    "audio/opus": "opus",
    "audio/wav": "wav",
    "audio/wave": "wav",
    "audio/x-wav": "wav",
    "audio/webm": "webm",
    "video/mp4": "mp4",
    "video/quicktime": "mov",
    "video/mpeg": "mpg",
    "audio/x-ms-wma": "wma",
}


class AudioInputError(RuntimeError):
    """无法读取或转换音频。"""


@dataclass(slots=True)
class PreparedAudio:
    data: bytes
    filename: str
    content_type: str
    audio_format: str
    source_name: str = ""
    converted: bool = False


def _normalize_ext(value: str) -> str:
    ext = (value or "").lower().strip().lstrip(".")
    if ext == "mpeg":
        return "mp3"
    if ext == "wave":
        return "wav"
    if ext == "oga":
        return "ogg"
    return ext


def sniff_audio_format(data: bytes) -> str:
    """根据文件头猜格式；猜不出返回空字符串。"""
    if not data:
        return ""
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WAVE":
        return "wav"
    if data[:3] == b"ID3" or (len(data) >= 2 and data[0] == 0xFF and data[1] & 0xE0 == 0xE0):
        # ADTS AAC 也以 FF Fx 开头，随后不是 MP3 的 layer 位。
        if len(data) >= 2 and (data[1] & 0xF6) == 0xF0:
            return "aac"
        return "mp3"
    if data[:4] == b"OggS":
        return "opus" if b"OpusHead" in data[:128] else "ogg"
    if data[:4] == b"fLaC":
        return "flac"
    if data[:4] == b"#!AM":
        return "amr"
    if data[:4] == b"\x1aE\xdf\xa3":
        return "webm"
    if data[:4] == b"0&\xb2u":
        return "wma"
    if len(data) >= 12 and data[4:8] == b"ftyp":
        brand = data[8:12]
        if brand == b"qt  ":
            return "mov"
        if brand[:3] in {b"M4A", b"M4B", b"M4P"}:
            return "m4a"
        return "mp4"
    if data[:4] in {b"\x00\x00\x01\xba", b"\x00\x00\x01\xb3"}:
        return "mpg"
    if b"#!SILK" in data[:16]:
        return "silk"
    return ""


def _guess_ext_from_name(name: str) -> str:
    ext = _normalize_ext(Path(name).suffix)
    return ext


def _guess_content_type(name: str, fmt: str) -> str:
    if fmt in MIME_BY_FORMAT:
        return MIME_BY_FORMAT[fmt]
    guessed, _ = mimetypes.guess_type(name)
    return guessed or "application/octet-stream"


def _file_uri_to_path(value: str) -> str:
    parsed = urlparse(value)
    path = unquote(parsed.path or "")
    if parsed.netloc and parsed.netloc not in {"", "localhost"}:
        path = f"//{parsed.netloc}{path}"
    if re.match(r"^/[A-Za-z]:", path):
        path = path[1:]
    return path


def _temp_dir() -> Path:
    try:
        from astrbot.core.utils.astrbot_path import get_astrbot_temp_path

        path = Path(get_astrbot_temp_path())
    except Exception:
        path = Path(tempfile.gettempdir())
    path.mkdir(parents=True, exist_ok=True)
    return path


def _write_temp(data: bytes, suffix: str) -> Path:
    directory = _temp_dir()
    fd, name = tempfile.mkstemp(prefix="moss_audio_", suffix=suffix or ".bin", dir=directory)
    os.close(fd)
    path = Path(name)
    path.write_bytes(data)
    return path


async def _convert_to_wav(data: bytes, fmt: str) -> bytes:
    """只在格式不被 MOSS 接受时使用。优先复用 AstrBot 的转换能力。"""
    src = _write_temp(data, f".{fmt or 'bin'}")
    dst: Path | None = None
    try:
        if fmt == "silk" or src.read_bytes()[:16].find(b"#!SILK") >= 0:
            try:
                from astrbot.core.utils.media_utils import ensure_wav

                converted = await ensure_wav(str(src))
            except ImportError as exc:
                raise AudioInputError(
                    "silk 音频需要 AstrBot 内置的 silk 转换器，但当前版本不可用。"
                ) from exc
            except Exception as exc:
                raise AudioInputError(f"silk 转 WAV 失败：{exc}") from exc
        else:
            try:
                from astrbot.core.utils.media_utils import convert_audio_format

                converted = await convert_audio_format(str(src), output_format="wav")
            except ImportError:
                converted = await _ffmpeg_to_wav(src)
        dst = Path(converted)
        if dst == src:
            return src.read_bytes()
        return dst.read_bytes()
    finally:
        for path in (src, dst):
            if path and path.exists():
                try:
                    path.unlink()
                except OSError:
                    pass


async def _ffmpeg_to_wav(src: Path) -> str:
    if not shutil.which("ffmpeg"):
        raise AudioInputError(
            "这个音频格式需要 ffmpeg 转成 WAV。请安装 ffmpeg，"
            "或直接上传 mp3 / wav / m4a / amr / ogg / webm。"
        )
    out = src.with_name(f"{src.stem}_moss.wav")

    def run() -> None:
        process = subprocess.run(
            [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-i",
                str(src),
                "-ar",
                "16000",
                "-ac",
                "1",
                str(out),
            ],
            capture_output=True,
            text=True,
        )
        if process.returncode != 0:
            raise AudioInputError(
                f"ffmpeg 转换失败：{(process.stderr or '').strip()[:300]}"
            )

    await asyncio.to_thread(run)
    return str(out)


async def prepare_audio_from_bytes(
    data: bytes,
    *,
    filename: str = "",
    content_type: str = "",
    max_bytes: int = 100 * 1024 * 1024,
) -> PreparedAudio:
    if not data:
        raise AudioInputError("音频内容为空。")
    if len(data) > max_bytes:
        raise AudioInputError(
            f"音频太大（{len(data) / 1024 / 1024:.1f} MB），上限 {max_bytes / 1024 / 1024:.0f} MB。"
        )

    fmt = sniff_audio_format(data)
    ext = _guess_ext_from_name(filename)
    if not fmt and ext in SUPPORTED_FORMATS | {"silk"}:
        fmt = ext
    if not fmt and content_type:
        fmt = EXT_BY_MIME.get(content_type.split(";", 1)[0].strip().lower(), "")
    if not fmt:
        raise AudioInputError(
            "无法识别这个音频格式。请上传 mp3 / wav / m4a / amr / ogg / webm。"
        )

    converted = False
    if fmt not in SUPPORTED_FORMATS:
        data = await _convert_to_wav(data, fmt)
        fmt = "wav"
        converted = True

    target_name = f"audio.{fmt}"
    return PreparedAudio(
        data=data,
        filename=target_name,
        content_type=_guess_content_type(target_name, fmt),
        audio_format=fmt,
        source_name=filename or target_name,
        converted=converted,
    )



async def _read_http(url: str, max_bytes: int) -> tuple[bytes, str, str]:
    timeout = httpx.Timeout(120, connect=30)
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            async with client.stream("GET", url) as response:
                response.raise_for_status()
                content_type = response.headers.get("content-type", "")
                length = response.headers.get("content-length")
                if length and length.isdigit() and int(length) > max_bytes:
                    raise AudioInputError("远程音频超过大小上限。")
                chunks: list[bytes] = []
                total = 0
                async for chunk in response.aiter_bytes():
                    total += len(chunk)
                    if total > max_bytes:
                        raise AudioInputError("远程音频超过大小上限。")
                    chunks.append(chunk)
                return b"".join(chunks), content_type, str(response.url)
    except httpx.HTTPError as exc:
        raise AudioInputError(f"下载音频失败：{exc}") from exc


async def prepare_audio(
    source: str,
    *,
    max_bytes: int = 100 * 1024 * 1024,
) -> PreparedAudio:
    """读取本地路径 / file:// / http(s) / base64:// / data: 形式的音频。"""
    value = str(source or "").strip()
    if not value:
        raise AudioInputError("音频地址为空。")

    if value.startswith("data:"):
        header, _, encoded = value.partition(",")
        if ";base64" not in header:
            raise AudioInputError("只支持 base64 编码的 data URI。")
        try:
            data = base64.b64decode(encoded, validate=False)
        except (ValueError, binascii.Error) as exc:
            raise AudioInputError("data URI 解码失败。") from exc
        return await prepare_audio_from_bytes(data, max_bytes=max_bytes)

    if value.startswith("base64://"):
        try:
            data = base64.b64decode(value[9:], validate=False)
        except (ValueError, binascii.Error) as exc:
            raise AudioInputError("base64 音频解码失败。") from exc
        return await prepare_audio_from_bytes(data, max_bytes=max_bytes)

    if value.startswith(("http://", "https://")):
        data, content_type, final_url = await _read_http(value, max_bytes)
        name = Path(urlparse(final_url).path).name or "audio"
        return await prepare_audio_from_bytes(
            data,
            filename=name,
            content_type=content_type,
            max_bytes=max_bytes,
        )

    if value.startswith("file://"):
        value = _file_uri_to_path(value)

    path = Path(value)
    if not path.exists() or not path.is_file():
        raise AudioInputError(f"音频文件不存在：{value}")
    if path.stat().st_size > max_bytes:
        raise AudioInputError("音频文件超过大小上限。")
    return await prepare_audio_from_bytes(
        path.read_bytes(),
        filename=path.name,
        max_bytes=max_bytes,
    )
