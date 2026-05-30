"""Settings sanity for fields added by the OAuth + Resend feature."""

from __future__ import annotations

import pytest

from irma_api.config import Settings


@pytest.fixture(autouse=True)
def _clear_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in (
        "IRMA_USER_EMAIL",
        "RESEND_API_KEY",
        "RESEND_FROM_EMAIL",
    ):
        monkeypatch.delenv(key, raising=False)


def test_user_email_defaults_to_none() -> None:
    settings = Settings(_env_file=None)
    assert settings.irma_user_email is None


def test_user_email_reads_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("IRMA_USER_EMAIL", "amit@example.com")
    settings = Settings(_env_file=None)
    assert settings.irma_user_email == "amit@example.com"


def test_resend_api_key_defaults_to_none() -> None:
    settings = Settings(_env_file=None)
    assert settings.resend_api_key is None


def test_resend_api_key_reads_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RESEND_API_KEY", "re_xxx")
    settings = Settings(_env_file=None)
    assert settings.resend_api_key is not None
    assert settings.resend_api_key.get_secret_value() == "re_xxx"


def test_resend_from_email_default() -> None:
    settings = Settings(_env_file=None)
    assert settings.resend_from_email == "onboarding@resend.dev"


def test_resend_from_email_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RESEND_FROM_EMAIL", "irma@example.com")
    settings = Settings(_env_file=None)
    assert settings.resend_from_email == "irma@example.com"


def test_secret_value_or_none_returns_none_for_blank() -> None:
    from pydantic import SecretStr

    from irma_api.config import secret_value_or_none

    assert secret_value_or_none(None) is None
    assert secret_value_or_none(SecretStr("")) is None
    assert secret_value_or_none(SecretStr("real-value")) == "real-value"
