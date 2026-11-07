from __future__ import annotations

import json
import sys
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.audio import prepare_audio_from_bytes, sniff_audio_format  # noqa: E402
from core.client import MossAPIError, MossClient  # noqa: E402
from core.config import (  # noqa: E402
    build_stt_provider_config,
    build_tts_provider_config,
    migrate_legacy_config,
    normalize_config,
)
from core.formatting import format_transcript  # noqa: E402


def wav_bytes() -> bytes:
    return b"RIFF" + (36).to_bytes(4, "little") + b"WAVEfmt " + b"\x00" * 40


async def test_tts_binary(monkeypatch):
    captured = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["json"] = json.loads(request.content)
        return httpx.Response(200, content=b"ID3fake-audio", headers={"content-type": "audio/mpeg"})

    client = MossClient("test-key", api_base="https://api.mosi.cn")
    await client._client.aclose()
    client._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        result = await client.synthesize(
            text="你好",
            model="moss-tts-1.5-flash",
            voice_id="voice-1",
            language="Chinese",
        )
    finally:
        await client.close()

    assert captured["url"].endswith("/v1/audio/speech")
    assert captured["json"]["input"] == "你好"
    assert captured["json"]["voice_id"] == "voice-1"
    assert captured["json"]["delivery_method"] == "audio"
    assert captured["json"]["language"] == "Chinese"
    assert result.audio_format == "mp3"
    assert result.data == b"ID3fake-audio"


async def test_tts_url_response(monkeypatch):
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "id": "speech-1",
                "status": "SUCCESS",
                "url": "https://cdn.example.com/out.wav",
                "response_format": "wav",
                "content_type": "audio/wav",
            },
            headers={"content-type": "application/json"},
        )

    async def fake_download(url: str) -> tuple[bytes, str]:
        assert url == "https://cdn.example.com/out.wav"
        return b"RIFFwav", "audio/wav"

    client = MossClient("test-key")
    await client._client.aclose()
    client._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(client, "_download", fake_download)
    try:
        result = await client.synthesize(
            text="hello",
            model="moss-tts-1.0-pro",
            voice_id="voice-1",
        )
    finally:
        await client.close()

    assert result.data == b"RIFFwav"
    assert result.audio_format == "wav"
    assert result.meta["status"] == "SUCCESS"


async def test_api_error_is_readable():
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            401,
            json={
                "error": {
                    "message": "invalid api key",
                    "type": "authentication_error",
                    "code": "invalid_api_key",
                }
            },
        )

    client = MossClient("bad")
    await client._client.aclose()
    client._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(MossAPIError) as exc_info:
            await client.test_connection()
    finally:
        await client.close()
    assert exc_info.value.status_code == 401
    assert exc_info.value.code == "invalid_api_key"
    assert "invalid api key" in str(exc_info.value)


async def test_transcribe_multipart():
    captured = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = request.content
        return httpx.Response(
            200,
            json={
                "text": "你好",
                "segments": [
                    {"speaker": "S01", "start": 0.1, "end": 1.2, "text": "你好"}
                ],
            },
        )

    client = MossClient("key")
    await client._client.aclose()
    client._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        payload = await client.transcribe(
            data=b"ID3fake",
            filename="audio.mp3",
            content_type="audio/mpeg",
            model="moss-transcribe-diarize-pro",
            diarize=True,
            keyterms=["MOSS"],
        )
    finally:
        await client.close()

    assert payload["segments"][0]["speaker"] == "S01"
    assert b"moss-transcribe-diarize-pro" in captured["body"]
    assert b"keyterms" in captured["body"]


async def test_list_voices():
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "object": "list",
                "data": [
                    {"id": "v1", "name": "Alice"},
                    {"id": "v2", "name": "Bob"},
                ],
                "has_more": False,
                "next_cursor": "",
            },
        )

    client = MossClient("key")
    await client._client.aclose()
    client._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        voices = await client.list_voices()
    finally:
        await client.close()
    assert [voice["id"] for voice in voices] == ["v1", "v2"]


def test_sniff_formats():
    assert sniff_audio_format(wav_bytes()) == "wav"
    assert sniff_audio_format(b"ID3" + b"\x00" * 30) == "mp3"
    assert sniff_audio_format(b"OggS" + b"\x00" * 30) == "ogg"
    assert sniff_audio_format(b"OggS" + b"OpusHead" + b"\x00" * 30) == "opus"
    assert sniff_audio_format(b"\x1aE\xdf\xa3" + b"\x00" * 30) == "webm"
    assert sniff_audio_format(b"\x00\x00\x00\x18ftypM4A " + b"\x00" * 30) == "m4a"


async def test_prepare_audio():
    prepared = await prepare_audio_from_bytes(
        wav_bytes(),
        filename="voice.wav",
        max_bytes=1024 * 1024,
    )
    assert prepared.audio_format == "wav"
    assert prepared.filename == "audio.wav"
    assert prepared.content_type == "audio/wav"


def test_format_transcript():
    payload = {
        "text": "fallback",
        "segments": [
            {"speaker": "S01", "start": 0.16, "end": 5.18, "text": "你好"},
            {"speaker": "S02", "start": 5.2, "end": 7.0, "text": "再见"},
        ],
    }
    text = format_transcript(payload, include_speaker=True, include_timestamp=True)
    assert "S01:" in text
    assert "[00:00.2–00:05.2]" in text
    assert "再见" in text


def test_config_normalization_and_provider_mapping():
    cfg = normalize_config(
        {
            "connection": {"api_key": "  key  ", "api_base": "https://api.mosi.cn/", "timeout": 5},
            "tts": {"model": "bad-model", "voice_id": "voice", "response_format": "pcm"},
            "stt": {"model": "bad-model", "keyterms": "MOSS，AstrBot"},
            "routing": {"auto_sync": "false"},
        }
    )
    assert cfg["connection"]["api_key"] == "key"
    assert cfg["connection"]["timeout"] == 10
    assert cfg["tts"]["model"] == "moss-tts-1.5-flash"
    assert cfg["tts"]["response_format"] == "mp3"
    assert cfg["stt"]["model"] == "moss-transcribe-1.0"
    assert cfg["stt"]["keyterms"] == ["MOSS", "AstrBot"]
    assert cfg["routing"]["auto_sync"] is False
    assert build_tts_provider_config(cfg)["type"] == "moss_tts"
    assert build_stt_provider_config(cfg)["provider_type"] == "speech_to_text"


def test_legacy_migration():
    cfg = {
        "cloud": {
            "api_key": "old-key",
            "api_base": "https://api.mosi.cn",
            "voice_id": "old-voice",
            "model": "moss-tts",
            "response_format": "wav",
        },
        "stt": {"model": "moss-transcribe-diarize", "diarize": False},
        "sync": {"auto_sync": False, "auto_enable": False},
    }
    assert migrate_legacy_config(cfg) is True
    assert cfg["connection"]["api_key"] == "old-key"
    assert cfg["tts"]["voice_id"] == "old-voice"
    assert cfg["tts"]["response_format"] == "wav"
    assert cfg["stt"]["model"] == "moss-transcribe-diarize-pro"
    assert cfg["stt"]["diarize"] is False
    assert cfg["routing"]["auto_sync"] is False
    assert cfg["routing"]["auto_enable"] is False

