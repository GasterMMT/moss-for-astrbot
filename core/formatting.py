"""把 MOSS 转写结果整理成聊天或页面可读的文本。"""

from __future__ import annotations

from typing import Any


def timecode(seconds: Any) -> str:
    try:
        value = max(0.0, float(seconds))
    except (TypeError, ValueError):
        return "00:00.0"
    minutes = int(value // 60)
    remain = value - minutes * 60
    return f"{minutes:02d}:{remain:04.1f}"


def format_transcript(
    payload: dict,
    *,
    include_speaker: bool = True,
    include_timestamp: bool = False,
) -> str:
    """优先按 segments 输出，普通转写退回 text。"""
    if not isinstance(payload, dict):
        return str(payload or "").strip()

    segments = payload.get("segments")
    lines: list[str] = []
    if isinstance(segments, list):
        for item in segments:
            if not isinstance(item, dict):
                continue
            text = str(item.get("text") or "").strip()
            if not text:
                continue
            prefix: list[str] = []
            if include_timestamp:
                start = item.get("start")
                end = item.get("end")
                if start is not None or end is not None:
                    prefix.append(f"[{timecode(start)}–{timecode(end)}]")
            if include_speaker:
                speaker = str(item.get("speaker") or item.get("id") or "").strip()
                if speaker and speaker.lower() not in {"segment", "transcript"}:
                    prefix.append(f"{speaker}:")
            lines.append((" ".join(prefix) + " " + text).strip())

    if lines:
        return "\n".join(lines)

    text = str(payload.get("text") or "").strip()
    return text


def result_segments(payload: dict) -> list[dict]:
    """页面展示用：只保留页面需要的字段。"""
    result: list[dict] = []
    segments = payload.get("segments") if isinstance(payload, dict) else None
    if isinstance(segments, list):
        for item in segments:
            if not isinstance(item, dict):
                continue
            text = str(item.get("text") or "").strip()
            if not text:
                continue
            result.append(
                {
                    "speaker": str(item.get("speaker") or "").strip(),
                    "start": item.get("start"),
                    "end": item.get("end"),
                    "text": text,
                }
            )
    return result
