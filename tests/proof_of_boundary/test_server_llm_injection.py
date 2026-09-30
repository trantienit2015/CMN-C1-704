# The standalone entry point must import and construct whether or not the Azure OpenAI
# secrets are provisioned, and its caller-auth boundary must never let the external bearer
# token reach INTERNAL. server.py injects LazyAzureOpenAILLM into config["llm"] only when
# client_available() and all three AZURE_OPENAI_* secrets resolve (src/services/azure_llm.py);
# the construct-with-key / missing-value / no-leaked-value properties of that adapter are
# covered at the unit level in tests/unit/test_azure_llm_adapter.py, so this PB scope proves
# only that the entry point itself boots either way (the blueprint's Anthropic-specific
# TestServerConstructsLlmWithKey does not apply — this template has no ANTHROPIC_API_KEY path).

import importlib


class TestServerBootsWithoutAzureSecrets:
    def test_server_imports_and_app_constructs_with_no_secrets_bound(self, monkeypatch):
        for key in ("AZURE_OPENAI_API_KEY", "AZURE_OPENAI_ENDPOINT", "AZURE_OPENAI_DEPLOYMENT"):
            monkeypatch.delenv(key, raising=False)

        import src.api.server as server

        importlib.reload(server)

        assert server.app is not None
        assert server.agent is not None


class TestStandaloneTrustPromotion:
    def test_external_bearer_never_promotes_to_internal(self):
        import src.api.server as server
        from framework.schemas.trust_level import TrustLevel

        assert server._resolve_standalone_trust(
            TrustLevel.ANONYMOUS, "Bearer external", "external", "runner"
        ) is TrustLevel.VERIFIED_EXTERNAL

    def test_runner_bearer_promotes_to_internal(self):
        import src.api.server as server
        from framework.schemas.trust_level import TrustLevel

        assert server._resolve_standalone_trust(
            TrustLevel.ANONYMOUS, "Bearer runner", "external", "runner"
        ) is TrustLevel.INTERNAL

    def test_wrong_or_missing_bearer_is_rejected_when_auth_is_enabled(self):
        import pytest
        import src.api.server as server
        from fastapi import HTTPException
        from framework.schemas.trust_level import TrustLevel

        for authorization in ("", "Bearer wrong"):
            with pytest.raises(HTTPException) as exc:
                server._resolve_standalone_trust(TrustLevel.ANONYMOUS, authorization, "external", "runner")
            assert exc.value.status_code == 401
