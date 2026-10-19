"""AI runtime configuration: cloud / local / offline switching.

The platform follows one rule everywhere: the AI runtime is **configured, not
hard coded**.  This module holds that configuration and makes it editable at
runtime, so the GUI can flip between a cloud provider, a local server and the
fully offline engine without restarting the process::

    from ai_runtime.config import get_config, set_mode

    set_mode("cloud")          # force the cloud family
    set_mode("local")          # force local inference (Ollama / vLLM / HF)
    set_mode("offline")        # never touch the network
    set_mode("auto")           # try cloud -> open_source -> chemistry -> local -> offline

Configuration is stored as JSON (``config/ai.json`` by default, overridable
with ``CHEMML_AI_CONFIG``).  API keys may be stored there for a self hosted
deployment; they are pushed into the environment so the providers -- which read
the environment, never the file -- keep working unchanged.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

__all__ = [
    "AIConfig",
    "MODES",
    "MODE_LABELS",
    "get_config",
    "load_config",
    "save_config",
    "set_mode",
    "set_provider",
    "update_config",
    "reset_config",
    "config_path",
    "family_order",
]

ROOT = Path(__file__).resolve().parents[1]

#: Valid modes. ``auto`` walks every family in priority order.
MODES: List[str] = ["auto", "cloud", "local", "open_source", "chemistry", "offline"]

#: Human readable labels (zh / en) surfaced by the GUI.
MODE_LABELS: Dict[str, Dict[str, str]] = {
    "auto": {"zh": "自动", "en": "Auto"},
    "cloud": {"zh": "云端", "en": "Cloud"},
    "local": {"zh": "本地", "en": "Local"},
    "open_source": {"zh": "开源模型", "en": "Open source"},
    "chemistry": {"zh": "化学基座模型", "en": "Chemistry models"},
    "offline": {"zh": "离线内置", "en": "Offline"},
}

#: Family dispatch order for ``auto`` mode.
AUTO_ORDER: List[str] = ["cloud", "open_source", "chemistry", "local", "offline"]


@dataclass
class AIConfig:
    """Runtime AI configuration."""

    mode: str = "auto"
    #: Force a specific provider by name (overrides ``mode`` when set).
    provider: str = ""
    #: Model id override forwarded to the provider (empty keeps its default).
    model: str = ""
    temperature: float = 0.3
    max_tokens: int = 1024
    timeout: float = 30.0
    #: ``env key -> value`` pairs pushed into ``os.environ`` on load.
    api_keys: Dict[str, str] = field(default_factory=dict)
    #: ``provider name -> base url`` overrides (Ollama / vLLM endpoints).
    base_urls: Dict[str, str] = field(default_factory=dict)
    #: ``provider name -> model id`` chosen by the user in the API-key panel.
    #:
    #: v0.7.3 added this so the model list fetched from the provider's own
    #: ``/models`` endpoint could actually be *used*.  A catalogue the user can
    #: read but not select from is a read-only display: the runtime kept
    #: sending whatever the node's default was, so a user who picked
    #: ``openai/gpt-oss-20b`` because NVIDIA's other 80 ids were retired got the
    #: retired one anyway.  Keyed by the same provider id as ``base_urls``.
    models: Dict[str, str] = field(default_factory=dict)

    # -- (de)serialisation --------------------------------------------------- #
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "AIConfig":
        config = cls()
        for key, value in (payload or {}).items():
            if hasattr(config, key):
                setattr(config, key, value)
        if config.mode not in MODES:
            config.mode = "auto"
        return config

    def normalised(self) -> "AIConfig":
        """Coerce numeric fields and validate the mode."""
        self.mode = self.mode if self.mode in MODES else "auto"
        self.temperature = float(self.temperature)
        self.max_tokens = int(self.max_tokens)
        self.timeout = float(self.timeout)
        self.provider = str(self.provider or "")
        self.model = str(self.model or "")
        self.api_keys = {str(k): str(v) for k, v in dict(self.api_keys or {}).items()}
        self.base_urls = {str(k): str(v) for k, v in dict(self.base_urls or {}).items()}
        self.models = {str(k): str(v) for k, v in dict(self.models or {}).items()}
        return self


# --------------------------------------------------------------------------- #
# persistence
# --------------------------------------------------------------------------- #
def config_path() -> Path:
    """Location of the configuration document."""
    override = (os.environ.get("CHEMML_AI_CONFIG") or "").strip()
    if override:
        return Path(override)
    return ROOT / "config" / "ai.json"


def load_config(force: bool = False) -> AIConfig:
    """Read the configuration (missing / broken file -> defaults)."""
    global _CACHE
    if _CACHE is not None and not force:
        return _CACHE
    path = config_path()
    payload: Dict[str, Any] = {}
    if path.exists():
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            payload = {}
    config = AIConfig.from_dict(payload)
    # Environment mode wins over the file so a container can force offline.
    env_mode = (os.environ.get("CHEMML_AI_MODE") or "").strip()
    if env_mode in MODES:
        config.mode = env_mode
    config.normalised()
    _apply_env(config)
    _CACHE = config
    return config


def save_config(config: Optional[AIConfig] = None) -> Path:
    """Persist the configuration and return the path written."""
    global _CACHE
    config = (config or get_config()).normalised()
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(config.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    _apply_env(config)
    _CACHE = config
    return path


# --------------------------------------------------------------------------- #
# accessors
# --------------------------------------------------------------------------- #
def get_config() -> AIConfig:
    """The process wide configuration (lazily loaded)."""
    global _CACHE
    if _CACHE is None:
        return load_config(force=True)
    return _CACHE


def set_mode(mode: str) -> AIConfig:
    """Switch the AI mode and persist it."""
    config = get_config()
    config.mode = mode if mode in MODES else "auto"
    if config.mode != "auto":
        # a forced mode clears a stale forced provider of another family
        config.provider = ""
    save_config(config)
    return config


def set_provider(provider: str) -> AIConfig:
    """Force a specific provider (empty string -> clear)."""
    config = get_config()
    config.provider = str(provider or "")
    save_config(config)
    return config


def update_config(**fields: Any) -> AIConfig:
    """Merge ``fields`` into the configuration and persist it."""
    config = get_config()
    for key, value in fields.items():
        if hasattr(config, key):
            setattr(config, key, value)
    save_config(config)
    return config


def reset_config() -> AIConfig:
    """Restore the defaults."""
    global _CACHE
    _CACHE = AIConfig()
    save_config(_CACHE)
    return _CACHE


def family_order(mode: str = "") -> List[str]:
    """The provider family dispatch order for ``mode``.

    A forced mode is honoured first but always ends with ``offline`` so the
    runtime degrades gracefully instead of hard failing when, say, the cloud
    mode is selected without an API key.  The engine that actually answered is
    recorded in the result, so a fallback is never hidden.
    """
    resolved = (mode or get_config().mode or "auto").strip()
    if resolved == "auto":
        return list(AUTO_ORDER)
    if resolved == "offline":
        return ["offline"]
    return [resolved, "offline"]


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
_CACHE: Optional[AIConfig] = None


def _apply_env(config: AIConfig) -> None:
    """Push stored keys / endpoints into the environment (never overwriting)."""
    for key, value in config.api_keys.items():
        if value and not (os.environ.get(key) or "").strip():
            os.environ[key] = value
    for provider, url in config.base_urls.items():
        if not url:
            continue
        if provider == "ollama":
            os.environ.setdefault("CHEMML_OLLAMA_BASE", url)
        elif provider == "vllm":
            os.environ.setdefault("CHEMML_VLLM_BASE", url)
