"""Regression tests for the 0.7.3 credential store and its GUI surface.

The credential path is the one place where a bug is invisible *and* dangerous:
a key that silently fails to save leaves the platform on offline rules while the
GUI says "configured", and a key that leaks is out of reach of any test that
does not look for it.  Four properties are locked here:

1. **A secret never comes back.**  No listing, write or probe response carries
   the value -- only a mask, a length and a source.  This is asserted by
   searching the raw response body for the secret, not by trusting the shape.
2. **Saving actually reaches the runtime.**  The providers read
   ``os.environ``, so a store that only wrote to disk would show "configured"
   while the AI runtime kept falling back to offline.  The environment push is
   the load-bearing part.
3. **Storage location is reported, not implied.**  A user who believes their key
   is in the OS keyring must be told when it is in a plain file.
4. **The GUI has a visible entry point.**  The top bar badge and the icon-rail
   key button are the difference between "there is a feature" and "there is a
   feature you can find"; a static check keeps them from being dropped.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from ai_runtime.credentials import (
    PROVIDERS,
    credential_backend,
    delete_credential,
    list_credentials,
    mask_secret,
    provider_spec,
    set_credential,
)
# Aliased on import: the bare name starts with ``test_`` and pytest would collect
# the *function under test* as a test case and then demand a ``provider_id``
# fixture.  Renaming at the import site keeps the production name honest.
from ai_runtime.credentials import test_credential as probe_credential

REPO = Path(__file__).resolve().parent.parent
FRONTEND = REPO / "frontend" / "src"

#: A value distinctive enough that finding it in a response is unambiguous.
FAKE_SECRET = "sk-test-ZZZUNIQUEZZZ-0123456789"


@pytest.fixture(autouse=True)
def _clean_credentials():
    """Every provider starts and ends without a stored secret.

    The store touches ``os.environ`` and a file under ``config/``; without this
    a test could pass because of a key a previous run left behind.
    """
    before = {
        spec.id: os.environ.get(spec.primary_env)
        for spec in PROVIDERS
        if spec.primary_env
    }
    for spec in PROVIDERS:
        if not spec.primary_env:
            continue
        if os.environ.get(spec.primary_env):
            try:
                delete_credential(spec.id)
            except KeyError:
                pass
    yield
    for provider, value in before.items():
        if value is None:
            os.environ.pop(provider, None)
        else:
            os.environ[provider] = value


# --------------------------------------------------------------------------- #
# 1. A secret never comes back
# --------------------------------------------------------------------------- #
def test_mask_never_reveals_the_whole_secret():
    long_secret = "sk-abcdefghijklmnopqrstuvwxyz0123456789"
    mask = mask_secret(long_secret)
    assert mask != long_secret
    # Only the first and last four characters survive.
    assert mask.startswith("sk-a") and mask.endswith("6789")
    assert mask.count("*") == 6


def test_short_secret_is_masked_completely():
    """Four characters of an eight-character secret is not a safe disclosure."""
    assert set(mask_secret("abcdefgh")) == {"*"}


def test_empty_secret_masks_to_empty():
    assert mask_secret("") == ""


def test_listing_never_contains_the_secret():
    set_credential("deepseek", FAKE_SECRET)
    payload = list_credentials()
    assert FAKE_SECRET not in json.dumps(payload, ensure_ascii=False)


def test_write_response_never_contains_the_secret():
    """The POST body is the riskiest place: it is what the GUI renders next."""
    payload = set_credential("deepseek", FAKE_SECRET)
    assert FAKE_SECRET not in json.dumps(payload, ensure_ascii=False)
    assert payload["masked"] == mask_secret(FAKE_SECRET)


def test_probe_response_never_contains_the_secret():
    result = probe_credential("deepseek")
    assert FAKE_SECRET not in json.dumps(result, ensure_ascii=False)


# --------------------------------------------------------------------------- #
# 2. Saving reaches the runtime
# --------------------------------------------------------------------------- #
def test_set_credential_pushes_into_the_environment():
    """The whole point: a key on disk that the runtime cannot see is a lie."""
    set_credential("deepseek", FAKE_SECRET)
    assert os.environ.get("DEEPSEEK_API_KEY") == FAKE_SECRET


def test_delete_removes_the_environment_push():
    set_credential("deepseek", FAKE_SECRET)
    result = delete_credential("deepseek")
    assert result["removed"] is True
    assert os.environ.get("DEEPSEEK_API_KEY") in (None, "")


def test_a_key_survives_a_restart_when_there_is_no_os_keyring(monkeypatch, tmp_path):
    """No keyring is the desktop case, and it used to keep the key in RAM only.

    The file fallback was wired to the *keyring failure* branch, so with no
    keyring installed the secret was pushed into ``os.environ`` and never
    written anywhere -- while ``stored_in`` still reported ``environment`` and
    the listing advertised a ``config/credentials.json`` that did not exist.
    """
    import ai_runtime.credentials as creds

    monkeypatch.setattr(creds, "_keyring", lambda: None)
    monkeypatch.setattr(creds, "FALLBACK_FILE", tmp_path / "credentials.json")

    result = creds.set_credential("deepseek", FAKE_SECRET)
    assert result["stored_in"] == "file"
    assert creds.FALLBACK_FILE.exists(), "the key was never persisted"
    stored = json.loads(creds.FALLBACK_FILE.read_text(encoding="utf-8"))
    assert stored["deepseek"]["secret"] == FAKE_SECRET

    # A fresh process: same directory, no environment push, still configured.
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    creds._SELF_SET.discard("DEEPSEEK_API_KEY")
    assert creds.credential_backend() == "file"
    status = next(
        item for item in creds.list_credentials()["credentials"]
        if item["provider"] == "deepseek"
    )
    assert status["configured"] is True
    assert FAKE_SECRET not in json.dumps(creds.list_credentials())


def test_delete_keeps_an_environment_variable_the_user_exported(monkeypatch, tmp_path):
    """A variable inherited from the shell is not ours to destroy."""
    import ai_runtime.credentials as creds

    monkeypatch.setattr(creds, "_keyring", lambda: None)
    monkeypatch.setattr(creds, "FALLBACK_FILE", tmp_path / "credentials.json")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-USER-EXPORTED-FROM-SHELL")

    result = creds.delete_credential("openai")
    assert os.environ.get("OPENAI_API_KEY") == "sk-USER-EXPORTED-FROM-SHELL"
    assert "OPENAI_API_KEY" in result["shell_env_preserved"]

    # What we did set, we do clear.
    creds.set_credential("deepseek", FAKE_SECRET)
    creds.delete_credential("deepseek")
    assert os.environ.get("DEEPSEEK_API_KEY") in (None, "")


def test_a_provider_error_that_quotes_the_key_is_redacted(monkeypatch):
    """Providers echo the submitted credential back in 400/402 bodies."""
    import ai_runtime.credentials as creds

    secret = "sk-SUPERSECRET-abc123456789"
    detail = creds._redact(f"bad request: the key {secret} is not on file", secret)
    assert secret not in detail
    assert "sk-S" in detail, "the provider's own prefix should survive so it reads"
    other = creds._redact("rejected sk-SOMEONEELSESKEY-zzz", secret)
    assert "SOMEONEELSESKEY" not in other


def test_delete_of_an_unset_provider_reports_nothing_removed():
    """Not an error -- the GUI must be able to show "there was nothing"."""
    result = delete_credential("deepseek")
    assert result["removed"] is False


def test_saved_key_appears_as_configured_with_its_mask():
    set_credential("deepseek", FAKE_SECRET)
    entry = next(
        item for item in list_credentials()["credentials"] if item["provider"] == "deepseek"
    )
    assert entry["configured"] is True
    assert entry["masked"] == mask_secret(FAKE_SECRET)
    assert entry["length"] == len(FAKE_SECRET)
    assert entry["source"] in {"environment", "keyring", "file"}


# --------------------------------------------------------------------------- #
# 3. Input validation and error surfacing
# --------------------------------------------------------------------------- #
def test_empty_secret_is_rejected():
    with pytest.raises(ValueError):
        set_credential("deepseek", "   ")


def test_secret_with_a_line_break_is_rejected():
    """A newline would corrupt the environment variable for every child process."""
    with pytest.raises(ValueError):
        set_credential("deepseek", "sk-abc\nDEEPSEEK_API_KEY=evil")


def test_unknown_provider_raises_key_error():
    with pytest.raises(KeyError):
        set_credential("not-a-provider", "sk-whatever")
    with pytest.raises(KeyError):
        delete_credential("not-a-provider")
    with pytest.raises(KeyError):
        probe_credential("not-a-provider")


def test_probe_without_a_credential_is_ok_false_not_an_exception():
    """"No key" is an answer the GUI displays, not a 500."""
    result = probe_credential("deepseek")
    assert result["ok"] is False
    assert "no credential" in result["detail"]


def test_probe_of_a_local_provider_defers_to_the_ai_panel():
    """Ollama has no API key to probe; claiming otherwise would be a fake test.

    The endpoint is configured first, otherwise the probe stops at "no
    credential" -- which is the correct answer, just not the one under test.
    """
    set_credential("ollama", "http://127.0.0.1:11434")
    result = probe_credential("ollama")
    assert result["ok"] is False
    assert "local" in result["detail"]


# --------------------------------------------------------------------------- #
# 4. Storage location is reported
# --------------------------------------------------------------------------- #
def test_backend_is_one_of_the_three_known_values():
    assert credential_backend() in {"keyring", "file"}


def test_file_backend_carries_a_bilingual_warning():
    """The warning exists exactly when the key is not in encrypted storage."""
    payload = list_credentials()
    if payload["backend"] == "keyring":
        assert payload["warning"] is None
    else:
        assert payload["warning"] is not None
        assert payload["warning"]["zh"] and payload["warning"]["en"]


def test_every_provider_has_a_bilingual_label_and_notes():
    payload = list_credentials()
    assert len(payload["credentials"]) == len(PROVIDERS)
    for entry in payload["credentials"]:
        assert entry["labels"]["zh"] and entry["labels"]["en"]
        assert entry["notes"]["zh"] or entry["notes"]["en"]


def test_cloud_providers_declare_an_env_var():
    """A hosted provider with no env var could never be configured at all."""
    for spec in PROVIDERS:
        if spec.kind == "cloud":
            assert spec.primary_env, f"{spec.id} is a cloud provider with no env var"


def test_provider_spec_lookup():
    assert provider_spec("openai") is not None
    assert provider_spec("nope") is None


# --------------------------------------------------------------------------- #
# 5. REST surface
# --------------------------------------------------------------------------- #
def test_credential_routes_are_mounted():
    """Openapi, not ``app.routes`` -- the latter hides nested routers."""
    from backend.app import app

    paths = set(app.openapi()["paths"])
    for expected in (
        "/api/credentials",
        "/api/credentials/providers",
        "/api/credentials/{provider}",
        "/api/credentials/{provider}/test",
    ):
        assert expected in paths, f"{expected} is not mounted"


def test_a_rejected_key_is_a_200_with_ok_false():
    """A 401 from the provider is data, not a transport failure."""
    from fastapi.testclient import TestClient

    from backend.app import app

    client = TestClient(app)
    assert client.post(
        "/api/credentials", json={"provider": "deepseek", "secret": FAKE_SECRET}
    ).status_code == 200
    response = client.post("/api/credentials/deepseek/test")
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is False
    assert body["detail"]


def test_unknown_provider_is_a_404_on_the_route():
    from fastapi.testclient import TestClient

    from backend.app import app

    assert TestClient(app).delete("/api/credentials/not-a-provider").status_code == 404


def test_credential_routes_have_explicit_permissions():
    """Reading is harmless; writing a secret is not."""
    from backend.security import ROUTE_RULES

    rules = {
        (rule.method, rule.pattern.pattern): rule.permission
        for rule in ROUTE_RULES
    }
    # The patterns are compiled, so they carry the ``^...$`` anchors.
    assert rules[("POST", "^/api/credentials$")] == "write"
    assert rules[("DELETE", "^/api/credentials/.+$")] == "write"
    assert rules[("POST", "^/api/credentials/.+/test$")] == "execute"


# --------------------------------------------------------------------------- #
# 6. The GUI entry point exists and is findable
# --------------------------------------------------------------------------- #
def test_credentials_router_is_registered_in_the_app():
    from backend.app import app

    assert "/api/credentials" in app.openapi()["paths"]


def test_dock_has_a_key_tab():
    dock = (FRONTEND / "panels" / "Dock.tsx").read_text(encoding="utf-8")
    assert 'id: "apikey"' in dock
    assert "<ApiKeyPanel />" in dock


def test_store_dock_tab_union_includes_apikey():
    store = (FRONTEND / "store.ts").read_text(encoding="utf-8")
    assert '"apikey"' in store


def test_topbar_has_a_key_badge():
    """The user asked for an *obvious* entry point; the top bar is the answer."""
    topbar = (FRONTEND / "components" / "TopBar.tsx").read_text(encoding="utf-8")
    assert "IconKey" in topbar
    assert 'setDockTab("apikey")' in topbar


def test_icon_rail_has_a_key_button():
    rail = (FRONTEND / "components" / "IconRail.tsx").read_text(encoding="utf-8")
    assert "IconKey" in rail
    assert 'openTab("apikey")' in rail


def test_panel_never_renders_a_stored_value():
    """There is no "reveal" button, because the backend never sends one."""
    panel = (FRONTEND / "panels" / "ApiKeyPanel.tsx").read_text(encoding="utf-8")
    assert "item.masked" in panel or "status.masked" in panel or "state.masked" in panel
    # The only secret-shaped state is what the user is currently typing.
    assert 'useState("")' in panel


def test_every_new_i18n_key_exists_in_both_languages():
    """A key present in zh but missing in en renders as the raw key string."""
    i18n = (FRONTEND / "i18n.ts").read_text(encoding="utf-8")
    zh_block = i18n.split('zh: {', 1)[1].split('en: {', 1)[0]
    en_block = i18n.split('en: {', 1)[1]
    import re

    zh_keys = set(re.findall(r"^\s{4}(\w+):", zh_block, flags=re.M))
    en_keys = set(re.findall(r"^\s{4}(\w+):", en_block, flags=re.M))
    missing = zh_keys - en_keys
    assert not missing, f"missing from the English dictionary: {sorted(missing)}"

def test_the_credential_file_is_gitignored():
    """It holds plaintext keys, so ``git add -A`` must never pick it up.

    ``config/ai.json`` was ignored from the start; the credential store was
    not, and a test that wrote a key left the file sitting in the working tree
    one ``git add -A`` away from being committed.
    """
    ignored = subprocess.run(
        ["git", "check-ignore", "-q", "config/credentials.json"],
        cwd=REPO,
        capture_output=True,
    )
    assert ignored.returncode == 0, (
        "config/credentials.json is not gitignored -- it stores plaintext keys"
    )
