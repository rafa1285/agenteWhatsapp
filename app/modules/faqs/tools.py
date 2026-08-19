"""Tool de FAQs (delega en su `service.py`)."""

from typing import Any

from app.agent.tool import Tool, ToolContext
from app.modules.faqs.schemas import FaqQueryInput
from app.modules.faqs.service import answer_faq


async def answer_faq_tool_fn(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    """Responde una FAQ con datos reales; `known=false` indica derivar a humano."""
    payload = FaqQueryInput.model_validate(args)
    answer = await answer_faq(
        ctx.session, restaurant_id=ctx.restaurant_id, question=payload.question
    )
    return {"answer": answer.answer, "known": answer.known, "category": answer.category}


answer_faq_tool = Tool(
    name="answer_faq",
    description=(
        "Responde preguntas frecuentes sobre el restaurante (horario, telefono, "
        "idiomas, grupos). Si devuelve known=false no se sabe la respuesta: deriva "
        "a un humano. Nunca inventa datos."
    ),
    input_schema=FaqQueryInput.model_json_schema(),
    func=answer_faq_tool_fn,
)
