"""Tests del servicio de la capa core (resolución de tenant)."""

from app.core.service import (
    get_restaurant_by_voice_number,
    get_restaurant_by_whatsapp_number,
    mask_phone,
)


async def test_finds_active_restaurant_by_whatsapp_number(db_session, restaurant_factory):
    restaurant = await restaurant_factory(whatsapp_number_id="wa-12345", active=True)
    found = await get_restaurant_by_whatsapp_number(db_session, whatsapp_number_id="wa-12345")
    assert found is not None
    assert found.id == restaurant.id


async def test_unknown_number_returns_none(db_session, restaurant_factory):
    await restaurant_factory(whatsapp_number_id="wa-12345", active=True)
    assert (
        await get_restaurant_by_whatsapp_number(db_session, whatsapp_number_id="wa-missing") is None
    )


async def test_inactive_restaurant_excluded(db_session, restaurant_factory):
    await restaurant_factory(whatsapp_number_id="wa-12345", active=False)
    assert (
        await get_restaurant_by_whatsapp_number(db_session, whatsapp_number_id="wa-12345") is None
    )


async def test_multi_tenant_lookup_scoped_to_number(db_session, restaurant_factory):
    first = await restaurant_factory(whatsapp_number_id="wa-111", active=True)
    await restaurant_factory(whatsapp_number_id="wa-222", active=True)
    found = await get_restaurant_by_whatsapp_number(db_session, whatsapp_number_id="wa-111")
    assert found.id == first.id


async def test_finds_active_restaurant_by_voice_number(db_session, restaurant_factory):
    restaurant = await restaurant_factory(voice_number="+34910000001", active=True)
    found = await get_restaurant_by_voice_number(db_session, voice_number="+34910000001")
    assert found is not None
    assert found.id == restaurant.id


async def test_unknown_voice_number_returns_none(db_session, restaurant_factory):
    await restaurant_factory(voice_number="+34910000001", active=True)
    assert await get_restaurant_by_voice_number(db_session, voice_number="+34910000009") is None


async def test_inactive_voice_restaurant_excluded(db_session, restaurant_factory):
    await restaurant_factory(voice_number="+34910000001", active=False)
    assert await get_restaurant_by_voice_number(db_session, voice_number="+34910000001") is None


def test_mask_phone() -> None:
    assert mask_phone("+34611222333") == "***333"
    assert mask_phone("34611222333") == "***333"
    assert mask_phone("12") == "***"
