"""Tests del servicio de FAQs (base de datos real)."""

import uuid
from datetime import time as time_type

from app.modules.faqs.service import answer_faq


async def test_answer_horario(db_session, restaurant_factory):
    restaurant = await restaurant_factory(
        opening_time=time_type(13, 0), closing_time=time_type(16, 0)
    )
    answer = await answer_faq(
        db_session, restaurant_id=restaurant.id, question="¿a qué hora abren?"
    )
    assert answer.known is True
    assert answer.category == "horario"
    assert "13:00" in answer.answer
    assert "16:00" in answer.answer


async def test_answer_telefono(db_session, restaurant_factory):
    restaurant = await restaurant_factory(public_phone="+34910000000")
    answer = await answer_faq(db_session, restaurant_id=restaurant.id, question="¿tenéis teléfono?")
    assert answer.known is True
    assert answer.category == "telefono"
    assert "+34910000000" in answer.answer


async def test_answer_idiomas(db_session, restaurant_factory):
    restaurant = await restaurant_factory(supported_languages=["es", "en"])
    answer = await answer_faq(db_session, restaurant_id=restaurant.id, question="¿hablan inglés?")
    assert answer.known is True
    assert answer.category == "idiomas"
    assert "es" in answer.answer
    assert "en" in answer.answer


async def test_answer_grupos(db_session, restaurant_factory):
    restaurant = await restaurant_factory(large_group_threshold=8)
    answer = await answer_faq(
        db_session, restaurant_id=restaurant.id, question="¿reservo para un grupo?"
    )
    assert answer.known is True
    assert answer.category == "grupos"
    assert "8" in answer.answer


async def test_answer_unknown_category(db_session, restaurant_factory):
    restaurant = await restaurant_factory()
    answer = await answer_faq(db_session, restaurant_id=restaurant.id, question="¿tienen parking?")
    assert answer.known is False
    assert answer.category == "unknown"


async def test_restaurant_not_found(db_session):
    answer = await answer_faq(db_session, restaurant_id=uuid.uuid4(), question="¿a qué hora abren?")
    assert answer.known is False
    assert answer.category == "unknown"
