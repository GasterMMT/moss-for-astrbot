"""冒烟测试：用 stub 模拟 AstrBot/httpx 环境，验证官方 API 适配器行为。"""
import asyncio
import importlib
import os
import shutil
import sys
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace

PLUGIN_DIR = Path(__file__).resolve().parent.parent
STUB_ROOT = Path(tempfile.mkdtemp(prefix="astrbot_stub_"))


def write(pkg_path: Path, content: str):
    pkg_path.mkdir(parents=True, exist_ok=True)
    (pkg_path / "__init__.py").write_text(content, encoding="utf-8")


def write_module(pkg_path: Path, name: str, content: str):
    pkg_path.mkdir(parents=True, exist_ok=True)
    (pkg_path / f"{name}.py").write_text(content, encoding="utf-8")


# ---- stub: astrbot ----
write(STUB_ROOT / "astrbot", "import logging\nlogger = logging.getLogger('astrbot-stub')\n")
write(STUB_ROOT / "astrbot" / "api", "from astrbot import logger\n")
write(STUB_ROOT / "astrbot" / "api" / "star", """
class Context:
    pass
class Star:
    def __init__(self, context, config=None):
        self.context = context
""")

# ---- stub: astrbot.core.provider ----
core = STUB_ROOT / "astrbot" / "core"
write(core, "")
write_module(core / "provider", "entities", """
import enum
class ProviderType(enum.Enum):
    CHAT_COMPLETION = "chat_completion"
    SPEECH_TO_TEXT = "speech_to_text"
    TEXT_TO_SPEECH = "text_to_speech"
    EMBEDDING = "embedding"
    RERANK = "rerank"
""")
write_module(core / "provider", "register", """
from types import SimpleNamespace
provider_registry = []
provider_cls_map = {}
def register_provider_adapter(provider_type_name, desc, provider_type=None,
                              default_config_tmpl=None, provider_display_name=None):
    def decorator(cls):
        if default_config_tmpl:
            default_config_tmpl.setdefault("type", provider_type_name)
            default_config_tmpl.setdefault("enable", False)
            default_config_tmpl.setdefault("id", provider_type_name)
        pm = SimpleNamespace(
            id="default", model=None, type=provider_type_name, desc=desc,
            provider_type=provider_type, cls_type=cls,
            default_config_tmpl=default_config_tmpl,
            provider_display_name=provider_display_name,
        )
        provider_registry.append(pm)
        provider_cls_map[provider_type_name] = pm
        return cls
    return decorator
""")
write_module(core / "provider", "provider", """
import abc
class AbstractProvider(abc.ABC):
    def __init__(self, provider_config):
        self.model_name = ""
        self.provider_config = provider_config
    def set_model(self, model_name):
        self.model_name = model_name
    def get_model(self):
        return self.model_name
class STTProvider(AbstractProvider):
    def __init__(self, provider_config, provider_settings):
        super().__init__(provider_config)
        self.provider_settings = provider_settings
class TTSProvider(AbstractProvider):
    def __init__(self, provider_config, provider_settings):
        super().__init__(provider_config)
        self.provider_settings = provider_settings
""")

# ---- stub: astrbot.core.utils ----
utils = core / "utils"
write(utils, "")
write_module(utils, "astrbot_path", """
def get_astrbot_temp_path():
    import tempfile
    return tempfile.gettempdir()
""")
write_module(utils, "datetime_utils", """
import time, uuid
def generate_timestamp_id():
    return f"{int(time.time()*1000)}_{uuid.uuid4().hex[:6]}"
""")
write_module(utils, "media_utils", """
from contextlib import asynccontextmanager
from pathlib import Path
class MediaResolver:
    def __init__(self, media_ref, *, media_type="file", default_suffix=None):
        self.media_ref = media_ref
        self.media_type = media_type
        self.default_suffix = default_suffix
    @asynccontextmanager
    async def as_path(self, target_format=None):
        import tempfile
        p = Path(self.media_ref)
        if not p.is_file():
            p = Path(tempfile.mktemp(suffix=".wav")); p.write_bytes(b"RIFFxxxxWAVEfake")
            yield p
            p.unlink(missing_ok=True)
        else:
            yield p
""")

# ---- stub: httpx ----
write(STUB_ROOT / "httpx", """
import json as _json
class Response:
    def __init__(self, content=b"", headers=None, status_code=200, text=""):
        self.content = content; self.headers = headers or {}; self.status_code = status_code; self.text = text
    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")
    def json(self):
        return _json.loads(self.content)
class AsyncClient:
    def __init__(self, **kwargs): self.kwargs = kwargs; self.post_calls = []; self.get_calls = []
    async def post(self, url, **kwargs):
        self.post_calls.append((url, kwargs))
        return Response(content=b"ID3\\x03fake-mp3-bytes", headers={"content-type": "audio/mpeg"})
    async def get(self, url, **kwargs):
        self.get_calls.append((url, kwargs))
        return Response(content=b"ID3\\x03fake-mp3-bytes", headers={"content-type": "audio/mpeg"})
    async def aclose(self): pass
""")


def main():
    sys.path.insert(0, str(STUB_ROOT))
    sys.path.insert(0, str(PLUGIN_DIR))

    # 以包方式导入（模拟 AstrBot 的 data.plugins.<name> 加载路径）
    import types as t
    pkg = t.ModuleType("astrbot_plugin_moss_voice")
    pkg.__path__ = [str(PLUGIN_DIR)]
    sys.modules["astrbot_plugin_moss_voice"] = pkg

    moss_tts_cloud = importlib.import_module("astrbot_plugin_moss_voice.providers.moss_tts_cloud")
    moss_stt_cloud = importlib.import_module("astrbot_plugin_moss_voice.providers.moss_stt_cloud")
    mosi_api = importlib.import_module("astrbot_plugin_moss_voice.providers._mosi_api")
    sync_mod = importlib.import_module("astrbot_plugin_moss_voice.core.sync")
    main_mod = importlib.import_module("astrbot_plugin_moss_voice.main")

    from astrbot.core.provider.register import provider_cls_map

    assert "moss_tts_cloud" in provider_cls_map
    assert "moss_stt_cloud" in provider_cls_map
    print("1. Provider 注册成功:", sorted(provider_cls_map))

    # ---- 2. TTS：官方请求字段（严格入参）----
    tts_meta = provider_cls_map["moss_tts_cloud"]
    tts = tts_meta.cls_type(
        {
            "id": "moss_tts_cloud", "type": "moss_tts_cloud", "enable": True,
            "api_base": "https://api.mosi.cn", "api_key": "sk-test",
            "model": "moss-tts", "version": "v1", "voice_id": "806c9695-6160-404e-8722-4f788d935af3",
            "response_format": "mp3", "delivery_method": "audio", "timeout": 120, "proxy": "",
        },
        {},
    )
    payload = tts._build_payload("欢迎使用 Moss API。[pause 1.5s] 测试")
    assert payload == {
        "model": "moss-tts",
        "input": "欢迎使用 Moss API。[pause 1.5s] 测试",
        "voice_id": "806c9695-6160-404e-8722-4f788d935af3",
        "response_format": "mp3",
        "delivery_method": "audio",
        "version": "v1",
    }, payload
    # 不夹带官方未文档化字段
    assert set(payload) <= {"model", "input", "voice_id", "response_format", "delivery_method", "version"}
    assert mosi_api.mosi_headers(tts.api_key, json_body=True)["Authorization"] == "Bearer sk-test"
    print("2. moss_tts_cloud 官方请求字段构造正确（严格入参）")

    # ---- 3. TTS 端到端（audio 二进制交付）----
    async def run_tts():
        path = await tts.get_audio("hello")
        assert os.path.isfile(path) and path.endswith(".mp3")
        assert os.path.getsize(path) > 0
        os.remove(path)
        # delivery_method=url：JSON 交付 → 下载 url
        tts.delivery_method = "url"
        import types as t
        async def fake_post(self, url, **kw):
            import json as j
            return SimpleNamespace(
                raise_for_status=lambda: None,
                status_code=200,
                json=lambda: {"id": "task_1", "object": "audio.speech", "status": "SUCCESS",
                              "url": "https://cdn.example.com/out.mp3",
                              "response_format": "mp3", "content_type": "audio/mpeg"},
            )
        tts.client.post = t.MethodType(fake_post, tts.client)
        path2 = await tts.get_audio("hello url")
        assert os.path.isfile(path2) and path2.endswith(".mp3")
        os.remove(path2)
        print("3. moss_tts_cloud get_audio 端到端（audio / url 两种交付）通过")

    asyncio.run(run_tts())

    # ---- 4. 官方错误结构解析 ----
    err = mosi_api.mosi_error_message(
        {"error": {"message": "billing error", "type": "billing_error", "param": None, "code": "insufficient_credits"}},
        http_status=402,
    )
    assert "billing error" in err and "余额不足" in err, err
    err403 = mosi_api.mosi_error_message(
        {"error": {"code": "102111001", "type": "permission_error", "message": "iam api key auth failed", "legacy_code": 4030},
         "trace_id": "x"},
        http_status=403,
    )
    assert "API Key" in err403, err403
    print("4. 官方错误结构解析正确（billing / permission）")

    # ---- 5. STT：官方请求字段与结果解析 ----
    stt_meta = provider_cls_map["moss_stt_cloud"]
    stt = stt_meta.cls_type(
        {
            "id": "moss_stt_cloud", "type": "moss_stt_cloud", "enable": True,
            "api_base": "https://api.mosi.cn", "api_key": "sk-test",
            "model": "moss-transcribe-diarize", "version": "", "diarize": True,
            "response_format": "json", "include_speaker": True, "include_timestamp": True,
            "timeout": 300, "proxy": "",
        },
        {},
    )
    form = stt._build_form_data()
    assert form == {"model": "moss-transcribe-diarize", "response_format": "json", "diarize": "true"}, form
    # 普通转写模型不传 diarize
    stt.set_model("moss-transcribe")
    assert "diarize" not in stt._build_form_data()
    stt.set_model("moss-transcribe-diarize")

    fake_resp = SimpleNamespace(
        raise_for_status=lambda: None,
        text="",
        headers={"content-type": "application/json"},
        json=lambda: {
            "task": "transcribe", "duration": 5.0,
            "text": "大家好，你好。",
            "segments": [
                {"type": "segment", "id": "s1", "start": 0.15, "end": 2.74, "text": "大家好，", "speaker": "S01"},
                {"type": "segment", "id": "s2", "start": 3.1, "end": 5.0, "text": "你好。", "speaker": "S02"},
            ],
        },
    )
    parsed = stt._parse_result(fake_resp)
    assert "[0.1s-2.7s] S01: 大家好，" in parsed, parsed
    assert "[3.1s-5.0s] S02: 你好。" in parsed, parsed
    print("5. moss_stt_cloud 官方 segments 解析正确:\n" + parsed)

    # ---- 6. STT 端到端（multipart file 上传）----
    async def run_stt():
        import types as t
        async def fake_post(self, url, **kw):
            files = kw.get("files") or {}
            assert "file" in files, "必须走 multipart file 上传"
            data = kw.get("data") or {}
            assert data.get("model") == "moss-transcribe-diarize"
            assert data.get("diarize") == "true"
            return SimpleNamespace(
                raise_for_status=lambda: None,
                status_code=200,
                text="",
                headers={"content-type": "application/json"},
                json=lambda: {"text": "识别结果", "segments": []},
            )
        stt.client.post = t.MethodType(fake_post, stt.client)
        stt.include_speaker = False
        text = await stt.get_text(str(PLUGIN_DIR / "README.md"))
        assert text == "识别结果", text
        print("6. moss_stt_cloud get_text 端到端（multipart file）通过:", text)

    asyncio.run(run_stt())

    # ---- 7. sync：配置同步 ----
    cfg = {"cloud": {"api_key": "sk-x", "voice_id": "V1"}, "stt": {"diarize": False}, "sync": {}}
    tts_cfg = sync_mod.build_tts_provider_config(cfg)
    assert tts_cfg["id"] == "moss_tts_cloud" and tts_cfg["voice_id"] == "V1"
    assert tts_cfg["api_base"] == "https://api.mosi.cn"
    stt_cfg = sync_mod.build_stt_provider_config(cfg)
    assert stt_cfg["diarize"] is False and stt_cfg["model"] == "moss-transcribe-diarize"
    provider_list = [{"id": "other", "type": "x"}]
    action, pid = sync_mod.upsert_provider_config(provider_list, tts_cfg)
    assert action == "created" and len(provider_list) == 2
    tts_cfg["voice_id"] = "V2"
    action, pid = sync_mod.upsert_provider_config(provider_list, tts_cfg)
    assert action == "updated" and provider_list[1]["voice_id"] == "V2"
    print("7. core.sync 配置构建与就地 upsert 正确")

    # ---- 8. 热重载幂等性（复现“适配器已注册”报错场景）----
    for mod_name in [
        "astrbot_plugin_moss_voice.providers.moss_tts_cloud",
        "astrbot_plugin_moss_voice.providers.moss_stt_cloud",
    ]:
        reg_name = mod_name.rsplit(".", 1)[1]
        mod = sys.modules[mod_name]
        old_cls = provider_cls_map[reg_name].cls_type
        importlib.reload(mod)
        new_cls = provider_cls_map[reg_name].cls_type
        assert new_cls is not old_cls, f"{reg_name} 注册表未更新为新类"
        assert new_cls.__module__ == mod_name
    print("8. Provider 热重载幂等：无冲突，注册表指向新类")

    # ---- 9. main 包加载 ----
    assert hasattr(main_mod, "MossVoicePlugin")
    assert main_mod.PLUGIN_VERSION == "2.1.0"
    print("9. main.py 插件类加载正常（v2.0.1）")

    print("\n=== 冒烟测试全部通过 ===")


if __name__ == "__main__":
    try:
        main()
    finally:
        shutil.rmtree(STUB_ROOT, ignore_errors=True)
