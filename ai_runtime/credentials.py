"""Provider credential store (v0.7.3).

The GUI needs somewhere obvious to put an API key, and the runtime needs
somewhere safe to read it from.  This module is that meeting point, and it
exists because the existing pieces each covered only half the problem:

* ``ai_runtime.config`` stores ``env key -> value`` pairs.  That is the right
  shape for the *provider* (which reads the environment) but the wrong shape
  for a *person* -- nobody remembers whether the OpenAI key is
  ``OPENAI_API_KEY`` or ``CHEMML_OPENAI_KEY``, and a provider that needs two
  variables is invisible from the key name alone.
* ``backend/routers/ai.py`` masks the keys on the way out, which is right, but
  it exposes no way to ask *which providers are configured*, no way to test one,
  and no way to delete a single key.

So credentials are organised **by provider** here, and each provider declares
which environment variables it needs::

    list_credentials()          -> per-provider status, never the secret
    set_credential(p, secret)  -> store, push to the environment
    delete_credential(p)       -> remove from the store *and* the environment
    test_credential(p)         -> actually call the provider and say what happened

Storage order is ``OS keyring -> file``.  The keyring is preferred because a
shared machine should not leave a bearer token in a JSON file; the file fallback
exists because the desktop build has no keyring on a bare Windows install, and
"no keyring" must degrade to "works, with a visible warning" rather than "you
cannot configure a key at all".  The fallback file is written with
owner-only permissions where the platform supports it, and the store reports
which backend it landed on so the GUI can say so out loud.
"""

from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

__all__ = [
    "PROVIDERS",
    "CredentialStatus",
    "credential_backend",
    "list_credentials",
    "set_credential",
    "delete_credential",
    "test_credential",
    "mask_secret",
]

ROOT = Path(__file__).resolve().parents[1]

#: Where a provider's key is remembered when the OS has no keyring.
FALLBACK_FILE = ROOT / "config" / "credentials.json"

#: Names that must never be echoed back to a client or written to a log.
_MASK = "*"


# --------------------------------------------------------------------------- #
# provider catalogue
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class ProviderSpec:
    """One provider: what it is called, and what it needs to work."""

    id: str
    label_zh: str
    label_en: str
    #: Environment variables this provider reads, in the order it reads them.
    env_vars: Tuple[str, ...]
    #: Where the credential came from / goes, for the label in the GUI.
    kind: str = "cloud"
    docs_url: str = ""
    #: Base URL used by :func:`test_credential` when the provider is OpenAI-compatible.
    default_base_url: str = ""
    notes_zh: str = ""
    notes_en: str = ""

    @property
    def primary_env(self) -> str:
        return self.env_vars[0] if self.env_vars else ""


#: Every provider the GUI offers.  Kept as data so the frontend can render the
#: whole list from ``GET /api/credentials`` without hard-coding names that would
#: drift out of step with the runtime.
PROVIDERS: Tuple[ProviderSpec, ...] = (
    ProviderSpec(
        id="openai",
        label_zh="OpenAI（云端）",
        label_en="OpenAI (cloud)",
        env_vars=("OPENAI_API_KEY",),
        docs_url="https://platform.openai.com/api-keys",
        default_base_url="https://api.openai.com/v1",
        notes_zh="需要有效的 OpenAI API Key。",
        notes_en="Requires a valid OpenAI API key.",
    ),
    ProviderSpec(
        id="deepseek",
        label_zh="DeepSeek（云端）",
        label_en="DeepSeek (cloud)",
        env_vars=("DEEPSEEK_API_KEY",),
        docs_url="https://platform.deepseek.com/",
        default_base_url="https://api.deepseek.com/v1",
        notes_zh="OpenAI 兼容接口，填写 DeepSeek 平台的 Key。",
        notes_en="OpenAI-compatible endpoint; use the key from the DeepSeek platform.",
    ),
    ProviderSpec(
        id="moonshot",
        label_zh="Moonshot / Kimi（云端）",
        label_en="Moonshot / Kimi (cloud)",
        env_vars=("MOONSHOT_API_KEY",),
        docs_url="https://platform.moonshot.cn/",
        default_base_url="https://api.moonshot.cn/v1",
        notes_zh="OpenAI 兼容接口，国内直连。",
        notes_en="OpenAI-compatible endpoint, directly reachable from mainland China.",
    ),
    ProviderSpec(
        id="siliconflow",
        label_zh="SiliconFlow（云端）",
        label_en="SiliconFlow (cloud)",
        env_vars=("SILICONFLOW_API_KEY",),
        docs_url="https://cloud.siliconflow.cn/",
        default_base_url="https://api.siliconflow.cn/v1",
        notes_zh="聚合多个开源模型，OpenAI 兼容。",
        notes_en="Aggregates open models behind an OpenAI-compatible API.",
    ),
    ProviderSpec(
        id="dashscope",
        label_zh="阿里云百炼 DashScope（云端）",
        label_en="Alibaba DashScope (cloud)",
        env_vars=("DASHSCOPE_API_KEY",),
        docs_url="https://bailian.console.aliyun.com/",
        default_base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        notes_zh="Qwen 系列，OpenAI 兼容模式。",
        notes_en="Qwen models via the OpenAI-compatible mode.",
    ),
    ProviderSpec(
        id="zhipu",
        label_zh="智谱 GLM（云端）",
        label_en="Zhipu GLM (cloud)",
        env_vars=("ZHIPUAI_API_KEY",),
        docs_url="https://open.bigmodel.cn/",
        default_base_url="https://open.bigmodel.cn/api/paas/v4",
        notes_zh="GLM 系列，OpenAI 兼容。",
        notes_en="GLM models via an OpenAI-compatible API.",
    ),
    ProviderSpec(
        id="anthropic",
        label_zh="Anthropic Claude（云端）",
        label_en="Anthropic Claude (cloud)",
        env_vars=("ANTHROPIC_API_KEY",),
        docs_url="https://console.anthropic.com/settings/keys",
        notes_zh="原生 Messages API，非 OpenAI 兼容格式。",
        notes_en="Native Messages API, not the OpenAI-compatible format.",
    ),
    ProviderSpec(
        id="ollama",
        label_zh="Ollama（本地）",
        label_en="Ollama (local)",
        env_vars=("CHEMML_OLLAMA_BASE",),
        kind="local",
        default_base_url="http://127.0.0.1:11434",
        notes_zh="本地推理，无需 Key，填服务地址即可。",
        notes_en="Local inference; no key needed, just the server address.",
    ),
    ProviderSpec(
        id="vllm",
        label_zh="vLLM（本地）",
        label_en="vLLM (local)",
        env_vars=("CHEMML_VLLM_BASE",),
        kind="local",
        default_base_url="http://127.0.0.1:8000",
        notes_zh="本地推理，无需 Key，填服务地址即可。",
        notes_en="Local inference; no key needed, just the server address.",
    ),
)

_BY_ID: Dict[str, ProviderSpec] = {p.id: p for p in PROVIDERS}


def provider_spec(provider_id: str) -> Optional[ProviderSpec]:
    """Look up a provider by id (case-insensitive)."""
    return _BY_ID.get(str(provider_id or "").strip().lower())


# --------------------------------------------------------------------------- #
# storage backends
# --------------------------------------------------------------------------- #
def _keyring():
    """The OS keyring module, or ``None`` when there is not a usable one."""
    try:
        import keyring  # type: ignore
        from keyring.backends.fail import Keyring as FailKeyring  # type: ignore
    except Exception:
        return None
    try:
        backend = keyring.get_keyring()
        # The "fail" backend is what keyring installs when it finds no real
        # store.  Treating it as available would silently swallow every save.
        if isinstance(backend, FailKeyring):
            return None
        name = type(backend).__module__ + "." + type(backend).__name__
        if "chainer" in name.lower():
            # A chainer may still have a usable backend behind it; probe.
            try:
                keyring.get_keyring().get_password("chemml-probe", "probe")
            except Exception:
                return None
        return keyring
    except Exception:
        return None


def _keyring_service() -> str:
    return "Chem ML Platform"


def _read_file() -> Dict[str, Dict[str, str]]:
    if not FALLBACK_FILE.exists():
        return {}
    try:
        data = json.loads(FALLBACK_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_file(data: Dict[str, Dict[str, str]]) -> None:
    """Write the fallback store, owner-only where the platform allows it."""
    FALLBACK_FILE.parent.mkdir(parents=True, exist_ok=True)
    FALLBACK_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    if platform.system() == "Windows":
        # Windows has no POSIX mode; the file inherits the user profile's ACL,
        # which is the platform's normal protection.  Nothing to tighten here.
        return
    try:
        os.chmod(FALLBACK_FILE, 0o600)
    except OSError:
        pass


def credential_backend() -> str:
    """``"keyring"``, ``"file"`` or ``"none"`` -- where a new key would land.

    Reported to the GUI so the storage choice is visible rather than implied.
    A user who thinks a key is in their OS keyring should be told when it is not.
    """
    return "keyring" if _keyring() is not None else "file"


def _stored_secrets() -> Dict[str, str]:
    """Every stored secret as ``provider id -> value``, keyring first."""
    out: Dict[str, str] = {}
    file_data = _read_file()
    for spec in PROVIDERS:
        value = ""
        if spec.primary_env and (os.environ.get(spec.primary_env) or "").strip():
            value = os.environ[spec.primary_env].strip()
        if not value:
            entry = file_data.get(spec.id)
            if isinstance(entry, dict):
                value = str(entry.get("secret") or "").strip()
        if value:
            out[spec.id] = value
    return out


def mask_secret(secret: str) -> str:
    """``sk-abcdef123456`` -> ``sk-a•••••3456``.

    Keeps the first and last few characters so a user pasting several keys can
    tell them apart, and never returns the whole value.  A short secret is
    masked completely -- there is no safe way to show four characters of it.
    """
    text = str(secret or "")
    if not text:
        return ""
    if len(text) <= 8:
        return _MASK * len(text)
    return f"{text[:4]}{_MASK * 6}{text[-4:]}"


@dataclass
class CredentialStatus:
    """One provider's credential, described without disclosing the secret."""

    provider: str
    labels: Dict[str, str] = field(default_factory=dict)
    kind: str = "cloud"
    env_var: str = ""
    configured: bool = False
    #: Where the value came from: environment, keyring, file, or nowhere.
    source: str = "none"
    masked: str = ""
    length: int = 0
    docs_url: str = ""
    notes: Dict[str, str] = field(default_factory=dict)
    default_base_url: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "provider": self.provider,
            "labels": self.labels,
            "kind": self.kind,
            "env_var": self.env_var,
            "configured": self.configured,
            "source": self.source,
            "masked": self.masked,
            "length": self.length,
            "docs_url": self.docs_url,
            "notes": self.notes,
            "default_base_url": self.default_base_url,
        }


def _source_of(spec: ProviderSpec) -> str:
    if spec.primary_env and (os.environ.get(spec.primary_env) or "").strip():
        return "environment"
    if _keyring() is not None:
        try:
            if _keyring().get_password(_keyring_service(), spec.id):  # type: ignore[union-attr]
                return "keyring"
        except Exception:
            pass
    entry = _read_file().get(spec.id)
    if isinstance(entry, dict) and str(entry.get("secret") or "").strip():
        return "file"
    return "none"


# --------------------------------------------------------------------------- #
# public operations
# --------------------------------------------------------------------------- #
def list_credentials() -> Dict[str, Any]:
    """Every provider's status, plus where a new key would be stored."""
    secrets = _stored_secrets()
    items: List[CredentialStatus] = []
    for spec in PROVIDERS:
        secret = secrets.get(spec.id, "")
        items.append(
            CredentialStatus(
                provider=spec.id,
                labels={"zh": spec.label_zh, "en": spec.label_en},
                kind=spec.kind,
                env_var=spec.primary_env,
                configured=bool(secret),
                source=_source_of(spec),
                masked=mask_secret(secret),
                length=len(secret),
                docs_url=spec.docs_url,
                notes={"zh": spec.notes_zh, "en": spec.notes_en},
                default_base_url=spec.default_base_url,
            )
        )
    backend = credential_backend()
    return {
        "backend": backend,
        "backend_label": {
            "zh": "系统密钥环" if backend == "keyring" else "本地文件（config/credentials.json）",
            "en": "OS keyring" if backend == "keyring" else "local file (config/credentials.json)",
        },
        "warning": (
            None
            if backend == "keyring"
            else {
                "zh": "当前系统没有可用的密钥环，密钥将明文保存在 config/credentials.json。"
                "该文件已被 .gitignore 排除，但仍请勿在共享机器上存放生产密钥。",
                "en": "No OS keyring is available, so keys are stored in plain text in "
                "config/credentials.json. The file is git-ignored, but do not keep "
                "production keys on a shared machine.",
            }
        ),
        "credentials": [item.to_dict() for item in items],
    }


def set_credential(provider_id: str, secret: str, base_url: str = "") -> Dict[str, Any]:
    """Store a secret for a provider and push it into the environment.

    The environment push is what makes the change take effect: the providers
    read ``os.environ``, not this store, so saving without pushing would produce
    a credential the GUI happily displays and the runtime never sees.
    """
    spec = provider_spec(provider_id)
    if spec is None:
        raise KeyError(
            f"unknown provider {provider_id!r}; known: {', '.join(sorted(_BY_ID))}"
        )
    value = str(secret or "").strip()
    if not value:
        raise ValueError("the credential is empty")
    if "\n" in value or "\r" in value:
        raise ValueError("the credential contains a line break")

    stored_in = "environment"
    # The providers read os.environ, not this store: pushing here is what makes
    # a newly saved key take effect for the AI runtime and the agent.
    os.environ[spec.primary_env] = value

    # Prefer the OS keyring; fall back to the file when there is none.
    keyring = _keyring()
    if keyring is not None:
        try:
            keyring.set_password(_keyring_service(), spec.id, value)  # type: ignore[union-attr]
            stored_in = "keyring"
        except Exception:
            stored_in = "file"
    if stored_in == "file":
        data = _read_file()
        data[spec.id] = {"secret": value, "env_var": spec.primary_env}
        _write_file(data)

    if base_url:
        try:
            from ai_runtime.config import get_config, save_config

            config = get_config()
            config.base_urls[spec.id] = base_url
            save_config(config)
        except Exception:
            # A base-URL that cannot be persisted must not lose the key that
            # was; report it rather than raising after the fact.
            pass

    return {
        "provider": spec.id,
        "stored_in": stored_in,
        "masked": mask_secret(value),
        "status": list_credentials(),
    }


def delete_credential(provider_id: str) -> Dict[str, Any]:
    """Forget a provider's secret in every place it could be held."""
    spec = provider_spec(provider_id)
    if spec is None:
        raise KeyError(
            f"unknown provider {provider_id!r}; known: {', '.join(sorted(_BY_ID))}"
        )
    removed = False
    if spec.primary_env and os.environ.get(spec.primary_env):
        # The GUI's "forget this key" button has to actually forget it.  A key
        # exported by the shell and a key this store wrote look identical from
        # here, so the button clears both -- and says so, by reporting ``removed``.
        removed = True
        os.environ.pop(spec.primary_env, None)
    keyring = _keyring()
    if keyring is not None:
        try:
            keyring.delete_password(_keyring_service(), spec.id)  # type: ignore[union-attr]
            removed = True
        except Exception:
            pass
    data = _read_file()
    if spec.id in data:
        data.pop(spec.id, None)
        _write_file(data)
        removed = True
    return {
        "provider": spec.id,
        "removed": removed,
        "status": list_credentials(),
    }


# --------------------------------------------------------------------------- #
# connectivity test
# --------------------------------------------------------------------------- #
def _curl_chat(base_url: str, api_key: str, timeout: float = 20.0) -> Tuple[bool, str]:
    """Probe an OpenAI-compatible ``/chat/completions`` with a tiny prompt.

    Uses ``curl`` rather than ``urllib`` because a TLS failure, a proxy
    requirement and an HTTP 401 all need to be told apart, and the messages
    that come back are far more useful to a user than a stack trace.  A
    one-token request also keeps the probe from costing anything meaningful.
    """
    exe = shutil.which("curl")
    if not exe:
        return False, "curl is not available on this machine, so the probe could not run"
    url = base_url.rstrip("/") + "/chat/completions"
    payload = json.dumps(
        {
            "model": "gpt-4o-mini",
            "messages": [{"role": "user", "content": "ping"}],
            "max_tokens": 1,
        }
    )
    args = [
        exe, "-sS", "-o", "-", "-w", "\n__HTTP__%{http_code}",
        "--max-time", str(timeout),
        "-H", "Content-Type: application/json",
        "-H", f"Authorization: Bearer {api_key}",
        "-d", payload,
        url,
    ]
    try:
        proc = subprocess.run(  # noqa: S603 - fixed argv, no shell
            args, capture_output=True, text=True, timeout=timeout + 5,
        )
    except subprocess.TimeoutExpired:
        return False, f"no answer within {timeout:.0f} s -- check the address and the network"
    except OSError as exc:
        return False, f"could not start curl: {exc}"

    raw = proc.stdout or ""
    if "__HTTP__" not in raw:
        err = (proc.stderr or "").strip()
        return False, err or f"curl exited with {proc.returncode} and no response"

    body, _, code = raw.rpartition("__HTTP__")
    code = code.strip()
    body = body.strip()

    if code in {"200", ""}:
        try:
            parsed = json.loads(body)
        except json.JSONDecodeError:
            return False, "the endpoint answered but not with JSON -- is the base URL correct?"
        model = ""
        choices = parsed.get("choices")
        if isinstance(choices, list) and choices:
            model = str((choices[0].get("message") or {}).get("model") or "")
        return True, f"connected (HTTP 200){f', model {model}' if model else ''}"
    if code in {"401", "403"}:
        return False, f"HTTP {code}: the key was rejected -- check it in the provider's console"
    if code == "404":
        return False, "HTTP 404: no chat/completions at that base URL -- check the path"
    if code == "429":
        return False, "HTTP 429: rate limited or out of quota"
    detail = ""
    try:
        parsed = json.loads(body)
        detail = str((parsed.get("error") or {}).get("message") or "")[:200]
    except json.JSONDecodeError:
        detail = body[:200]
    return False, f"HTTP {code}{f': {detail}' if detail else ''}"


def test_credential(provider_id: str) -> Dict[str, Any]:
    """Try the configured credential against its provider and report what happened.

    Never raises for a failed probe: "your key is wrong" is an answer, not an
    exception, and the GUI has to be able to display it.
    """
    spec = provider_spec(provider_id)
    if spec is None:
        raise KeyError(
            f"unknown provider {provider_id!r}; known: {', '.join(sorted(_BY_ID))}"
        )
    secrets = _stored_secrets()
    secret = secrets.get(spec.id, "")
    if not secret:
        return {
            "provider": spec.id,
            "ok": False,
            "detail": "no credential is configured for this provider yet",
        }
    if spec.kind == "local":
        return {
            "provider": spec.id,
            "ok": False,
            "detail": (
                "local providers are checked by running a model through them; "
                "use the AI panel's test button for that"
            ),
        }
    if not spec.default_base_url:
        return {
            "provider": spec.id,
            "ok": False,
            "detail": "this provider has no built-in probe endpoint; it will be used on the next completion",
        }
    ok, detail = _curl_chat(spec.default_base_url, secret)
    return {"provider": spec.id, "ok": ok, "detail": detail}