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
