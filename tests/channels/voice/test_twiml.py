"""Tests del builder de TwiML (XML canónico, sin dependencias).

El render es canónico (atributos en orden estable, texto escapado), pero los
tests comparan árboles (`assert_twiml`) para no depender de whitespace entre
elementos ni del orden de los atributos.
"""

import xml.etree.ElementTree as ET

from app.channels.voice.twiml import build_response, dial, gather, hangup, pause, say

ACTION = "https://ejemplo.com/api/voice/call"


def _same(a: ET.Element, b: ET.Element) -> bool:
    """¿Son equivalentes dos nodos XML (tag, atributos, texto, hijos en orden)?"""
    if a.tag != b.tag or dict(a.attrib) != dict(b.attrib):
        return False
    if (a.text or "").strip() != (b.text or "").strip():
        return False
    if len(a) != len(b):
        return False
    return all(_same(x, y) for x, y in zip(a, b, strict=True))


def assert_twiml(actual: str, expected: str) -> None:
    """Compara dos documentos TwiML por árbol, ignorando formato (whitespace,
    orden de atributos, comillas). La declaration XML no forma parte del árbol.
    """
    assert _same(ET.fromstring(actual), ET.fromstring(expected))


def test_assert_twiml_ignores_formatting_differences() -> None:
    # Mismo árbol con whitespace y orden de atributos distintos.
    assert_twiml(
        '<Response><Say language="es-ES" voice="Polly.Joanna">Hola</Say>  <Hangup/></Response>',
        '<?xml version="1.0"?><Response>\n  <Say voice="Polly.Joanna" language="es-ES"> '
        "Hola </Say>\n  <Hangup/>\n</Response>",
    )


def test_say_escapes_special_characters() -> None:
    assert_twiml(
        say('a < b & c > d "e"').render(),
        '<Say language="es-ES">a &lt; b &amp; c &gt; d "e"</Say>',
    )


def test_say_accepts_language_and_voice() -> None:
    node = say("Hola", language="en-US", voice="Polly.Joanna")
    assert_twiml(
        node.render(),
        '<Say voice="Polly.Joanna" language="en-US">Hola</Say>',
    )


def test_gather_nests_and_emits_attributes() -> None:
    node = gather(say("Hable"), action=ACTION, speech_timeout=4)
    assert_twiml(
        node.render(),
        '<Gather action="https://ejemplo.com/api/voice/call" method="POST" '
        'input="speech" language="es-ES" speechTimeout="4">'
        '<Say language="es-ES">Hable</Say></Gather>',
    )


def test_hangup_self_closes() -> None:
    assert hangup().render() == "<Hangup/>"


def test_dial_emits_timeout_and_action() -> None:
    node = dial("+34910000000", timeout=15, action=ACTION)
    assert_twiml(
        node.render(),
        '<Dial action="https://ejemplo.com/api/voice/call" method="POST" timeout="15">'
        "+34910000000</Dial>",
    )


def test_pause_with_length() -> None:
    assert pause(2).render() == '<Pause length="2"/>'


def test_build_response_wraps_with_declaration() -> None:
    twiml = build_response(say("Hola"), hangup())
    assert twiml.startswith('<?xml version="1.0" encoding="UTF-8"?><Response>')
    assert twiml.endswith("</Response>")
    assert_twiml(twiml, '<Response><Say language="es-ES">Hola</Say><Hangup/></Response>')
