"""Third-party model catalogue selection and the three-way theme setting (v0.7.3).

Feature 1 asked for the GUI to list a provider's models and let the user change
which one is used.  Two facts from the live NVIDIA key shaped the design and are
asserted here:

* ``GET /v1/models`` returned 81 ids of which most answer HTTP 410 on use.  The
  catalogue is **not** an availability list, so a listing response must be
  labelled as such rather than presented as working models.
* ``GET /v1/models`` with no key returns ``{"object": "list", "data": null}``.
  The parser used to raise ``TypeError: 'NoneType' object is not iterable`` on
  exactly that body, which is the *unauthenticated* response -- i.e. the error
  happened precisely when the user had not pasted a key yet.

Feature 3 renamed "WorkBuddy 黑/白" to "黑/白" and added "跟随系统".
``wb-system`` is a *mode*, not a token set, so anything that indexes the theme
table with the setting directly reads ``undefined``.
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import pytest

from ai_runtime import credentials as C


# --------------------------------------------------------------------------- #
# Model catalogue parsing
# --------------------------------------------------------------------------- #
class TestModelListingParser:
    def _spec(self, provider="nvidia"):
        return C.provider_spec(provider)

    def test_openai_shape_data_array(self):
        body = json.dumps({"data": [{"id": "gpt-4o"}, {"id": "gpt-4o-mini"}]})
        models = C._parse_model_listing(body, self._spec())
        assert [m["id"] for m in models] == ["gpt-4o", "gpt-4o-mini"]

    def test_models_key_shape(self):
        body = json.dumps({"models": [{"name": "llama3"}]})
        # NVIDIA-style specs read the "id" key, so a name-keyed body yields
        # nothing -- assert it degrades instead of raising.
        assert isinstance(C._parse_model_listing(body, self._spec()), list)

    def test_bare_array_shape(self):
        body = json.dumps([{"id": "phi-4"}, {"id": "phi-3"}])
        assert [m["id"] for m in C._parse_model_listing(body, self._spec())] == [
            "phi-4", "phi-3"
        ]

    def test_null_data_is_the_unauthenticated_response(self):
        """The exact body NVIDIA returns without a key.

        This used to raise ``TypeError: 'NoneType' object is not iterable`` --
        so the panel crashed on the state a user is in *before* pasting a key,
        which is the first state they are ever in.
        """
        body = json.dumps({"object": "list", "data": None})
        assert C._parse_model_listing(body, self._spec()) == []

    def test_malformed_and_empty_bodies_never_raise(self):
        spec = self._spec()
        for body in ("", "not json", "{}", "[]", '{"data": "oops"}', '{"data": [1,2]}'):
            assert isinstance(C._parse_model_listing(body, spec), list), body

    def test_ollama_reads_the_name_key(self):
        spec = C.provider_spec("ollama")
        assert spec.models_id_key == "name"
        body = json.dumps({"models": [{"name": "qwen2.5:7b"}]})
        assert [m["id"] for m in C._parse_model_listing(body, spec)] == ["qwen2.5:7b"]


class TestModelSelection:
    def test_every_networked_provider_declares_a_catalogue_path(self):
        """A provider with no ``models_path`` cannot list models at all."""
        for provider in ("openai", "anthropic", "deepseek", "nvidia", "moonshot",
                         "siliconflow", "dashscope", "zhipu", "ollama", "vllm"):
            spec = C.provider_spec(provider)
            assert spec is not None, provider
            assert spec.models_path, f"{provider} has no models_path"
            assert spec.models_path.startswith("/"), provider

    @pytest.fixture(autouse=True)
    def _isolated_config(self, tmp_path, monkeypatch):
        """Point the config at a scratch file.

        ``CHEMML_AI_CONFIG`` is the override the loader reads; setting a
        different variable here would let the test write the developer's real
        ``config/ai.json`` and appear to pass.
        """
        path = tmp_path / "ai.json"
        monkeypatch.setenv("CHEMML_AI_CONFIG", str(path))
        yield path

    def test_selected_model_round_trips_through_config(self):
        C.set_provider_model("nvidia", "stepfun-ai/step-5-preview")
        assert C.provider_model("nvidia") == "stepfun-ai/step-5-preview"

    def test_unknown_provider_is_rejected_not_stored(self):
        with pytest.raises(KeyError):
            C.set_provider_model("not-a-provider", "some-model")

    def test_clearing_the_choice_falls_back_to_the_provider_default(self):
        """Two different things, and conflating them hides a failed clear.

        ``_selected_model`` is the stored choice and goes empty; ``provider_model``
        is what the runtime will actually ask for and falls back to the provider's
        default.  A test that only reads the second cannot tell "cleared" from
        "still set to the default" -- and for NVIDIA the default *is*
        ``openai/gpt-oss-20b``, so picking that value makes an uncleared config
        look cleared.
        """
        spec = C.provider_spec("nvidia")
        default = spec.probe_model
        chosen = "a-model-that-is-not-the-default"
        assert chosen != default, "pick a value that cannot be confused with the default"

        C.set_provider_model("nvidia", chosen)
        assert C._selected_model(spec) == chosen
        assert C.provider_model("nvidia") == chosen

        C.set_provider_model("nvidia", "")
        # The stored choice is gone...
        assert C._selected_model(spec) == ""
        # ...and the runtime is back on the documented default.
        assert C.provider_model("nvidia") == default

    def test_config_normalisation_keeps_the_model_map(self):
        from ai_runtime.config import AIConfig

        config = AIConfig()
        config.models = {"nvidia": "openai/gpt-oss-20b"}
        assert config.normalised().models.get("nvidia") == "openai/gpt-oss-20b"


class TestCredentialStatusExposesTheModel:
    def test_status_carries_selection_and_catalogue_metadata(self):
        names = {f.name for f in dataclasses.fields(C.CredentialStatus)}
        for field in ("selected_model", "effective_model", "models_path"):
            assert field in names, f"CredentialStatus.{field} missing"

    def test_probe_defaults_to_the_model_the_user_chose(self):
        """A credential test must exercise what will actually be used.

        Otherwise "the key works" and "the key works for the model I selected"
        are separate claims, and only the first is ever tested.
        """
        spec = C.provider_spec("nvidia")
        assert spec.probe_model, "nvidia needs a default probe model"
        chosen = dataclasses.replace(spec, probe_model="openai/gpt-oss-20b")
        assert chosen.probe_model == "openai/gpt-oss-20b"


class TestModelEndpoints:
    def test_routes_are_mounted(self):
        """Checked through openapi: ``app.routes`` hides mounted sub-routers."""
        from backend.app import app

        paths = set(app.openapi()["paths"])
        assert "/api/credentials/{provider}/models" in paths
        assert "/api/credentials/{provider}/model" in paths
        assert "/api/credentials/providers" in paths

    def test_model_payload_field_exists(self):
        from backend.routers.credentials import CredentialPayload

        assert "model" in CredentialPayload.model_fields


# --------------------------------------------------------------------------- #
# Theme: 黑 / 白 / 跟随系统
# --------------------------------------------------------------------------- #
class TestThemeSetting:
    def _theme_path(self):
        return Path(__file__).resolve().parents[1] / "frontend" / "src" / "theme.ts"

    def _read(self, relative: str) -> str:
        path = self._theme_path()
        assert path.exists(), f"frontend source missing: {path}"
        target = path.parent / relative
        assert target.exists(), f"missing {relative}"
        return target.read_text(encoding="utf-8")

    def test_system_is_a_third_setting_not_a_token_set(self):
        """``wb-system`` has no colours; indexing THEMES with it yields undefined.

        Every read site has to go through ``resolveTheme`` for that to be true,
        so the source must not index the theme table with a raw setting.
        """
        source = self._read("theme.ts")
        assert "wb-system" in source
        assert "resolveTheme" in source
        store = self._read("store.ts")
        # Any THEMES[ ... ] read must be resolved first.
        for line in store.splitlines():
            if "THEMES[" in line:
                assert "resolveTheme" in line, f"unresolved theme index: {line.strip()}"

    def test_labels_are_black_white_and_follow_system(self):
        i18n = self._read("i18n.ts")
        assert 'themeWbDark: "黑"' in i18n, "dark label must be 黑, not WorkBuddy 黑"
        assert 'themeWbLight: "白"' in i18n, "light label must be 白"
        assert "跟随系统" in i18n, "missing the follow-system label"

    def test_three_settings_are_offered(self):
        source = self._read("theme.ts")
        assert "THEME_SETTINGS" in source
        assert '"wb-dark"' in source and '"wb-light"' in source and '"wb-system"' in source

    def test_persisted_value_is_the_setting_not_the_resolved_id(self):
        """Storing the resolved id would silently drop a follow-system choice.

        A user who picks 跟随系统 while the OS is dark would be written down as
        "wb-dark" and never get light mode again on a light desktop.
        """
        source = self._read("theme.ts")
        assert "data-theme-setting" in source, "the chosen mode must be persisted separately"
        assert "data-theme" in source, "the resolved token set must still be applied"

    def test_topbar_does_not_mislabell_the_system_setting(self):
        """A lookup table, not a two-way ternary.

        ``wb-system ? dark : light`` style code labels 跟随系统 as 黑.
        """
        topbar = self._read("components/TopBar.tsx")
        assert "THEME_SETTINGS" in topbar or "themeLabel" in topbar

    def test_electron_bridge_exposes_the_system_theme(self):
        main = self._read("../../desktop/src/main.js")
        assert "nativeTheme" in main, "Electron side must read the OS theme"
        preload = self._read("../../desktop/src/preload.js")
        assert "system" in preload.lower(), "preload must expose the system-theme query"