"""Tests de la tool `answer_faq` (base de datos real)."""

from datetime import time as time_type

from app.agent.tool import ToolContext
from app.modules.faqs.tools import answer_faq_tool
from app.modules.reservations.models import SourceChannel


def _ctx(db_session, restaurant_id) -> ToolContext:
    return ToolContext(
        session=db_session,
        restaurant_id=restaurant_id,
        source_channel=SourceChannel.WHATSAPP,
    )


async def test_answer_faq_tool_returns_answer(db_session, restaurant_factory):
    restaurant = await restaurant_factory(
        opening_time=time_type(13, 0), closing_time=time_type(16, 0)
    )
    result = await answer_faq_tool.func(
        _ctx(db_session, restaurant.id), {"question": "¿a qué hora abren?"}
    )
    assert result["known"] is True
    assert result["category"] == "horario"
    assert "13:00" in result["answer"]


async def test_answer_faq_tool_unknown(db_session, restaurant_factory):
    restaurant = await restaurant_factory()
    result = await answer_faq_tool.func(
        _ctx(db_session, restaurant.id), {"question": "¿tienen parking?"}
    )
    assert result["known"] is False
    assert result["category"] == "unknown"


def test_answer_faq_tool_schema_shape() -> None:
    schema = answer_faq_tool.input_schema
    assert schema["type"] == "object"
    assert "question" in schema["properties"]
    assert schema["properties"]["question"].get("minLength") == 1
    assert "question" in schema["required"]
