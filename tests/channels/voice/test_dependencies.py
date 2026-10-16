"""Tests de validación de firma Twilio (`X-Twilio-Signature`)."""

from types import SimpleNamespace

from app.channels.voice.dependencies import validate_twilio_signature
from app.core.settings import settings


class _FakeRequest:
    def __init__(self, *, path: str = "/api/voice/call", headers: dict[str, str] | None = None):
        self.url = SimpleNamespace(path=path)
        self.headers = headers or {}


def _sign(*, token: str, url: str, form: dict[str, str]) -> str:
    import base64
    import hashlib
    import hmac

    payload = "".join(f"{key}{value}" for key, value in sorted(form.items()))
    digest = hmac.new(token.encode("utf-8"), f"{url}{payload}".encode(), hashlib.sha1).digest()
    return base64.b64encode(digest).decode("ascii")


def test_validation_skipped_in_testing_mode(monkeypatch):
    monkeypatch.setattr(settings, "TESTING", True)
    monkeypatch.setattr(settings, "TWILIO_VALIDATE_SIGNATURE", True)
    monkeypatch.setattr(settings, "TWILIO_AUTH_TOKEN", "secret")

    assert validate_twilio_signature(_FakeRequest(), form_data={"CallSid": "CA1"}) is True


def test_validation_skipped_when_disabled(monkeypatch):
    monkeypatch.setattr(settings, "TESTING", False)
    monkeypatch.setattr(settings, "TWILIO_VALIDATE_SIGNATURE", False)
    monkeypatch.setattr(settings, "TWILIO_AUTH_TOKEN", "secret")

    assert validate_twilio_signature(_FakeRequest(), form_data={"CallSid": "CA1"}) is True


def test_validation_skipped_without_auth_token(monkeypatch):
    monkeypatch.setattr(settings, "TESTING", False)
    monkeypatch.setattr(settings, "TWILIO_VALIDATE_SIGNATURE", True)
    monkeypatch.setattr(settings, "TWILIO_AUTH_TOKEN", None)

    assert validate_twilio_signature(_FakeRequest(), form_data={"CallSid": "CA1"}) is True


def test_validation_skipped_with_blank_auth_token(monkeypatch):
    monkeypatch.setattr(settings, "TESTING", False)
    monkeypatch.setattr(settings, "TWILIO_VALIDATE_SIGNATURE", True)
    monkeypatch.setattr(settings, "TWILIO_AUTH_TOKEN", "   ")

    assert validate_twilio_signature(_FakeRequest(), form_data={"CallSid": "CA1"}) is True


def test_missing_signature_is_rejected(monkeypatch):
    monkeypatch.setattr(settings, "TESTING", False)
    monkeypatch.setattr(settings, "TWILIO_VALIDATE_SIGNATURE", True)
    monkeypatch.setattr(settings, "TWILIO_AUTH_TOKEN", "secret")

    assert validate_twilio_signature(_FakeRequest(), form_data={"CallSid": "CA1"}) is False


def test_invalid_signature_is_rejected(monkeypatch):
    monkeypatch.setattr(settings, "TESTING", False)
    monkeypatch.setattr(settings, "TWILIO_VALIDATE_SIGNATURE", True)
    monkeypatch.setattr(settings, "TWILIO_AUTH_TOKEN", "secret")
    monkeypatch.setattr(settings, "VOICE_BASE_URL", "https://example.com")

    request = _FakeRequest(headers={"X-Twilio-Signature": "no-es-valida"})
    assert validate_twilio_signature(request, form_data={"CallSid": "CA1"}) is False


def test_valid_signature_is_accepted(monkeypatch):
    monkeypatch.setattr(settings, "TESTING", False)
    monkeypatch.setattr(settings, "TWILIO_VALIDATE_SIGNATURE", True)
    monkeypatch.setattr(settings, "TWILIO_AUTH_TOKEN", "secret")
    monkeypatch.setattr(settings, "VOICE_BASE_URL", "https://example.com")

    form = {"CallSid": "CA1", "From": "+34611111111", "To": "+34910000001"}
    signature = _sign(token="secret", url="https://example.com/api/voice/call", form=form)
    request = _FakeRequest(headers={"X-Twilio-Signature": signature})

    assert validate_twilio_signature(request, form_data=form) is True
