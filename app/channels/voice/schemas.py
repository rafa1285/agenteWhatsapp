"""Parsing del form-encoded que envía Twilio al webhook de voz.

Un solo schema sirve para `/call` y `/status`: Twilio manda los mismos campos
base (`CallSid`, `From`, `To`, `CallStatus`) más los específicos de cada
escenario (`SpeechResult`/`Confidence` en el Gather, `DialCallStatus` en el
retorno del `<Dial>`, `RecordingUrl`/`CallDuration`/`UncompletedCall` en el
status callback). Los campos llegan en PascalCase: se mapean a atributos
snake_case con `alias`, y el modelo es tolerante (`extra="ignore"`).
"""

from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class TwilioCallRequest(BaseModel):
    """Payload form-encoded de Twilio (campo presente = contexto de la llamada)."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    call_sid: str | None = Field(default=None, alias="CallSid")
    from_: str | None = Field(default=None, alias="From")
    to: str | None = Field(default=None, alias="To")
    call_status: str | None = Field(default=None, alias="CallStatus")
    speech_result: str | None = Field(default=None, alias="SpeechResult")
    confidence_raw: str | None = Field(default=None, alias="Confidence")
    digits: str | None = Field(default=None, alias="Digits")
    recording_url: str | None = Field(default=None, alias="RecordingUrl")
    call_duration: str | None = Field(default=None, alias="CallDuration")
    uncompleted_call: str | None = Field(default=None, alias="UncompletedCall")
    dial_call_status: str | None = Field(default=None, alias="DialCallStatus")

    @classmethod
    def from_form(cls, form: Mapping[str, Any]) -> "TwilioCallRequest":
        """Construye la petición desde el body form-encoded (dict str -> str)."""
        return cls.model_validate(dict(form))

    @property
    def speech_text(self) -> str | None:
        """Transcript del turno, recortado; vacío/ausente -> `None`."""
        text = (self.speech_result or "").strip()
        return text or None

    @property
    def confidence(self) -> float | None:
        """Confianza del STT (0-1) como float; ausente/inválido -> `None`."""
        if self.confidence_raw is None:
            return None
        try:
            return float(self.confidence_raw)
        except ValueError:
            return None

    @property
    def uncompleted(self) -> bool:
        """¿Twilio marcó la llamada no completada (`UncompletedCall=true`)?"""
        return (self.uncompleted_call or "").strip().lower() == "true"

    @property
    def call_duration_seconds(self) -> int | None:
        """Duración de la llamada en segundos; ausente/inválido -> `None`."""
        if self.call_duration is None:
            return None
        try:
            return int(self.call_duration)
        except ValueError:
            return None
