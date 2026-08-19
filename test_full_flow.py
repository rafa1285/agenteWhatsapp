#!/usr/bin/env python
"""Test full customer + reservation flow with direct DB verification."""

import asyncio
import datetime
import sys

import httpx
import jwt

# Add the app to path
sys.path.insert(0, 'C:/laragon/www/agenteWhatsapp')

import uuid

from app.db.session import async_session_factory
from sqlalchemy import select

RESTAURANT_ID = uuid.UUID('2f177e23-7ace-4827-ac12-9f3a784d6531')

async def test():
    print("=== Phase 1: Test direct service call ===")
    async with async_session_factory() as session:
        from datetime import date as date_type
        from datetime import time as time_type

        from app.modules.customers.models import Customer
        from app.modules.customers.service import find_or_create_customer_by_phone
        from app.modules.reservations.models import SourceChannel
        from app.modules.reservations.service import create_reservation

        # Create customer via service
        phone = '+34611111111'
        customer = await find_or_create_customer_by_phone(
            session=session,
            restaurant_id=RESTAURANT_ID,
            phone=phone
        )
        customer.name = 'Test Direct Service'
        await session.flush()
        await session.commit()
        customer_id = customer.id
        print(f"Created customer: {customer_id}")

    # Verify in fresh session
    async with async_session_factory() as session2:
        result = await session2.execute(
            select(Customer).where(Customer.id == customer_id)
        )
        fetched = result.scalar_one_or_none()
        print(f"Fresh session fetch: {fetched is not None}, phone={fetched.phone if fetched else 'N/A'}")

    print("\n=== Phase 2: Test reservation creation via service ===")
    async with async_session_factory() as session:
        from datetime import date as date_type
        from datetime import time as time_type

        from app.modules.reservations.models import SourceChannel
        from app.modules.reservations.service import create_reservation

        result = await create_reservation(
            session=session,
            restaurant_id=RESTAURANT_ID,
            customer_id=customer_id,
            date=date_type(2026, 8, 23),
            time=time_type(14, 0),
            party_size=2,
            source_channel=SourceChannel.WEB,
            requested_table_id=uuid.UUID('cf07ad9b-1852-482a-8754-6be815907268')
        )
        await session.commit()
        reservation_id = result.reservation.id
        print(f"Created reservation: {reservation_id}")

    # Verify in fresh session
    async with async_session_factory() as session2:
        from app.modules.reservations.models import Reservation
        result = await session2.execute(
            select(Reservation).where(Reservation.id == reservation_id)
        )
        fetched = result.scalar_one_or_none()
        print(f"Fresh session fetch reservation: {fetched is not None}, status={fetched.status if fetched else 'N/A'}")

    print("\n=== Phase 3: Test via API ===")
    payload = {
        'iss': 'reception-panel',
        'aud': 'reception-api',
        'iat': int(datetime.datetime.now(datetime.UTC).timestamp()),
        'exp': int((datetime.datetime.now(datetime.UTC) + datetime.timedelta(hours=1)).timestamp()),
        'restaurant_id': '2f177e23-7ace-4827-ac12-9f3a784d6531',
    }
    token = jwt.encode(payload, open(r'C:/laragon/www/agenteWhatsappPanel/storage/keys/private.pem').read(), algorithm='RS256')
    headers = {'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'}

    # Create customer via API
    phone = '+34612345678'
    response = httpx.post(
        f'http://127.0.0.1:8001/api/v1/customers?phone={phone}&name=APICustomer',
        headers=headers, timeout=10
    )
    print(f"API create customer status: {response.status_code}")
    if response.status_code == 201:
        api_customer_id = response.json().get('id')
        print(f"API customer ID: {api_customer_id}")

    # Verify in fresh session
    await asyncio.sleep(0.5)
    async with async_session_factory() as session2:
        result = await session2.execute(
            select(Customer).where(Customer.id == api_customer_id)
        )
        fetched = result.scalar_one_or_none()
        print(f"Fresh session fetch after API: {fetched is not None}, phone={fetched.phone if fetched else 'N/A'}")

asyncio.run(test())
