import pytest
from pydantic import ValidationError

from app.config import Settings

_BASE_SETTINGS = {
    "app_env": "test",
    "jwt_secret": "test-secret-at-least-32-characters-long",
}


def test_esim_access_package_codes_rejects_old_bare_integer_keys() -> None:
    """The pre-§6.36 format ('5') is still valid JSON, so it parses without
    error into dict[str, str] -- it must be rejected at startup, not left to
    silently miss every EsimAccessProvider lookup at request time."""
    with pytest.raises(ValidationError, match="COUNTRY:GB"):
        Settings(
            **_BASE_SETTINGS,
            esim_access_package_codes={"5": "SA_5GB"},
        )


def test_esim_access_package_codes_rejects_mixed_valid_and_bare_keys() -> None:
    with pytest.raises(ValidationError, match="COUNTRY:GB"):
        Settings(
            **_BASE_SETTINGS,
            esim_access_package_codes={"SA:5": "SA_5GB", "10": "SA_10GB"},
        )


def test_esim_access_package_codes_rejects_no_sa_entry() -> None:
    """Syntactically valid composite keys with zero SA coverage would still
    leave eSIM Access silently unusable for the only real destination."""
    with pytest.raises(ValidationError, match="no 'SA:' entries"):
        Settings(
            **_BASE_SETTINGS,
            esim_access_package_codes={"KE:5": "KE_5GB"},
        )


def test_esim_access_package_codes_accepts_correct_composite_format() -> None:
    settings = Settings(
        **_BASE_SETTINGS,
        esim_access_package_codes={"SA:5": "SA_5GB", "SA:10": "SA_10GB"},
    )
    assert settings.esim_access_package_codes == {
        "SA:5": "SA_5GB",
        "SA:10": "SA_10GB",
    }


def test_esim_access_package_codes_empty_is_allowed() -> None:
    """Unconfigured (dev/test, or a deployment that only uses Monty
    Mobile/1GLOBAL) is not the failure mode this check targets."""
    settings = Settings(**_BASE_SETTINGS)
    assert settings.esim_access_package_codes == {}


def test_esim_access_package_codes_rejects_old_format_from_real_env_var(
    monkeypatch,
) -> None:
    """End-to-end: the exact scenario this fix exists for -- a production
    env var left in the pre-§6.36 format at deploy time."""
    monkeypatch.setenv("ESIM_ACCESS_PACKAGE_CODES", '{"5":"SA_5GB"}')
    with pytest.raises(ValidationError, match="COUNTRY:GB"):
        Settings(**_BASE_SETTINGS)


def test_esim_access_package_codes_accepts_new_format_from_real_env_var(
    monkeypatch,
) -> None:
    monkeypatch.setenv("ESIM_ACCESS_PACKAGE_CODES", '{"SA:5":"SA_5GB"}')
    settings = Settings(**_BASE_SETTINGS)
    assert settings.esim_access_package_codes == {"SA:5": "SA_5GB"}


class TestProductionRejectsDeveloperDefaults:
    """US-42, chunk 26B — a deployment that boots is a deployment somebody trusts.

    Each of these settings is fine in development and an incident in production.
    They fail at startup on purpose: a deployment that refuses to boot is found
    by whoever deployed it, and one that boots and cannot sign anybody in is
    found by customers.
    """

    def _production(self, **overrides: object) -> dict[str, object]:
        base: dict[str, object] = {
            "app_env": "production",
            "jwt_secret": "a-real-production-secret-of-sufficient-length",
            "resend_api_key": "re_live_example",
            "dashboard_base_url": "https://dashboard.damdam.example",
        }
        base.update(overrides)
        return base

    def test_a_valid_production_configuration_starts(self) -> None:
        settings = Settings(**self._production())  # type: ignore[arg-type]

        assert settings.app_env == "production"
        assert settings.browser_origins == ["https://dashboard.damdam.example"]

    def test_the_published_development_jwt_secret_is_refused(self) -> None:
        with pytest.raises(ValidationError) as excinfo:
            Settings(  # type: ignore[arg-type]
                **self._production(
                    jwt_secret="development-only-secret-change-before-deploy"
                )
            )

        assert "JWT_SECRET" in str(excinfo.value)

    def test_identity_mail_with_no_provider_is_refused(self) -> None:
        """`NullDeliveryTransport` discards messages and logs nothing.

        In staging that is correct. In production it is a total authentication
        outage that reports itself as healthy.
        """
        with pytest.raises(ValidationError) as excinfo:
            Settings(**self._production(resend_api_key=""))  # type: ignore[arg-type]

        assert "RESEND_API_KEY" in str(excinfo.value)

    @pytest.mark.parametrize(
        "origin",
        [
            "http://dashboard.damdam.example",
            "https://localhost:3000",
            "http://127.0.0.1:3000",
        ],
    )
    def test_an_insecure_browser_origin_is_refused(self, origin: str) -> None:
        with pytest.raises(ValidationError) as excinfo:
            Settings(**self._production(dashboard_base_url=origin))  # type: ignore[arg-type]

        assert "browser origins" in str(excinfo.value)

    def test_additional_origins_are_parsed_and_deduplicated(self) -> None:
        settings = Settings(  # type: ignore[arg-type]
            **self._production(
                additional_browser_origins=(
                    "https://app.damdam.example/, https://dashboard.damdam.example"
                )
            )
        )

        # Trailing slash normalized, duplicate of the dashboard URL dropped.
        assert settings.browser_origins == [
            "https://dashboard.damdam.example",
            "https://app.damdam.example",
        ]

    def test_development_is_left_alone(self) -> None:
        """The rules are production's. Making them global would stop every
        developer's checkout from starting, and the check would be deleted."""
        settings = Settings(app_env="development")  # type: ignore[arg-type]

        assert settings.jwt_secret.startswith("development-only")
