"""Builder de TwiML (Twilio Voice XML), puro y sin dependencias.

Twilio exige TwiML XML como respuesta al Voice URL. Se construye a mano (sin
SDK) para no añadir dependencias: un árbol de nodos que se renderiza a XML con
escapado correcto de texto y atributos. Se usa para responder `<Say>` (TTS),
`<Gather input="speech">` (STT por turnos) y `<Dial>` (transferencia en vivo).
"""

from dataclasses import dataclass, field
from xml.sax.saxutils import escape


def _attr_escape(value: str) -> str:
    """Escapa un valor de atributo XML (comillas dobles incluidas)."""
    return escape(value, {'"': "&quot;", "'": "&apos;"})


@dataclass(frozen=True)
class Node:
    """Nodo del árbol TwiML: `<tag attrs>hijos|texto</tag>` o autocierre vacío."""

    tag: str
    attrs: dict[str, str] = field(default_factory=dict)
    children: list["Node"] = field(default_factory=list)
    text: str | None = None

    def render(self) -> str:
        attrs = "".join(f' {name}="{_attr_escape(value)}"' for name, value in self.attrs.items())
        if self.text is not None:
            return f"<{self.tag}{attrs}>{escape(self.text)}</{self.tag}>"
        if not self.children:
            return f"<{self.tag}{attrs}/>"
        inner = "".join(child.render() for child in self.children)
        return f"<{self.tag}{attrs}>{inner}</{self.tag}>"


def say(text: str, *, language: str = "es-ES", voice: str | None = None) -> Node:
    """`<Say>`: texto que Twilio lee al cliente (TTS)."""
    attrs = {"language": language}
    if voice:
        attrs["voice"] = voice
    return Node("Say", attrs=attrs, text=text)


def gather(
    inner: Node | list[Node],
    *,
    action: str,
    speech_timeout: int | None = None,
    language: str = "es-ES",
    input_: str = "speech",
) -> Node:
    """`<Gather input="speech">`: recoge el siguiente turno hablado (STT).

    `action` es la URL absoluta (base `VOICE_BASE_URL`) a la que Twilio devuelve
    el turno; `speech_timeout` permite el barge-in (cortar el TTS al hablar).
    """
    attrs = {"action": action, "method": "POST", "input": input_, "language": language}
    if speech_timeout is not None:
        attrs["speechTimeout"] = str(speech_timeout)
    children = inner if isinstance(inner, list) else [inner]
    return Node("Gather", attrs=attrs, children=children)


def hangup() -> Node:
    """`<Hangup/>`: cuelga la llamada."""
    return Node("Hangup")


def dial(number: str, *, timeout: int = 15, action: str | None = None) -> Node:
    """`<Dial>`: transfiere la llamada a `number`; `action` recibe el resultado."""
    attrs = {"timeout": str(timeout)}
    if action:
        attrs["action"] = action
        attrs["method"] = "POST"
    return Node("Dial", attrs=attrs, text=number)


def pause(length: int = 1) -> Node:
    """`<Pause>`: silencio de `length` segundos."""
    return Node("Pause", attrs={"length": str(length)})


def build_response(*children: Node) -> str:
    """Envuelve los nodos en el `<Response>` raíz con la declaration XML."""
    inner = "".join(child.render() for child in children)
    return f'<?xml version="1.0" encoding="UTF-8"?><Response>{inner}</Response>'


def connect_stream(stream_url: str) -> Node:
    """`<Connect><Stream url="..."></Stream></Connect>`: inicia un flujo de medios con Twilio.

    El `stream_url` es la URL pública del WebSocket de FastAPI que manejará
    el flujo de audio bidireccional.
    """
    return Node("Connect", children=[Node("Stream", attrs={"url": stream_url})])
