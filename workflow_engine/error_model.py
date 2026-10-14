"""Unified error model (v0.7 -- spec section 9).

Every platform module reports failures as a :class:`PlatformError` carrying a
machine readable :class:`ErrorCode`, a user-presentable message, technical
detail, recoverability and a suggested action.  The GUI renders exactly this
structure; the REST layer serialises it via :meth:`PlatformError.to_dict`.

Secret redaction: :func:`redact_secrets` masks anything that looks like an
API key or bearer token before the message can reach a log, a report or the
client.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

from .errors import ChemMLError

__all__ = [
    "ErrorCode",
    "RECOVERABLE_CODES",
    "PlatformError",
    "redact_secrets",
    "SUGGESTED_ACTIONS",
]


class ErrorCode(str, Enum):
    """Stable error codes mandated by the v0.7 specification (section 9)."""

    VALIDATION_ERROR = "VALIDATION_ERROR"
    INPUT_FORMAT_ERROR = "INPUT_FORMAT_ERROR"
    NODE_EXECUTION_ERROR = "NODE_EXECUTION_ERROR"
    DEPENDENCY_MISSING = "DEPENDENCY_MISSING"
    MODEL_UNAVAILABLE = "MODEL_UNAVAILABLE"
    API_AUTH_ERROR = "API_AUTH_ERROR"
    NETWORK_ERROR = "NETWORK_ERROR"
    GPU_UNAVAILABLE = "GPU_UNAVAILABLE"
    OUT_OF_MEMORY = "OUT_OF_MEMORY"
    TIMEOUT = "TIMEOUT"
    EXTERNAL_SOFTWARE_ERROR = "EXTERNAL_SOFTWARE_ERROR"
    STORAGE_SECURITY_ERROR = "STORAGE_SECURITY_ERROR"
    WORKFLOW_INVALID = "WORKFLOW_INVALID"
    CANCELLED = "CANCELLED"


#: Codes from which a user-facing "Retry" affordance makes sense.
RECOVERABLE_CODES = {
    ErrorCode.NETWORK_ERROR,
    ErrorCode.TIMEOUT,
    ErrorCode.MODEL_UNAVAILABLE,
    ErrorCode.OUT_OF_MEMORY,
    ErrorCode.GPU_UNAVAILABLE,
    ErrorCode.EXTERNAL_SOFTWARE_ERROR,
}

#: Default user guidance per error code.
SUGGESTED_ACTIONS: Dict[ErrorCode, str] = {
    ErrorCode.VALIDATION_ERROR: "检查参数取值范围后重试。",
    ErrorCode.INPUT_FORMAT_ERROR: "确认文件格式与所选解析器匹配，或改用受支持的通用格式。",
    ErrorCode.NODE_EXECUTION_ERROR: "查看节点日志定位失败原因，可重试该节点。",
    ErrorCode.DEPENDENCY_MISSING: "安装缺失的依赖后重启平台（见安装说明）。",
    ErrorCode.MODEL_UNAVAILABLE: "启动本地推理服务（如 Ollama）或配置云端 Provider 密钥。",
    ErrorCode.API_AUTH_ERROR: "在 AI 设置中更新 API Key（密钥不会写入工作流或日志）。",
    ErrorCode.NETWORK_ERROR: "检查网络连接后重试；敏感数据建议改用本地模型。",
    ErrorCode.GPU_UNAVAILABLE: "安装 CUDA 版 PyTorch 或改用 CPU 回退执行。",
    ErrorCode.OUT_OF_MEMORY: "减小批处理大小、卸载未用模型，或切换到更小的模型。",
    ErrorCode.TIMEOUT: "增加超时上限、缩小任务规模后重试。",
    ErrorCode.EXTERNAL_SOFTWARE_ERROR: "确认外部软件已安装、许可证有效且命令行可用。",
    ErrorCode.STORAGE_SECURITY_ERROR: "文件路径超出授权工作区，请通过上传接口重新导入。",
    ErrorCode.WORKFLOW_INVALID: "根据校验信息修复节点连线或参数。",
    ErrorCode.CANCELLED: "任务已被用户取消。",
}

# Patterns that look like credentials.  Redaction is applied defensively to
# every user-visible message.
_SECRET_PATTERNS = [
    re.compile(r"(sk-[A-Za-z0-9]{8,})"),                       # OpenAI style
    re.compile(r"(Bearer\s+[A-Za-z0-9\-._~+/]+=*)", re.I),     # bearer tokens
    re.compile(r"(gh[pousr]_[A-Za-z0-9]{20,})"),               # GitHub tokens
    re.compile(r"(eyJ[A-Za-z0-9\-_.]{20,})"),                  # JWT-ish
]


def redact_secrets(text: str) -> str:
    """Mask credential-looking substrings in a message."""
    masked = text
    for pattern in _SECRET_PATTERNS:
        masked = pattern.sub(lambda m: m.group(1)[:6] + "***REDACTED", masked)
    return masked


@dataclass
class PlatformError(ChemMLError):
    """The single error shape used across engine, nodes, API and GUI."""

    code: ErrorCode
    message: str                       # user presentable (redacted)
    technical: str = ""                # developer detail (redacted)
    node_id: str = ""
    node_type: str = ""
    run_id: str = ""
    recoverable: Optional[bool] = None  # None -> derived from the code
    suggested_action: str = ""
    details: Dict[str, Any] = field(default_factory=dict)
    logs: List[str] = field(default_factory=list)
    timestamp: float = field(default_factory=time.time)

    def __post_init__(self) -> None:
        self.message = redact_secrets(str(self.message))
        self.technical = redact_secrets(str(self.technical or self.message))
        if self.recoverable is None:
            self.recoverable = self.code in RECOVERABLE_CODES
        if not self.suggested_action:
            self.suggested_action = SUGGESTED_ACTIONS.get(self.code, "")

    # -- convenience constructors ------------------------------------------- #
    @classmethod
    def validation(cls, message: str, **kw: Any) -> "PlatformError":
        return cls(ErrorCode.VALIDATION_ERROR, message, **kw)

    @classmethod
    def input_format(cls, message: str, **kw: Any) -> "PlatformError":
        return cls(ErrorCode.INPUT_FORMAT_ERROR, message, **kw)

    @classmethod
    def dependency_missing(cls, what: str, **kw: Any) -> "PlatformError":
        return cls(ErrorCode.DEPENDENCY_MISSING, f"缺少依赖：{what}", **kw)

    @classmethod
    def storage_security(cls, message: str, **kw: Any) -> "PlatformError":
        return cls(ErrorCode.STORAGE_SECURITY_ERROR, message, **kw)

    @classmethod
    def cancelled(cls, message: str = "任务已取消", **kw: Any) -> "PlatformError":
        return cls(ErrorCode.CANCELLED, message, recoverable=False, **kw)

    # -- serialisation -------------------------------------------------------- #
    def to_dict(self) -> Dict[str, Any]:
        return {
            "code": self.code.value if isinstance(self.code, ErrorCode) else str(self.code),
            "message": self.message,
            "technical": self.technical,
            "node_id": self.node_id,
            "node_type": self.node_type,
            "run_id": self.run_id,
            "recoverable": bool(self.recoverable),
            "suggested_action": self.suggested_action,
            "details": dict(self.details),
            "logs": list(self.logs),
            "timestamp": self.timestamp,
        }

    def __str__(self) -> str:  # pragma: no cover - repr helper
        return f"[{self.code.value}] {self.message}"


def from_exception(exc: Exception, **kw: Any) -> PlatformError:
    """Wrap an arbitrary exception into the unified model."""
    if isinstance(exc, PlatformError):
        return exc
    # Storage layer signals are mapped to their mandated code lazily so the
    # storage package does not need to import the engine.
    if type(exc).__name__ == "SafePathError":
        return PlatformError(ErrorCode.STORAGE_SECURITY_ERROR, str(exc), **kw)
    text = f"{type(exc).__name__}: {exc}"
    return PlatformError(ErrorCode.NODE_EXECUTION_ERROR, text, **kw)
