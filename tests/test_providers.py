from __future__ import annotations

import enum
import importlib
import logging
import sys
import types
from dataclasses import dataclass
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _module(name: str, **attrs):
    module = types.ModuleType(name)
    for key, value in attrs.items():
        setattr(module, key, value)
    sys.modules[name] = module
    return module


def install_astrbot_stub():
    if "astrbot" in sys.modules and getattr(sys.modules["astrbot"], "__moss_stub__", False):
        return

    class ProviderType(enum.Enum):
        CHAT_COMPLETION = "chat_completion"
        SPEECH_TO_TEXT = "speech_to_text"
        TEXT_TO_SPEECH = "text_to_speech"
        EMBEDDING = "embedding"
        RERANK = "rerank"
        DECISION = "decision"

    @dataclass
    class ProviderMetaData:
        id: str
        model: str | None
        type: str
        desc: str = ""
        provider_type: ProviderType = ProviderType.CHAT_COMPLETION
        cls_type: object = None
        default_config_tmpl: dict | None = None
        provider_display_name: str | None = None

    registry: list[ProviderMetaData] = []
    cls_map: dict[str, ProviderMetaData] = {}

    def register_provider_adapter(
        name,
        desc,
        provider_type=ProviderType.CHAT_COMPLETION,
        default_config_tmpl=None,
        provider_display_name=None,
    ):
        def decorator(cls):
            meta = ProviderMetaData(
                id="default",
                model=None,
                type=name,
                desc=desc,
                provider_type=provider_type,
                cls_type=cls,
                default_config_tmpl=default_config_tmpl,
                provider_display_name=provider_display_name,
            )
            registry.append(meta)
            cls_map[name] = meta
            return cls

        return decorator

    class TTSProvider:
        def __init__(self, provider_config, provider_settings):
            self.provider_config = provider_config
            self.provider_settings = provider_settings
            self.model_name = ""

        def set_model(self, name):
            self.model_name = name

    class STTProvider:
        def __init__(self, provider_config, provider_settings):
            self.provider_config = provider_config
            self.provider_settings = provider_settings
            self.model_name = ""

        def set_model(self, name):
            self.model_name = name

    class Star:
        def __init__(self, context):
            self.context = context

    class Context:
        pass

    class FakeSP:
        def __init__(self):
            self.values = {}

        async def put_async(self, **kwargs):
            self.values[kwargs.get("key")] = kwargs.get("value")

    logger = logging.getLogger("astrbot")

    astrbot = _module("astrbot", __moss_stub__=True, logger=logger)
    astrbot.__path__ = []
    api = _module("astrbot.api", logger=logger)
    api.__path__ = []
    star = _module("astrbot.api.star", Context=Context, Star=Star)
    web = _module("astrbot.api.web")
    core = _module("astrbot.core", logger=logger, sp=FakeSP())
    core.__path__ = []
    provider = _module("astrbot.core.provider")
    provider.__path__ = []
    entities = _module(
        "astrbot.core.provider.entities",
        ProviderType=ProviderType,
        ProviderMetaData=ProviderMetaData,
    )
    _module(
        "astrbot.core.provider.provider",
        TTSProvider=TTSProvider,
        STTProvider=STTProvider,
    )
    register = _module(
        "astrbot.core.provider.register",
        provider_registry=registry,
        provider_cls_map=cls_map,
        register_provider_adapter=register_provider_adapter,
    )
    utils = _module("astrbot.core.utils")
    utils.__path__ = []
    path_mod = _module(
        "astrbot.core.utils.astrbot_path",
        get_astrbot_temp_path=lambda: str(Path(__file__).parent / ".tmp"),
    )
    media_mod = _module(
        "astrbot.core.utils.media_utils",
        ensure_wav=None,
        convert_audio_format=None,
    )

    astrbot.api = api
    api.star = star
    api.web = web
    astrbot.core = core
    core.provider = provider
    provider.entities = entities
    provider.provider = provider
    provider.register = register
    core.utils = utils
    utils.astrbot_path = path_mod
    utils.media_utils = media_mod

    class DummyRequest:
        content_type = "application/json"

        async def json(self, default=None):
            return default

        async def files(self):
            return {}

        async def form(self):
            return {}

    web.request = DummyRequest()
    web.json_response = lambda data: {"data": data}
    web.error_response = lambda message, status_code=400, data=None: {
        "status": "error",
        "message": message,
        "data": data,
    }

    return cls_map, registry, ProviderType


def load_plugin():
    install_astrbot_stub()
    package = types.ModuleType("moss_plugin")
    package.__path__ = [str(ROOT)]
    sys.modules["moss_plugin"] = package
    return importlib.import_module("moss_plugin.main")


def test_provider_registration_and_construction():
    cls_map, registry, _ = install_astrbot_stub()
    load_plugin()

    assert "moss_tts" in cls_map
    assert "moss_stt" in cls_map
    assert len(registry) >= 2

    from moss_plugin.providers.moss_stt import MossSTTProvider
    from moss_plugin.providers.moss_tts import MossTTSProvider

    tts = MossTTSProvider(
        {
            "api_key": "key",
            "api_base": "https://api.mosi.cn",
            "model": "moss-tts-1.5-flash",
            "voice_id": "voice-1",
            "response_format": "mp3",
        },
        {},
    )
    assert tts.model_name == "moss-tts-1.5-flash"
    assert tts.client.api_base == "https://api.mosi.cn"

    stt = MossSTTProvider(
        {
            "api_key": "key",
            "model": "moss-transcribe-diarize-pro",
            "diarize": True,
            "include_speaker": True,
        },
        {},
    )
    assert stt.model_name == "moss-transcribe-diarize-pro"
    assert stt.max_upload_bytes == 100 * 1024 * 1024


def test_page_api_routes():
    load_plugin()
    from moss_plugin.core.page_api import MossPageApi

    class Context:
        def __init__(self):
            self.routes = []

        def register_web_api(self, route, handler, methods, desc):
            self.routes.append((route, handler, methods, desc))

    class Plugin:
        config = {}

    plugin = Plugin()
    plugin.context = Context()
    api = MossPageApi(plugin)
    api.register_routes()
    routes = {(route, tuple(methods)) for route, _, methods, _ in plugin.context.routes}
    assert ("/astrbot_plugin_moss_voice/page/config", ("GET",)) in routes
    assert ("/astrbot_plugin_moss_voice/page/config", ("POST",)) in routes
    assert ("/astrbot_plugin_moss_voice/page/stt", ("POST",)) in routes


@pytest.mark.asyncio
async def test_sync_providers_boot():
    load_plugin()
    from moss_plugin.core.provider_sync import sync_providers

    class Conf(dict):
        def __init__(self):
            super().__init__(
                {
                    "provider": [],
                    "provider_tts_settings": {"enable": False, "provider_id": ""},
                    "provider_stt_settings": {"enable": False, "provider_id": ""},
                }
            )
            self.saved = 0

        def save_config(self):
            self.saved += 1

    class ACM:
        def __init__(self, conf):
            self.default_conf = conf

    class PM:
        def __init__(self, conf):
            self.acm = ACM(conf)
            self.inst_map = {}

    class Plugin:
        pass

    conf = Conf()
    plugin = Plugin()
    plugin.config = {
        "connection": {"api_key": "key", "api_base": "https://api.mosi.cn", "timeout": 120},
        "tts": {"model": "moss-tts-1.5-flash", "voice_id": "voice", "response_format": "mp3"},
        "stt": {"model": "moss-transcribe-1.0"},
        "routing": {"auto_sync": True, "auto_enable": True},
    }
    plugin.context = types.SimpleNamespace(provider_manager=PM(conf))
    result = await sync_providers(plugin)
    assert result["ok"] is True
    assert result["boot"] is True
    assert len(conf["provider"]) == 2
    assert conf["provider_tts_settings"]["provider_id"] == "moss_tts"
    assert conf["provider_stt_settings"]["provider_id"] == "moss_stt"
    assert conf["provider_tts_settings"]["enable"] is True
    assert conf.saved >= 1


@pytest.mark.asyncio
async def test_page_save_config(monkeypatch):
    load_plugin()
    from moss_plugin.core import page_api as page_mod

    class Config(dict):
        def __init__(self):
            super().__init__(
                {
                    "connection": {
                        "api_key": "",
                        "api_base": "https://api.mosi.cn",
                        "proxy": "",
                        "timeout": 120,
                    },
                    "tts": {
                        "model": "moss-tts-1.5-flash",
                        "voice_id": "voice",
                        "response_format": "mp3",
                    },
                    "stt": {"model": "moss-transcribe-1.0"},
                    "routing": {"auto_sync": False, "auto_enable": False},
                }
            )
            self.saved = 0

        async def save_config_async(self):
            self.saved += 1

    class Req:
        content_type = "application/json"

        async def json(self, default=None):
            return {
                "config": {
                    "connection": {
                        "api_key": "new-key",
                        "api_base": "https://api.mosi.cn",
                        "timeout": 90,
                    },
                    "tts": {"model": "moss-tts-1.0-pro"},
                    "routing": {"auto_sync": False, "auto_enable": False},
                }
            }

        async def files(self):
            return {}

        async def form(self):
            return {}

    class Plugin:
        def __init__(self):
            self.config = Config()
            self.context = types.SimpleNamespace(provider_manager=None)

    monkeypatch.setattr(page_mod, "web_request", Req())
    plugin = Plugin()
    api = page_mod.MossPageApi(plugin)
    response = await api.save_config()
    data = response["data"]
    assert data["config"]["connection"]["api_key"] == "new-key"
    assert data["config"]["connection"]["timeout"] == 90
    assert plugin.config.saved == 1


@pytest.mark.asyncio
async def test_sync_providers_runtime():
    load_plugin()
    from moss_plugin.core.provider_sync import sync_providers

    class Conf(dict):
        def __init__(self):
            super().__init__(
                {
                    "provider": [],
                    "provider_tts_settings": {"enable": False, "provider_id": ""},
                    "provider_stt_settings": {"enable": False, "provider_id": ""},
                }
            )
            self.saved = 0

        def save_config(self):
            self.saved += 1

    class ACM:
        def __init__(self, conf):
            self.default_conf = conf

    class PM:
        def __init__(self, conf):
            self.acm = ACM(conf)
            self.inst_map = {"other": object()}
            self.created = []
            self.selected = []

        async def create_provider(self, plan):
            self.created.append(plan)
            self.acm.default_conf["provider"].append(plan)
            self.inst_map[plan["id"]] = object()

        async def update_provider(self, provider_id, plan):
            raise AssertionError("unexpected update")

        async def set_provider(self, provider_id, provider_type):
            self.selected.append((provider_id, provider_type.value))

    class Plugin:
        pass

    conf = Conf()
    plugin = Plugin()
    plugin.config = {
        "connection": {"api_key": "key", "api_base": "https://api.mosi.cn", "timeout": 120},
        "tts": {"model": "moss-tts-1.5-flash", "voice_id": "voice", "response_format": "mp3"},
        "stt": {"model": "moss-transcribe-1.0"},
        "routing": {"auto_sync": True, "auto_enable": True},
    }
    pm = PM(conf)
    plugin.context = types.SimpleNamespace(provider_manager=pm)
    result = await sync_providers(plugin)
    assert result["ok"] is True
    assert result["boot"] is False
    assert [item["action"] for item in result["results"]] == ["created", "created"]
    assert {item[0] for item in pm.selected} == {"moss_tts", "moss_stt"}
    assert conf["provider_tts_settings"]["enable"] is True
    assert conf["provider_stt_settings"]["enable"] is True


@pytest.mark.asyncio
async def test_page_transcribe_handler(monkeypatch):
    load_plugin()
    from moss_plugin.core import page_api as page_mod

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def transcribe(self, **kwargs):
            assert kwargs["model"] == "moss-transcribe-diarize-pro"
            assert kwargs["diarize"] is True
            return {
                "text": "你好",
                "segments": [
                    {"speaker": "S01", "start": 0.1, "end": 1.2, "text": "你好"}
                ],
            }

        async def close(self):
            pass

    class Req:
        content_type = "application/json"

        async def json(self, default=None):
            import base64

            return {
                "filename": "test.wav",
                "content_type": "audio/wav",
                "data": base64.b64encode(
                    b"RIFF" + (36).to_bytes(4, "little") + b"WAVEfmt " + b"\x00" * 40
                ).decode(),
                "model": "moss-transcribe-diarize-pro",
                "diarize": True,
                "include_speaker": True,
                "include_timestamp": False,
            }

        async def files(self):
            return {}

        async def form(self):
            return {}

    class Config(dict):
        pass

    class Plugin:
        def __init__(self):
            self.config = Config(
                {
                    "connection": {
                        "api_key": "key",
                        "api_base": "https://api.mosi.cn",
                        "timeout": 120,
                    },
                    "stt": {
                        "model": "moss-transcribe-diarize-pro",
                        "diarize": True,
                        "include_speaker": True,
                        "include_timestamp": False,
                    },
                    "routing": {"auto_sync": False},
                }
            )
            self.context = types.SimpleNamespace(provider_manager=None)

    monkeypatch.setattr(page_mod, "MossClient", FakeClient)
    monkeypatch.setattr(page_mod, "web_request", Req())
    response = await page_mod.MossPageApi(Plugin()).transcribe()
    data = response["data"]
    assert data["text"] == "S01: 你好"
    assert data["segments"][0]["speaker"] == "S01"


@pytest.mark.asyncio
async def test_plugin_initialize_without_key():
    load_plugin()
    from moss_plugin.main import MossVoicePlugin

    class Context:
        def __init__(self):
            self.routes = []
            self.provider_manager = None

        def register_web_api(self, route, handler, methods, desc):
            self.routes.append(route)

    plugin = MossVoicePlugin(Context(), config={})
    await plugin.initialize()
    assert "/astrbot_plugin_moss_voice/page/status" in plugin.context.routes


@pytest.mark.asyncio
async def test_list_voices_empty_without_key():
    load_plugin()
    from moss_plugin.core.page_api import MossPageApi

    class Plugin:
        config = {}
        context = types.SimpleNamespace(provider_manager=None)

    response = await MossPageApi(Plugin()).list_voices()
    data = response["data"]
    assert data["voices"] == []
    assert data["source"] == "none"
