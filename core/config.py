"""配置默认值、兼容迁移与 Provider 配置生成。"""

from __future__ import annotations

import copy
import os
from typing import Any

from . import __version__

DEFAULT_API_BASE = "https://api.mosi.cn"
DEFAULT_TTS_MODEL = "moss-tts-1.5-flash"
DEFAULT_STT_MODEL = "moss-transcribe-1.0"

TTS_MODELS = (
    "moss-tts-1.5-flash",
    "moss-tts-1.0-pro",
    "moss-tts-1.5-flash-2026-06-26",
    "moss-tts-1.0-pro-2026-02-07",
)
STT_MODELS = (
    "moss-transcribe-1.0",
    "moss-transcribe-diarize-pro",
    "moss-transcribe-1.0-2026-07-22",
    "moss-transcribe-diarize-pro-2026-07-03",
)
TTS_FORMATS = ("mp3", "wav")
LANGUAGES = (
    "Chinese",
    "Cantonese",
    "English",
    "Arabic",
    "Czech",
    "Danish",
    "Dutch",
    "Finnish",
    "French",
    "German",
    "Greek",
    "Hebrew",
    "Hindi",
    "Hungarian",
    "Italian",
    "Japanese",
    "Korean",
    "Macedonian",
    "Malay",
    "Persian",
    "Polish",
    "Portuguese",
    "Romanian",
    "Russian",
    "Spanish",
    "Swahili",
    "Swedish",
    "Tagalog",
    "Thai",
    "Turkish",
    "Vietnamese",
)

DEFAULT_CONFIG: dict[str, Any] = {
    "connection": {
        "api_key": "",
        "api_base": DEFAULT_API_BASE,
        "proxy": "",
        "timeout": 120,
    },
    "tts": {
        "model": DEFAULT_TTS_MODEL,
        "voice_id": "",
        "language": "",
        "response_format": "mp3",
        "max_chars": 5000,
    },
    "stt": {
        "model": DEFAULT_STT_MODEL,
        "diarize": True,
        "keyterms": [],
        "include_speaker": True,
        "include_timestamp": False,
        "max_upload_mb": 100,
    },
    "routing": {
        "auto_sync": True,
        "auto_enable": True,
        "tts_provider_id": "moss_tts",
        "stt_provider_id": "moss_stt",
    },
}


def _as_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on", "开启"}
    if isinstance(value, (int, float)):
        return bool(value)
    return default


def _as_int(value: Any, default: int, minimum: int, maximum: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, number))


def _safe_id(value: Any, default: str) -> str:
    text = str(value or "").strip()
    if text and all(ch.isalnum() or ch == "_" for ch in text) and len(text) <= 64:
        return text
    return default


def deep_merge(defaults: dict, value: dict | None) -> dict:
    """把用户配置合并到默认值上，只保留 dict 里的同名字段。"""
    result = copy.deepcopy(defaults)
    if not isinstance(value, dict):
        return result
    for key, default in defaults.items():
        if key not in value:
            continue
        incoming = value[key]
        if isinstance(default, dict) and isinstance(incoming, dict):
            result[key] = {**default, **copy.deepcopy(incoming)}
        elif isinstance(default, list) and isinstance(incoming, list):
            result[key] = copy.deepcopy(incoming)
    return result


def normalize_config(value: dict | None) -> dict:
    """清洗配置，避免 UI / 旧配置写入非法值。"""
    data = deep_merge(DEFAULT_CONFIG, value)

    connection = data["connection"]
    connection["api_key"] = str(connection.get("api_key") or "").strip()
    api_base = str(connection.get("api_base") or "").strip().rstrip("/")
    if not api_base.startswith(("http://", "https://")):
        api_base = DEFAULT_API_BASE
    connection["api_base"] = api_base
    connection["proxy"] = str(connection.get("proxy") or "").strip()
    connection["timeout"] = _as_int(connection.get("timeout"), 120, 10, 600)

    tts = data["tts"]
    if tts.get("model") not in TTS_MODELS:
        tts["model"] = DEFAULT_TTS_MODEL
    tts["voice_id"] = str(tts.get("voice_id") or "").strip()
    language = str(tts.get("language") or "").strip()
    tts["language"] = language if language in LANGUAGES else ""
    if tts.get("response_format") not in TTS_FORMATS:
        tts["response_format"] = "mp3"
    tts["max_chars"] = _as_int(tts.get("max_chars"), 5000, 100, 10000)

    stt = data["stt"]
    if stt.get("model") not in STT_MODELS:
        stt["model"] = DEFAULT_STT_MODEL
    stt["diarize"] = _as_bool(stt.get("diarize"), True)
    stt["include_speaker"] = _as_bool(stt.get("include_speaker"), True)
    stt["include_timestamp"] = _as_bool(stt.get("include_timestamp"), False)
    stt["max_upload_mb"] = _as_int(stt.get("max_upload_mb"), 100, 1, 512)
    keyterms = stt.get("keyterms")
    if isinstance(keyterms, str):
        keyterms = [item.strip() for item in keyterms.replace("，", ",").split(",")]
    if not isinstance(keyterms, list):
        keyterms = []
    cleaned: list[str] = []
    for item in keyterms:
        term = str(item or "").strip()
        if term and term not in cleaned:
            cleaned.append(term[:64])
    stt["keyterms"] = cleaned[:50]

    routing = data["routing"]
    routing["auto_sync"] = _as_bool(routing.get("auto_sync"), True)
    routing["auto_enable"] = _as_bool(routing.get("auto_enable"), True)
    routing["tts_provider_id"] = _safe_id(routing.get("tts_provider_id"), "moss_tts")
    routing["stt_provider_id"] = _safe_id(routing.get("stt_provider_id"), "moss_stt")

    return data


def get_api_key(config: dict) -> tuple[str, str]:
    """返回 (key, source)。配置为空时回退到 MOSS_API_KEY 环境变量。"""
    key = str((config.get("connection") or {}).get("api_key") or "").strip()
    if key:
        return key, "config"
    env_key = os.environ.get("MOSS_API_KEY", "").strip()
    if env_key:
        return env_key, "env"
    return "", "none"


def mask_key(key: str) -> str:
    if not key:
        return ""
    if len(key) <= 8:
        return "****"
    return f"{key[:4]}****{key[-4:]}"


def build_tts_provider_config(config: dict) -> dict:
    cfg = normalize_config(config)
    conn = cfg["connection"]
    tts = cfg["tts"]
    return {
        "id": cfg["routing"]["tts_provider_id"],
        "type": "moss_tts",
        "provider_type": "text_to_speech",
        "enable": True,
        "api_base": conn["api_base"],
        "api_key": conn["api_key"],
        "proxy": conn["proxy"],
        "timeout": conn["timeout"],
        "model": tts["model"],
        "voice_id": tts["voice_id"],
        "language": tts["language"],
        "response_format": tts["response_format"],
        "max_chars": tts["max_chars"],
    }


def build_stt_provider_config(config: dict) -> dict:
    cfg = normalize_config(config)
    conn = cfg["connection"]
    stt = cfg["stt"]
    return {
        "id": cfg["routing"]["stt_provider_id"],
        "type": "moss_stt",
        "provider_type": "speech_to_text",
        "enable": True,
        "api_base": conn["api_base"],
        "api_key": conn["api_key"],
        "proxy": conn["proxy"],
        "timeout": max(conn["timeout"], 180),
        "model": stt["model"],
        "diarize": stt["diarize"],
        "keyterms": list(stt["keyterms"]),
        "include_speaker": stt["include_speaker"],
        "include_timestamp": stt["include_timestamp"],
        "max_upload_mb": stt["max_upload_mb"],
    }


def public_config(config: dict, *, include_key: bool = False) -> dict:
    """给页面的配置副本，附带 API Key 的显示状态。"""
    cfg = normalize_config(config)
    key, source = get_api_key(cfg)
    if not include_key:
        cfg["connection"]["api_key"] = ""
    cfg["_meta"] = {
        "version": __version__,
        "api_key_configured": bool(key),
        "api_key_masked": mask_key(key),
        "api_key_source": source,
    }
    return cfg


def migrate_legacy_config(config: dict) -> bool:
    """把 v2.x 的 cloud/stt/sync 配置迁移到 v3 结构，只补空值。"""
    if not isinstance(config, dict):
        return False
    changed = False

    legacy_cloud = config.get("cloud")
    legacy_stt = config.get("stt") or {}
    legacy_sync = config.get("sync") or {}
    if not isinstance(legacy_cloud, dict):
        legacy_cloud = {}

    conn = config.setdefault("connection", {})
    if isinstance(conn, dict):
        if not str(conn.get("api_key") or "").strip() and legacy_cloud.get("api_key"):
            conn["api_key"] = str(legacy_cloud.get("api_key") or "")
            changed = True
        if (
            not str(conn.get("api_base") or "").strip()
            or conn.get("api_base") == DEFAULT_API_BASE
        ) and legacy_cloud.get("api_base"):
            base = str(legacy_cloud.get("api_base") or "").strip()
            if base and base != DEFAULT_API_BASE:
                conn["api_base"] = base
                changed = True
        if not str(conn.get("proxy") or "").strip() and legacy_cloud.get("proxy"):
            conn["proxy"] = str(legacy_cloud.get("proxy") or "")
            changed = True
        if legacy_cloud.get("timeout") and conn.get("timeout") in (None, 120):
            conn["timeout"] = legacy_cloud["timeout"]
            changed = True

    tts = config.setdefault("tts", {})
    if isinstance(tts, dict):
        old_voice = str(legacy_cloud.get("voice_id") or "").strip()
        current_voice = str(tts.get("voice_id") or "").strip()
        if old_voice and not current_voice:
            tts["voice_id"] = old_voice
            changed = True
        old_model = str(legacy_cloud.get("model") or "")
        if old_model in {"moss-tts", "moss-tts-flash"} and tts.get("model") in (
            None,
            DEFAULT_TTS_MODEL,
        ):
            tts["model"] = DEFAULT_TTS_MODEL
            changed = True
        elif old_model in TTS_MODELS and tts.get("model") in (None, DEFAULT_TTS_MODEL):
            tts["model"] = old_model
            changed = True
        if legacy_cloud.get("response_format") and tts.get("response_format") in (
            None,
            "mp3",
        ):
            fmt = str(legacy_cloud["response_format"])
            if fmt in TTS_FORMATS and fmt != tts.get("response_format"):
                tts["response_format"] = fmt
                changed = True

    stt = config.setdefault("stt", {})
    if isinstance(stt, dict) and isinstance(legacy_stt, dict):
        old_stt_model = str(legacy_stt.get("model") or "")
        model_map = {
            "moss-transcribe": "moss-transcribe-1.0",
            "moss-transcribe-diarize": "moss-transcribe-diarize-pro",
        }
        current_stt_model = stt.get("model")
        if old_stt_model in model_map and current_stt_model in (
            None,
            DEFAULT_STT_MODEL,
            old_stt_model,
        ):
            stt["model"] = model_map[old_stt_model]
            changed = True
        defaults_stt = DEFAULT_CONFIG["stt"]
        for key in ("diarize", "include_speaker", "include_timestamp"):
            if key in legacy_stt:
                current = stt.get(key)
                if current is None or current == defaults_stt[key]:
                    if current != legacy_stt[key]:
                        stt[key] = legacy_stt[key]
                        changed = True
        if legacy_stt.get("keyterms") and not stt.get("keyterms"):
            stt["keyterms"] = legacy_stt["keyterms"]
            changed = True

    routing = config.setdefault("routing", {})
    if isinstance(routing, dict) and isinstance(legacy_sync, dict):
        defaults_routing = DEFAULT_CONFIG["routing"]
        for src in ("auto_sync", "auto_enable"):
            if src in legacy_sync:
                current = routing.get(src)
                if current is None or current == defaults_routing[src]:
                    if current != bool(legacy_sync[src]):
                        routing[src] = bool(legacy_sync[src])
                        changed = True

    return changed
