"""MOSI 官方 MossAPI（https://api.mosi.cn）公共工具。

依据官方文档（https://platform.mosi.cn/docs）：

- 所有 /v1 接口统一使用 ``Authorization: Bearer <API_KEY>`` 鉴权；
- 接口对请求体做严格字段校验，未知字段返回 400 invalid_request_error；
- 同步错误结构：``{"error": {"message", "type", "param", "code"}, ...}``；
- API Key 缺失/无效时可能返回 403 permission_error（不一定是 401）。
"""

MOSI_DEFAULT_API_BASE = "https://api.mosi.cn"

# 官方错误 type / code → 中文提示
MOSI_ERROR_HINTS = {
    # type 维度
    "invalid_request_error": "请求参数错误（官方接口严格校验入参，未知字段会被拒绝）",
    "authentication_error": "鉴权失败，请检查 API Key",
    "permission_error": "API Key 缺失、无效或无权限（403 也常见于此）",
    "billing_error": "计费或余额问题",
    "not_found_error": "资源不存在",
    "conflict_error": "资源冲突",
    "rate_limit_error": "限流或并发超限",
    # code 维度
    "missing_required_field": "缺少必填字段",
    "invalid_field_value": "字段值不合法",
    "unsupported_response_format": "不支持的输出格式",
    "invalid_url": "URL 格式不合法或不允许访问（不得指向 localhost/回环/私网地址）",
    "url_not_allowed": "URL 不允许访问（不得指向 localhost/回环/私网地址）",
    "insufficient_credits": "余额不足，请前往官方平台充值",
    "rate_limit_exceeded": "请求频率超限，请稍后重试",
    "concurrency_limit_exceeded": "并发超限，请稍后重试",
    "file_not_found": "文件不存在（file_id 无效或已过期）",
    "voice_not_found": "音色不存在（voice_id 无效）",
    "task_not_found": "任务不存在",
    "safety_guardrail_blocked": "内容被安全检测拦截",
}


def mosi_error_message(payload, http_status: int | None = None) -> str | None:
    """解析官方错误响应，返回中文提示；非错误响应返回 None。"""
    if not isinstance(payload, dict):
        return None

    error = payload.get("error")
    if isinstance(error, dict):
        message = str(error.get("message") or "").strip()
        err_type = str(error.get("type") or "").strip()
        code = str(error.get("code") or "").strip()
        parts = [message] if message else []
        if code:
            parts.append(f"code={code}")
        if err_type:
            parts.append(f"type={err_type}")
        hint = MOSI_ERROR_HINTS.get(code) or MOSI_ERROR_HINTS.get(err_type)
        if hint:
            parts.append(f"（{hint}）")
        if parts:
            return " ".join(parts)

    # 兼容无 error 包装的情况
    message = payload.get("message") or payload.get("error")
    if isinstance(message, str) and message.strip():
        return message.strip()

    return None


def mosi_headers(api_key: str, *, json_body: bool = False) -> dict:
    """构造官方 API 请求头。"""
    headers: dict = {}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    if json_body:
        headers["Content-Type"] = "application/json"
    return headers
