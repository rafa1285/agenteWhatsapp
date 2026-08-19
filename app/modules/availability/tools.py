"""Tools del módulo de disponibilidad (delegan en su `service.py`)."""

from typing import Any

from app.agent.tool import Tool, ToolContext
from app.modules.availability.schemas import CheckAvailabilityInput
from app.modules.availability.service import check_availability


async def check_availability_tool_fn(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    """Consulta disponibilidad. Nunca lanza: `check_availability` siempre responde."""
    payload = CheckAvailabilityInput.model_validate(args)
    result = await check_availability(
        ctx.session,
        restaurant_id=ctx.restaurant_id,
        date=payload.date,
        time=payload.time,
        party_size=payload.party_size,
        preferred_zone=payload.preferred_zone,
    )
    return result.model_dump(mode="json")


check_availability_tool = Tool(
    name="check_availability",
    description=(
        "Consulta si el restaurante puede atender a N comensales en una fecha y hora; "
        "devuelve el motivo (available/closed/outside_service_hours/aforo_exceeded/"
        "no_table_for_party), el turno activo y las mesas libres. Nunca inventar "
        "disponibilidad: usa siempre esta tool."
    ),
    input_schema=CheckAvailabilityInput.model_json_schema(),
    func=check_availability_tool_fn,
)
