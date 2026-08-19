#!/usr/bin/env python
"""Debug customer creation and persistence."""

import asyncio
import uuid

from app.db.session import async_session_factory
from app.modules.customers.models import Customer
from app.modules.customers.service import find_or_create_customer_by_phone
from sqlalchemy import select, text

RESTAURANT_ID = uuid.UUID('2f177e23-7ace-4827-ac12-9f3a784d6531')

async def test():
    async with async_session_factory() as session:
        print('=== Creating customer via service ===')
        customer = await find_or_create_customer_by_phone(
            session=session,
            restaurant_id=RESTAURANT_ID,
            phone='+34633333333'
        )
        print(f'Customer created: {customer.id}')
        print(f'Customer restaurant_id: {customer.restaurant_id}')
        await session.flush()
        print('After flush, customer in session')
        await session.commit()
        print('After commit')

        # Verify it's actually in DB
        print()
        print('=== Querying customer after commit ===')
        result = await session.execute(
            select(Customer).where(Customer.id == customer.id)
        )
        fetched = result.scalar_one_or_none()
        print(f'Fetched after commit: {fetched}')

        # Direct SQL check
        print()
        print('=== Direct SQL check ===')
        result = await session.execute(
            text("SELECT id, restaurant_id, phone FROM customers WHERE id = :cid"),
            {"cid": str(customer.id)}
        )
        row = result.fetchone()
        print(f'Direct SQL result: {row}')

asyncio.run(test())
