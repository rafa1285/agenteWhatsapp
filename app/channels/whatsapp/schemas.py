"""Schemas Pydantic del payload entrante del webhook de WhatsApp.

360dialog es un proxy de la Cloud API de Meta: el payload sigue su forma
(`object` → `entry[]` → `changes[]` → `value.messages[]`). Los modelos son
tolerantes a campos ausentes: un payload sin `messages` (p. ej. solo
`statuses`) se parsea sin errores y el handler lo ignora.
"""

from pydantic import BaseModel, ConfigDict, Field


class TextContent(BaseModel):
    """Contenido de un mensaje de tipo texto."""

    body: str | None = None


class InboundMessage(BaseModel):
    """Un mensaje entrante. `from` es el teléfono del remitente (E.164)."""

    model_config = ConfigDict(populate_by_name=True)

    id: str
    from_: str = Field(alias="from")
    type: str = "text"
    text: TextContent | None = None


class Metadata(BaseModel):
    """Datos del número de WhatsApp Business al que llegó el mensaje."""

    phone_number_id: str | None = None
    display_phone_number: str | None = None


class Value(BaseModel):
    """Contenido de un cambio: el número destino y sus mensajes."""

    metadata: Metadata | None = None
    messages: list[InboundMessage] = []

    def first_text_message(self) -> InboundMessage | None:
        """Primer mensaje de texto con cuerpo; `None` si no lo hay."""
        return next((m for m in self.messages if m.type == "text" and m.text and m.text.body), None)


class Change(BaseModel):
    """Un cambio dentro de una entrada del webhook."""

    field: str | None = None
    value: Value | None = None


class Entry(BaseModel):
    """Una entrada del webhook (una cuenta de negocio puede tener varias)."""

    id: str | None = None
    changes: list[Change] = []


class WebhookPayload(BaseModel):
    """Raíz del payload del webhook de WhatsApp (360dialog/Meta)."""

    object: str | None = None
    entry: list[Entry] = []

    def inbound(self) -> tuple[str, InboundMessage] | None:
        """Primer mensaje útil: `(phone_number_id, message)` o `None`.

        Ignora cambios sin mensajes (p. ej. `statuses`) y mensajes sin texto.
        """
        for entry in self.entry:
            for change in entry.changes:
                if change.value is None:
                    continue
                message = change.value.first_text_message()
                metadata = change.value.metadata
                if message is not None and metadata is not None and metadata.phone_number_id:
                    return metadata.phone_number_id, message
        return None
