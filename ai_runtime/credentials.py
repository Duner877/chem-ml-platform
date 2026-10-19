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
import logging
import os
import platform
import re
import shutil
import subprocess
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlsplit

from .config import load_config

__all__ = [
    "PROVIDERS",
    "CredentialStatus",
    "credential_backend",
    "list_credentials",
    "list_provider_models",
    "provider_model",
    "set_credential",
    "set_provider_model",
    "delete_credential",
    "test_credential",
    "mask_secret",
]

ROOT = Path(__file__).resolve().parents[1]

#: Where a provider's key is remembered when the OS has no keyring.
FALLBACK_FILE = ROOT / "config" / "credentials.json"

#: Names that must never be echoed back to a client or written to a log.
_MASK = "*"

#: Shapes that look like a bearer credential, used to scrub provider error text.
_KEY_SHAPED = re.compile(
    r"(?:sk|rk|xai|gsk|hf|api)[-_][A-Za-z0-9_\-]{8,}|"
    r"\b[A-Za-z0-9_\-]{28,}\b"
)


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

    # -- probe (v0.7.3 audit P1-1) ------------------------------------------ #
    #: Model name the connectivity check asks for.  A hard-coded ``gpt-4o-mini``
    #: (what this used to send to *every* provider) produces a false negative on
    #: any OpenAI-compatible service that does not happen to carry that model:
    #: DeepSeek and Moonshot would answer HTTP 400 / 404 with a perfectly valid
    #: key, and the GUI would tell the user their key is wrong.  Per provider.
    probe_model: str = ""
    #: Endpoint appended to the base URL.  Anthropic's Messages API is not
    #: OpenAI-shaped, so it needs its own path and body.
    probe_path: str = "/chat/completions"
    #: ``"openai"`` (chat/completions) or ``"anthropic"`` (native messages).
    probe_style: str = "openai"
    #: Extra headers for the probe (Anthropic requires the API version).
    probe_headers: Tuple[Tuple[str, str], ...] = ()
    # -- model catalogue (v0.7.3) ------------------------------------------- #
    #: Endpoint that lists the models this account may call, or ``""`` when the
    #: provider publishes no such listing.  Appended to the *base* URL, exactly
    #: like :attr:`probe_path`, because OpenAI-compatible gateways put it at
    #: ``<base>/models`` while Ollama keeps it at ``<base>/api/tags`` -- a single
    #: hard-coded ``/v1/models`` silently lists nothing on a local server.
    models_path: str = ""
    #: Key holding the model id in a listing entry.  OpenAI-compatible servers
    #: use ``id``; Ollama's ``/api/tags`` uses ``name``.
    models_id_key: str = "id"

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
        probe_model="gpt-4o-mini",
        models_path="/models",
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
        # DeepSeek does not serve any OpenAI model name; asking for one is a
        # guaranteed 400 and would read as "your key is invalid".
        probe_model="deepseek-chat",
        models_path="/models",
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
        probe_model="moonshot-v1-8k",
        models_path="/models",
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
        probe_model="Qwen/Qwen2.5-7B-Instruct",
        models_path="/models",
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
        probe_model="qwen-turbo",
        models_path="/models",
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
        probe_model="glm-4-flash",
        models_path="/models",
        notes_zh="GLM 系列，OpenAI 兼容。",
        notes_en="GLM models via an OpenAI-compatible API.",
    ),
    ProviderSpec(
        id="anthropic",
        label_zh="Anthropic Claude（云端）",
        label_en="Anthropic Claude (cloud)",
        env_vars=("ANTHROPIC_API_KEY",),
        docs_url="https://console.anthropic.com/settings/keys",
        # Native Messages API.  The old probe sent an OpenAI-shaped body to
        # this provider too, which could only ever fail.
        default_base_url="https://api.anthropic.com",
        probe_model="claude-3-5-haiku-latest",
        probe_path="/v1/messages",
        probe_style="anthropic",
        probe_headers=(("anthropic-version", "2023-06-01"),),
        models_path="/v1/models",
        notes_zh="原生 Messages API，非 OpenAI 兼容格式。",
        notes_en="Native Messages API, not the OpenAI-compatible format.",
    ),
    ProviderSpec(
        id="nvidia",
        label_zh="NVIDIA NIM（云端，免费额度）",
        label_en="NVIDIA NIM (cloud, free tier)",
        env_vars=("NVIDIA_API_KEY",),
        docs_url="https://build.nvidia.com/",
        # OpenAI-compatible gateway in front of NVIDIA-hosted open models.
        default_base_url="https://integrate.api.nvidia.com/v1",
        # Measured on 2026-10-18 against a live key: ``/v1/models`` lists 81 ids,
        # but many of them answer HTTP 410 (end-of-life) or 404, and a few
        # (deepseek-ai/deepseek-v4.1-flash, z-ai/glm-5.3*) accept the
        # connection and then never answer.  So the catalogue is *not* a
        # availability list and the probe model has to be one measured to
        # return 200 in ~1 s.  ``openai/gpt-oss-20b`` did; the failure modes
        # above are what ``_classify_http`` now distinguishes.
        probe_model="openai/gpt-oss-20b",
        models_path="/models",
        notes_zh=(
            "NVIDIA 开放模型托管平台，OpenAI 兼容接口，有免费额度。"
            "模型名形如 meta/llama-3.3-70b-instruct、openai/gpt-oss-20b；"
            "平台的模型目录包含已下线模型，填错会得到 410/404 或长时间无响应。"
            "点「获取模型列表」可以看到全部登记在册的 id，但列表不等于可用。"
        ),
        notes_en=(
            "NVIDIA's host for open models behind an OpenAI-compatible API, "
            "with a free tier. Model ids look like meta/llama-3.3-70b-instruct "
            "or openai/gpt-oss-20b. The catalogue includes end-of-life ids, so "
            "a wrong name yields 410/404 or no answer at all. Fetching the model "
            "list shows every registered id -- but the list is not an "
            "availability list."
        ),
    ),
    ProviderSpec(
        id="ollama",
        label_zh="Ollama（本地）",
        label_en="Ollama (local)",
        env_vars=("CHEMML_OLLAMA_BASE",),
        kind="local",
        default_base_url="http://127.0.0.1:11434",
        # /api/tags needs no key at all: for a local server the question is
        # "is it up and does it have a model", not "is the key valid".
        probe_path="/api/tags",
        models_path="/api/tags",
        models_id_key="name",
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
        probe_path="/v1/models",
        models_path="/v1/models",
        notes_zh="本地推理，无需 Key，填服务地址即可。",
        notes_en="Local inference; no key needed, just the server address.",
    ),
)

_BY_ID: Dict[str, ProviderSpec] = {p.id: p for p in PROVIDERS}

# Environment variables this process pushed via ``set_credential``.  A variable
# the user exported before launching the app belongs to their shell, and
# deleting a credential must not destroy it -- see ``delete_credential``.
_SELF_SET: set = set()

_log = logging.getLogger("chemml.credentials")


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
    """Every stored secret as ``provider id -> value``, keyring first.

    The keyring read was missing while :func:`_source_of` had it, so on a
    machine with a working keyring and no environment variable -- which is the
    normal state after a restart -- the listing said a key was missing while
    the *source* column for the same provider said ``keyring``.  Worse than an
    inconsistency: :func:`test_credential` reads its secret from here, so the
    probe reported "no credential configured" for a key the user had just
    saved, and only after restarting in an environment that happened to export
    the variable did it work.  A credential that is stored but unreadable is
    the same failure as no credential at all.
    """
    out: Dict[str, str] = {}
    file_data = _read_file()
    keyring = _keyring()
    for spec in PROVIDERS:
        value = ""
        if spec.primary_env and (os.environ.get(spec.primary_env) or "").strip():
            value = os.environ[spec.primary_env].strip()
        if not value and keyring is not None:
            try:
                value = str(
                    keyring.get_password(_keyring_service(), spec.id) or ""  # type: ignore[union-attr]
                ).strip()
            except Exception:  # noqa: BLE001 - one locked entry must not hide the rest
                value = ""
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


def _redact(text: str, secret: str) -> str:
    """Strip a secret (and anything shaped like one) out of free-form text.

    Provider error messages are third-party content on their way to the
    browser.  They routinely quote the credential back at us, so they cannot be
    forwarded unfiltered.
    """
    out = str(text or "")
    key = str(secret or "")
    if key:
        out = out.replace(key, mask_secret(key))
    # Catch keys the provider may have partially echoed or reformatted.
    return _KEY_SHAPED.sub(lambda m: m.group(0)[:4] + _MASK * 6, out)


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
    #: Model id the user picked from the provider's catalogue ("" = use default).
    selected_model: str = ""
    #: The model id that will actually be sent when a node names none.
    effective_model: str = ""
    #: Catalogue endpoint, "" when the provider publishes none.
    models_path: str = ""

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
            "selected_model": self.selected_model,
            "effective_model": self.effective_model,
            "models_path": self.models_path,
            "has_catalogue": bool(self.models_path),
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
    try:
        chosen = dict(getattr(load_config(), "models", {}) or {})
    except Exception:  # noqa: BLE001 - a broken config must not break the listing
        chosen = {}
    items: List[CredentialStatus] = []
    for spec in PROVIDERS:
        secret = secrets.get(spec.id, "")
        selected = str(chosen.get(spec.id, "") or "").strip()
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
                selected_model=selected,
                effective_model=selected or spec.probe_model,
                models_path=spec.models_path,
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

    os.environ[spec.primary_env] = value
    _SELF_SET.add(spec.primary_env)

    # Prefer the OS keyring; fall back to the file both when there is no keyring
    # at all and when the keyring refuses the write.  The desktop build is the
    # case that matters: with no backend installed, a keyring branch that is
    # simply skipped would leave the secret living only in this process -- the
    # GUI would report it as configured, ``list_credentials`` would advertise a
    # file that does not exist, and the key would be gone after a restart.
    keyring = _keyring()
    if keyring is not None:
        try:
            keyring.set_password(_keyring_service(), spec.id, value)  # type: ignore[union-attr]
            stored_in = "keyring"
        except Exception:
            stored_in = "file"
    else:
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
        except Exception as exc:
            # A base-URL that cannot be persisted must not lose the key that
            # was, and must not fail silently either -- the caller needs to know
            # the endpoint override did not stick, or it will debug the wrong
            # thing when the provider keeps rejecting requests.
            _log.warning(
                "could not persist the base URL for %s: %s", spec.id, exc
            )

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
    preserved: List[str] = []
    if spec.primary_env and os.environ.get(spec.primary_env):
        if spec.primary_env in _SELF_SET:
            removed = True
            os.environ.pop(spec.primary_env, None)
            _SELF_SET.discard(spec.primary_env)
        else:
            # Inherited from the shell that launched us.  Clearing it would
            # destroy something we never owned and cannot restore, so it stays
            # -- and the caller is told, because otherwise "deleted" would read
            # as "this provider can no longer be used" when in fact it still
            # can.
            preserved.append(spec.primary_env)
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
        "shell_env_preserved": preserved,
        "status": list_credentials(),
    }


# --------------------------------------------------------------------------- #
# model catalogue
# --------------------------------------------------------------------------- #
#: Upper bound on how many ids are returned to the GUI.  NVIDIA's catalogue
#: holds 81 and grows every quarter; shipping all of them into a dropdown
#: makes it unusable, and the client keeps whatever the user picked either way.
MODEL_LIST_LIMIT = 500


def _parse_model_listing(body: str, spec: ProviderSpec) -> List[Dict[str, str]]:
    """Pull ``{"id": ..., ...}`` entries out of a provider's model listing.

    Handles the three shapes actually seen: OpenAI-compatible ``{"data": [...]}``
    (the key is not fixed -- one gateway nests it under ``models``), Ollama's
    ``{"models": [{"name": "qwen2.5:7b", ...}]}``, and Anthropic's
    ``{"data": [{"id": ...}]}``.
    """
    try:
        parsed = json.loads(body)
    except json.JSONDecodeError:
        return []
    # Some gateways answer with a bare array rather than an object.
    if isinstance(parsed, list):
        entries: Any = parsed
    elif isinstance(parsed, dict):
        entries = None
        for key in ("data", "models", "result"):
            value = parsed.get(key)
            if isinstance(value, list):
                entries = value
                break
    else:
        return []
    if entries is None:
        # A 200 with no list field is a shape this parser does not know, not an
        # empty catalogue.  Returning [] here is what the caller turns into a
        # clear diagnostic; iterating None here would raise instead.
        return []

    out: List[Dict[str, str]] = []
    for item in entries:
        if isinstance(item, str):
            out.append({"id": item, "owned_by": ""})
            continue
        if not isinstance(item, dict):
            continue
        # Ollama's /api/tags carries the model under "name"; everything else
        # uses "id".  Accept either rather than trusting the declared key, so a
        # provider that switches convention does not silently list nothing.
        ident = str(item.get(spec.models_id_key) or item.get("id") or item.get("name") or "").strip()
        if not ident:
            continue
        entry = {"id": ident, "owned_by": str(item.get("owned_by") or item.get("owner") or "")}
        size = item.get("size") or item.get("parameter_size") or item.get("context_length")
        if size not in (None, ""):
            entry["detail"] = str(size)
        out.append(entry)
    return out


def _selected_model(spec: ProviderSpec) -> str:
    """The model id the user chose for this provider, if any."""
    try:
        config = load_config()
        return str(getattr(config, "models", {}).get(spec.id, "") or "").strip()
    except Exception:  # noqa: BLE001 - a broken config must not break the listing
        return ""


def set_provider_model(provider_id: str, model: str) -> Dict[str, Any]:
    """Remember the user's chosen model for a provider.

    Persisted next to the base-URL override (``config/ai.json``) and read back
    by :mod:`nodes.ai.llm`, so a model picked in the GUI is the model the
    canvas actually calls.  An empty *model* clears the choice.
    """
    spec = provider_spec(provider_id)
    if spec is None:
        raise KeyError(
            f"unknown provider {provider_id!r}; known: {', '.join(sorted(_BY_ID))}"
        )
    value = str(model or "").strip()
    if value and ("\n" in value or "\r" in value):
        raise ValueError("the model id contains a line break")
    try:
        from ai_runtime.config import get_config, save_config

        config = get_config()
        config.models = {
            k: v for k, v in dict(getattr(config, "models", {}) or {}).items() if k != spec.id
        }
        if value:
            config.models[spec.id] = value
        save_config(config)
    except Exception as exc:  # noqa: BLE001
        _log.warning("could not persist the model for %s: %s", spec.id, exc)
        raise ValueError(f"the model choice could not be saved: {exc}") from exc
    return {"provider": spec.id, "model": value}


def provider_model(provider_id: str) -> str:
    """The model id chosen for *provider_id*, falling back to its probe model.

    This is what the runtime asks for when a node does not name a model
    explicitly.  The user's choice wins over the built-in default, because the
    whole point of listing the catalogue was to act on it.
    """
    spec = provider_spec(provider_id)
    if spec is None:
        return ""
    return _selected_model(spec) or spec.probe_model


def list_provider_models(provider_id: str, timeout: float = 20.0) -> Dict[str, Any]:
    """Ask the provider which models this credential may address.

    Returns a *catalogue*, and says so in the payload.  Measured against a live
    NVIDIA key on 2026-10-18: ``/v1/models`` answered 200 with 81 ids, yet many
    of them answer HTTP 410 on an actual completion, and
    ``deepseek-ai/deepseek-v4.1-flash`` accepted the connection and then returned
    zero bytes for 300 s.  Presenting such a list as "available models" would
    be the same mistake as presenting it as an availability guarantee, so the
    GUI offers it as a catalogue and the connectivity test remains the thing
    that establishes whether a given id works.
    """
    spec = provider_spec(provider_id)
    if spec is None:
        raise KeyError(
            f"unknown provider {provider_id!r}; known: {', '.join(sorted(_BY_ID))}"
        )
    if not spec.models_path:
        return {
            "provider": spec.id,
            "ok": False,
            "outcome": PROBE_UNSUPPORTED,
            "models": [],
            "detail": "this provider publishes no model catalogue endpoint",
        }

    secret = _stored_secrets().get(spec.id, "")
    if not secret and spec.kind != "local":
        return {
            "provider": spec.id,
            "ok": False,
            "outcome": PROBE_NO_CREDENTIAL,
            "models": [],
            "detail": "save a key for this provider first -- the catalogue is account-specific",
        }

    base_url = _effective_base_url(spec)
    if not base_url:
        return {
            "provider": spec.id,
            "ok": False,
            "outcome": PROBE_UNSUPPORTED,
            "models": [],
            "detail": "set a base URL for this provider first",
        }

    url = base_url.rstrip("/") + spec.models_path
    local = spec.kind == "local"
    args, err = _curl_bootstrap(spec, url, 5.0 if local else timeout)
    if err is not None:
        return {
            "provider": spec.id,
            "ok": False, "outcome": err[1], "models": [],
            "detail": err[2],
        }

    headers = {"Content-Type": "application/json"}
    if not local:
        if spec.probe_style == "anthropic":
            headers["x-api-key"] = secret
        elif secret:
            headers["Authorization"] = f"Bearer {secret}"
    for key, value in spec.probe_headers:
        headers[key] = value
    for key, value in headers.items():
        args += ["-H", f"{key}: {value}"]
    args += ["-X", "GET"]

    code, body_text, err = _curl_response(args, url, secret, 5.0 if local else timeout)
    if err is not None:
        return {
            "provider": spec.id, "ok": False, "outcome": err[1], "models": [],
            "detail": err[2],
        }

    if code != "200":
        ok, outcome, detail = _classify_http(code, body_text, spec, secret)
        return {
            "provider": spec.id, "ok": False, "outcome": outcome, "models": [],
            "detail": detail, "http_status": code,
        }

    models = _parse_model_listing(body_text, spec)
    if not models:
        # A 200 that lists nothing is not an empty catalogue: it is a gateway
        # answering a different shape than the one parsed here, and saying
        # "0 models available" would send the user off to regenerate a key that
        # demonstrably works.
        return {
            "provider": spec.id,
            "ok": False,
            "outcome": PROBE_BAD_RESPONSE,
            "models": [],
            "detail": (
                f"{url} answered HTTP 200 but the response listed no model ids "
                "-- this gateway may not implement the catalogue endpoint"
            ),
        }

    selected = _selected_model(spec)
    ids = [entry["id"] for entry in models]
    truncated = len(models) > MODEL_LIST_LIMIT
    if truncated:
        models = models[:MODEL_LIST_LIMIT]
    if selected and selected not in ids and not truncated:
        # Keep a hand-typed id visible instead of dropping it silently -- the
        # user can still reach the model by name even when the catalogue does
        # not carry it.
        models = [{"id": selected, "owned_by": "", "detail": "manually set"}, *models]

    return {
        "provider": spec.id,
        "ok": True,
        "outcome": PROBE_OK,
        "base_url": base_url,
        "models": models,
        "count": len(models),
        "total": len(ids),
        "truncated": truncated,
        "selected": selected,
        "default_model": spec.probe_model,
        "catalogue_only": True,
        "detail": (
            f"{len(ids)} model id(s) registered at {url}"
            + (" -- a catalogue, not a verified availability list; use 测试 to confirm one"
               if len(ids) > 1 else "")
        ),
    }


# --------------------------------------------------------------------------- #
# connectivity test
# --------------------------------------------------------------------------- #
#: Outcome classes a probe can report.  The GUI colours these differently, and
#: they must not be collapsed: "your key is wrong" and "the host name does not
#: resolve" call for completely different user actions.
ProbeOutcome = str

PROBE_OK: ProbeOutcome = "ok"
PROBE_NO_CREDENTIAL: ProbeOutcome = "no_credential"
PROBE_INVALID_KEY: ProbeOutcome = "invalid_key"
PROBE_FORBIDDEN: ProbeOutcome = "forbidden"
PROBE_BAD_ENDPOINT: ProbeOutcome = "bad_endpoint"
PROBE_MODEL_UNSUPPORTED: ProbeOutcome = "model_unsupported"
PROBE_RATE_LIMITED: ProbeOutcome = "rate_limited"
PROBE_NETWORK: ProbeOutcome = "network_unreachable"
PROBE_TIMEOUT: ProbeOutcome = "timeout"
PROBE_BAD_RESPONSE: ProbeOutcome = "bad_response"
PROBE_UNSUPPORTED: ProbeOutcome = "not_probeable"
PROBE_UNAVAILABLE: ProbeOutcome = "probe_tool_missing"


def _probe_body(spec: ProviderSpec) -> Optional[Dict[str, Any]]:
    """The JSON body for this provider's probe, or ``None`` if it needs none.

    ``None`` means "GET something that only proves the server is listening" --
    the right probe for Ollama and vLLM, where the failure being diagnosed is
    "is the service up", not "is this token accepted".
    """
    if spec.kind == "local":
        return None
    if spec.probe_style == "anthropic":
        return {
            "model": spec.probe_model,
            "max_tokens": 1,
            "messages": [{"role": "user", "content": "ping"}],
        }
    return {
        "model": spec.probe_model,
        "messages": [{"role": "user", "content": "ping"}],
        "max_tokens": 1,
    }


def _probe_headers(spec: ProviderSpec, api_key: str) -> Dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if spec.probe_style == "anthropic":
        # Anthropic authenticates with x-api-key, not Bearer.
        headers["x-api-key"] = api_key
    elif api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    for key, value in spec.probe_headers:
        headers[key] = value
    return headers


def _classify_http(code: str, body: str, spec: ProviderSpec, api_key: str) -> Tuple[bool, ProbeOutcome, str]:
    """Turn an HTTP status into (ok, outcome, human message).

    The model-name branch matters more than it looks: an OpenAI-compatible
    gateway that does not carry the provider's default model answers 400/404
    with "model not found" *while the key is perfectly valid*.  Reporting that
    as an invalid key sends the user off to regenerate a working credential.
    """
    if code in {"200", ""}:
        try:
            parsed = json.loads(body)
        except json.JSONDecodeError:
            return False, PROBE_BAD_RESPONSE, (
                "the endpoint answered but not with JSON -- is the base URL correct?"
            )
        model = ""
        choices = parsed.get("choices")
        if isinstance(choices, list) and choices:
            message = choices[0].get("message") or {}
            model = str(message.get("model") or choices[0].get("model") or "")
        if not model and isinstance(parsed.get("models"), list):
            # /v1/models and /api/tags shapes: a listing is proof of life.
            first = parsed["models"][0] if parsed["models"] else {}
            if isinstance(first, dict):
                model = str(first.get("id") or first.get("name") or "")
        suffix = f", model {model}" if model else ""
        return True, PROBE_OK, f"connected (HTTP 200){suffix}"

    if code in {"401"}:
        return False, PROBE_INVALID_KEY, (
            "HTTP 401: the key was rejected -- check it in the provider's console"
        )
    if code == "403":
        return False, PROBE_FORBIDDEN, (
            "HTTP 403: the key authenticated but is not permitted to use "
            f"{spec.probe_model or 'this model'} -- it may need to be enabled in the console first"
        )
    if code == "429":
        return False, PROBE_RATE_LIMITED, (
            "HTTP 429: rate limited or out of quota (the key itself may be fine)"
        )

    detail = ""
    try:
        parsed = json.loads(body)
        error = parsed.get("error")
        detail = str((error or {}).get("message") if isinstance(error, dict) else error or "")
        if not detail:
            # NVIDIA NIM (and any RFC 7807 style gateway) answers
            # ``{"title": "Gone", "detail": "..."}`` with no ``error`` object.
            # Reading only ``error.message`` threw that whole explanation away
            # and left a bare HTTP status to report.
            detail = str(parsed.get("detail") or parsed.get("message") or "")
            title = str(parsed.get("title") or "").strip()
            if detail and title and title.lower() not in detail.lower():
                detail = f"{title}: {detail}"
    except json.JSONDecodeError:
        detail = body
    detail = _redact(detail[:300], api_key)

    # Measured against a live NVIDIA key on 2026-10-18: its catalogue lists
    # end-of-life model ids, which answer HTTP 410 Gone, and its serving tiers
    # answer HTTP 503 when saturated.  Neither means the key is wrong -- the
    # remedy is "choose another model" or "retry shortly", and reporting
    # either as a bad credential sends the user to regenerate a key that works.
    if code == "410":
        return False, PROBE_MODEL_UNSUPPORTED, (
            f"HTTP 410: {spec.probe_model or 'this model'} has been retired on "
            f"this platform ({detail or 'end of life'}) -- choose another model id"
        )
    if code == "503":
        return False, PROBE_RATE_LIMITED, (
            "HTTP 503: the serving tier is saturated right now "
            f"({detail or 'resource exhausted'}) -- the key is fine, retry shortly"
        )

    # "No such model" is a probe artefact, not a credential problem.  The
    # message has to *name* the model for this to fire: a bare 404 "not found"
    # is the endpoint itself missing, and reporting that as a model mismatch
    # would send the user editing the wrong setting.
    lowered = detail.lower()
    names_a_model = (
        spec.probe_model.lower() in lowered
        or ("model" in lowered and any(
            # "support" covers both "unsupported" and "not supported"; the
            # providers really do word this half a dozen different ways.
            phrase in lowered
            for phrase in ("not found", "does not exist", "unknown", "support", "no access")
        ))
    )
    if code in {"400", "404", "422"} and names_a_model:
        return False, PROBE_MODEL_UNSUPPORTED, (
            f"the endpoint rejected the probe model {spec.probe_model!r} "
            f"({detail or code}) -- this is a model-name mismatch, not necessarily a bad key"
        )
    if code == "404":
        return False, PROBE_BAD_ENDPOINT, (
            f"HTTP 404: no {spec.probe_path} at that base URL -- check the path"
        )
    if code in {"400", "422"}:
        return False, PROBE_BAD_RESPONSE, (
            f"HTTP {code}: the endpoint rejected the probe request"
            + (f" -- {detail}" if detail else "")
        )
    if detail:
        return False, PROBE_BAD_RESPONSE, f"HTTP {code}: {detail}"
    return False, PROBE_BAD_RESPONSE, f"HTTP {code}: the provider rejected the request"


def _is_loopback(url: str) -> bool:
    """True for URLs pointing at this machine (see the --noproxy note below)."""
    try:
        host = urlsplit(url).hostname or ""
    except ValueError:
        return False
    return host in {"127.0.0.1", "localhost", "::1", "[::1]", "0.0.0.0"}


def _curl_bootstrap(spec: ProviderSpec, url: str, timeout: float) -> Tuple[Optional[List[str]], Tuple[bool, ProbeOutcome, str]]:
    """Shared curl plumbing: locate curl and build the fixed argv prefix.

    Returns ``(argv_prefix, error)``; exactly one of the two is ``None``.

    The proxy split lives here and nowhere else, on purpose.  A loopback URL
    must bypass ``http_proxy`` (this machine exports one, and a local Ollama
    answered through it would look like "upstream connect failed"), while cloud
    providers must keep using it.  When the model listing was written with its
    own copy of this argv, the two copies drifted within the same file -- and
    the symptom (local models refuse to list) points nowhere near the proxy.
    """
    exe = shutil.which("curl")
    if not exe:
        return None, (
            False, PROBE_UNAVAILABLE,
            "curl is not available on this machine, so the request could not run",
        )
    args = [
        exe, "-sS", "-o", "-", "-w", "\n__HTTP__%{http_code}",
        "--max-time", str(timeout),
    ]
    if _is_loopback(url):
        args += ["--noproxy", "*"]
    return args, None


def _curl_response(
    args: List[str], url: str, api_key: str, timeout: float,
) -> Tuple[str, str, Optional[Tuple[bool, ProbeOutcome, str]]]:
    """Run curl and split its output into ``(http code, body, error)``.

    ``error`` is ``None`` on a completed HTTP exchange.  The ``__HTTP__000``
    case is handled here because curl emits its write-out template even when
    the connection never completed: reading that as an HTTP result reports a
    DNS failure or a refused connection as "the provider rejected the
    request" -- exactly the diagnosis the user needed, suppressed.
    """
    try:
        proc = subprocess.run(  # noqa: S603 - fixed argv, no shell
            [*args, url], capture_output=True, text=True, timeout=timeout + 5,
        )
    except subprocess.TimeoutExpired:
        return "", "", (
            False, PROBE_TIMEOUT,
            f"no answer within {timeout:.0f} s -- check the address and the network",
        )
    except OSError as exc:
        return "", "", (False, PROBE_UNAVAILABLE, f"could not start curl: {exc}")

    raw = proc.stdout or ""
    if "__HTTP__" not in raw:
        err = _redact((proc.stderr or "").strip(), api_key)
        if proc.returncode in {6, 7} or "resolve" in err.lower() or "Could not resolve" in err:
            return "", "", (
                False, PROBE_NETWORK,
                f"could not reach {url} -- check the host name and your network",
            )
        if "SSL" in err or "certificate" in err.lower() or "TLS" in err:
            return "", "", (False, PROBE_NETWORK, f"TLS handshake failed: {err or 'unknown reason'}")
        if "timed out" in err.lower():
            return "", "", (False, PROBE_TIMEOUT, f"the request timed out: {err}")
        return "", "", (
            False, PROBE_NETWORK,
            err or f"curl exited with {proc.returncode} and no response",
        )

    body_text, _, code = raw.rpartition("__HTTP__")
    code = code.strip()
    if code == "000" or not code:
        err = _redact((proc.stderr or "").strip(), api_key)
        if proc.returncode in {5, 6, 7, 28} or "resolve" in err.lower():
            return "", "", (
                False, PROBE_NETWORK,
                f"could not reach {url} -- check the host name, the address and your network"
                + (f" ({err})" if err else ""),
            )
        if "SSL" in err or "certificate" in err.lower() or "TLS" in err:
            return "", "", (False, PROBE_NETWORK, f"TLS handshake failed: {err or 'unknown reason'}")
        if proc.returncode == 28 or "timed out" in err.lower():
            return "", "", (
                False, PROBE_TIMEOUT,
                f"no answer within {timeout:.0f} s -- check the address and the network",
            )
        return "", "", (
            False, PROBE_NETWORK,
            err or f"the request to {url} did not complete (curl exit {proc.returncode})",
        )
    return code, body_text.strip(), None


def _curl_probe(
    spec: ProviderSpec, base_url: str, api_key: str, timeout: float = 20.0,
) -> Tuple[bool, ProbeOutcome, str]:
    """Probe *spec* at *base_url* with a request as small as the API allows.

    Uses ``curl`` rather than ``urllib`` because a TLS failure, a proxy
    requirement and an HTTP 401 all need to be told apart, and the messages
    that come back are far more useful to a user than a stack trace.  A
    one-token request also keeps the probe from costing anything meaningful.
    """
    url = base_url.rstrip("/") + spec.probe_path
    args, err = _curl_bootstrap(spec, url, timeout)
    if err is not None:
        return err

    headers = _probe_headers(spec, api_key)
    body = _probe_body(spec)
    for key, value in headers.items():
        args += ["-H", f"{key}: {value}"]
    if body is None:
        args += ["-X", "GET"]
    else:
        args += ["-X", "POST", "-d", json.dumps(body)]

    code, body_text, err = _curl_response(args, url, api_key, timeout)
    if err is not None:
        return err
    return _classify_http(code, body_text, spec, api_key)


def _effective_base_url(spec: ProviderSpec) -> str:
    """The base URL the probe must use: the user's override, else the default.

    v0.7.3 audit P1-1: ``set_credential`` has always accepted a ``base_url``
    override, but the probe read ``spec.default_base_url`` unconditionally --
    so anyone pointing the platform at a self-hosted vLLM, a proxy or an
    OpenAI-compatible gateway was told their key was invalid because the probe
    had asked a different host.  The override is stored in ``config/ai.json``
    under ``base_urls``; read it the same way the runtime does.
    """
    stored = ""
    try:
        config = load_config()
        stored = str(getattr(config, "base_urls", {}).get(spec.id, "") or "")
    except Exception:  # noqa: BLE001 - a broken config must not break the probe
        stored = ""
    override = stored.strip() or os.environ.get(_BASE_URL_ENV.get(spec.id, ""), "").strip()
    return override or spec.default_base_url


#: Per-provider environment variable holding a base URL override (optional).
_BASE_URL_ENV: Dict[str, str] = {}


def test_credential(provider_id: str) -> Dict[str, Any]:
    """Try the configured credential against its provider and report what happened.

    Never raises for a failed probe: "your key is wrong" is an answer, not an
    exception, and the GUI has to be able to display it.  Every answer carries
    an ``outcome`` class so the GUI can distinguish a bad key from an
    unreachable host from a model that this account cannot use.
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
            "outcome": PROBE_NO_CREDENTIAL,
            "detail": "no credential is configured for this provider yet",
        }

    base_url = _effective_base_url(spec)
    if not base_url:
        return {
            "provider": spec.id,
            "ok": False,
            "outcome": PROBE_UNSUPPORTED,
            "detail": "this provider has no built-in probe endpoint; it will be used on the next completion",
        }

    # Probe the model that will actually be used.  When the user has picked one
    # from the catalogue, that *is* the deployment: probing the built-in
    # default would report "connected" for a default the runtime never sends,
    # while the model the user chose -- possibly a retired id -- went untested.
    selected = _selected_model(spec)
    if selected and selected != spec.probe_model:
        spec = replace(spec, probe_model=selected)
        used_model = selected
    else:
        used_model = spec.probe_model

    if spec.kind == "local":
        # Local servers do not authenticate; probe the address instead.
        ok, outcome, detail = _curl_probe(spec, base_url, "", timeout=5.0)
        if outcome in {PROBE_NETWORK, PROBE_TIMEOUT}:
            return {
                "provider": spec.id,
                "ok": False,
                "outcome": outcome,
                "detail": f"{detail} -- is the local server running at {base_url}?",
            }
        if ok:
            return {
                "provider": spec.id,
                "ok": True,
                "outcome": PROBE_OK,
                "detail": f"reachable at {base_url}{f' ({detail})' if detail else ''}",
            }
        return {
            "provider": spec.id,
            "ok": False,
            "outcome": PROBE_BAD_RESPONSE,
            "detail": f"{base_url} answered but not as an API server: {detail}",
        }

    ok, outcome, detail = _curl_probe(spec, base_url, secret)
    result = {
        "provider": spec.id, "ok": ok, "outcome": outcome, "detail": detail,
        "model": used_model,
        "model_source": "user" if selected else "default",
    }
    if base_url != spec.default_base_url:
        # Say *where* we looked, or a failure on a custom gateway is undebuggable.
        result["base_url"] = base_url
        result["detail"] = f"{detail} (probed {base_url})"
    return result