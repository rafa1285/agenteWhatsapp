"""Tests del parsing del form-encoded que Twilio envía al webhook de voz."""

from app.channels.voice.schemas import TwilioCallRequest


def _form(**overrides: str) -> dict[str, str]:
    """Form realista de Twilio: campos base de toda llamada + extras."""
    fields = {
        "CallSid": "CA123456",
        "From": "+34611111111",
        "To": "+34910000001",
        "CallStatus": "in-progress",
    }
    fields.update(overrides)
    return fields


def test_parses_realistic_twilio_form() -> None:
    request = TwilioCallRequest.from_form(
        _form(SpeechResult="Quiero reservar", Confidence="0.87", UncompletedCall="true")
    )
    assert request.call_sid == "CA123456"
    assert request.from_ == "+34611111111"
    assert request.to == "+34910000001"
    assert request.call_status == "in-progress"
    assert request.speech_text == "Quiero reservar"
    assert request.confidence == 0.87
    assert request.uncompleted is True


def test_missing_fields_default_to_none() -> None:
    request = TwilioCallRequest.from_form(_form())
    assert request.call_sid == "CA123456"
    assert request.speech_result is None
    assert request.speech_text is None
    assert request.confidence_raw is None
    assert request.confidence is None
    assert request.digits is None
    assert request.recording_url is None
    assert request.call_duration is None
    assert request.call_duration_seconds is None
    assert request.dial_call_status is None
    assert request.uncompleted is False


def test_extra_fields_are_ignored() -> None:
    request = TwilioCallRequest.from_form(_form(SpeechResult="Hola", CallDuration="45", Foo="bar"))
    assert request.call_duration_seconds == 45
    assert request.speech_text == "Hola"


def test_speech_text_trims_and_blank_to_none() -> None:
    assert TwilioCallRequest.from_form(_form(SpeechResult="  hola  ")).speech_text == "hola"
    assert TwilioCallRequest.from_form(_form(SpeechResult="   ")).speech_text is None
    assert TwilioCallRequest.from_form(_form(SpeechResult="")).speech_text is None


def test_confidence_invalid_or_missing_is_none() -> None:
    assert TwilioCallRequest.from_form(_form(Confidence="xx")).confidence is None
    assert TwilioCallRequest.from_form(_form(Confidence="0.5")).confidence == 0.5


def test_uncompleted_flags() -> None:
    assert TwilioCallRequest.from_form(_form(UncompletedCall="true")).uncompleted is True
    assert TwilioCallRequest.from_form(_form(UncompletedCall="True")).uncompleted is True
    assert TwilioCallRequest.from_form(_form(UncompletedCall="false")).uncompleted is False
