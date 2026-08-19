"""Tests del agregador de tools (`app/agent/tools.py`), sin base de datos."""

from app.agent.tools import AGENT_TOOLS, tool_by_name, tool_schemas

EXPECTED_NAMES = {
    "check_availability",
    "create_booking",
    "modify_booking",
    "cancel_booking",
    "answer_faq",
    "escalate",
}
#: Identificadores que nunca deben exponerse al LLM en un input_schema.
FORBIDDEN_IDS = {"restaurant_id", "customer_id", "source_channel", "reservation_id"}


def test_agent_tools_names() -> None:
    assert {tool.name for tool in AGENT_TOOLS} == EXPECTED_NAMES


def test_tool_schemas_shape() -> None:
    schemas = tool_schemas()
    assert len(schemas) == len(AGENT_TOOLS)
    for schema in schemas:
        assert {"name", "description", "input_schema"} <= schema.keys()
        assert schema["input_schema"]["type"] == "object"
        assert "properties" in schema["input_schema"]
        # `required` se omite en schemas con todos los campos opcionales
        # (p. ej. modify_booking); si está presente, debe ser lista.
        assert isinstance(schema["input_schema"].get("required"), list) or (
            "required" not in schema["input_schema"]
        )


def test_no_tenant_ids_in_schemas() -> None:
    for schema in tool_schemas():
        properties = set(schema["input_schema"]["properties"])
        assert properties & FORBIDDEN_IDS == set()


def test_cancel_booking_requires_confirmed() -> None:
    tool = tool_by_name("cancel_booking")
    assert tool is not None
    assert "confirmed" in tool.input_schema["required"]


def test_escalate_schema() -> None:
    tool = tool_by_name("escalate")
    assert tool is not None
    assert tool.input_schema["type"] == "object"
    required = set(tool.input_schema.get("required", []))
    assert {"reason", "summary"} <= required
    assert set(tool.input_schema["properties"]) == {"reason", "summary"}


def test_modify_and_cancel_expose_no_uuids() -> None:
    for name in ("modify_booking", "cancel_booking"):
        tool = tool_by_name(name)
        assert tool is not None
        properties = set(tool.input_schema["properties"])
        assert "requested_table_id" not in properties
        assert "reservation_id" not in properties
