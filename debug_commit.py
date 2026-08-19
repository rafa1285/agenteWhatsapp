#!/usr/bin/env python
"""Debug customer creation - trace commits and rollbacks."""
import asyncio
import logging
import sys

logging.basicConfig(level=logging.DEBUG, stream=sys.stdout)
# Suppress noisy loggers
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

# Monkey-patch session to trace commits
import sqlalchemy.ext.asyncio.session as sess_mod

_orig_commit = sess_mod.AsyncSession.commit
async def _traced_commit(self):
    print(f"  >> SESSION COMMIT called (session id={id(self)})", flush=True)
    import traceback; traceback.print_stack(limit=5)
    result = await _orig_commit(self)
    print(f"  >> SESSION COMMIT returned {result}", flush=True)
    return result
sess_mod.AsyncSession.commit = _traced_commit

_orig_flush = sess_mod.AsyncSession.flush
async def _traced_flush(self, *args, **kwargs):
    print(f"  >> SESSION FLUSH called (session id={id(self)})", flush=True)
    result = await _orig_flush(self, *args, **kwargs)
    print(f"  >> SESSION FLUSH returned {result}", flush=True)
    return result
sess_mod.AsyncSession.flush = _traced_flush

_orig_rollback = sess_mod.AsyncSession.rollback
async def _traced_rollback(self):
    print(f"  >> SESSION ROLLBACK called (session id={id(self)})", flush=True)
    import traceback; traceback.print_stack(limit=5)
    result = await _orig_rollback(self)
    print(f"  >> SESSION ROLLBACK returned {result}", flush=True)
    return result
sess_mod.AsyncSession.rollback = _traced_rollback

from app.db import models  # noqa
from app.db.session import async_session_factory
import uuid

RESTAURANT_ID = uuid.UUID('2f177e23-7ace-4827-ac12-9f3a784d6531')

async def test():
    async with async_session_factory() as session:
        print(f"Session created: {id(session)}")

        from app.modules.customers.service import find_or_create_customer_by_phone

        customer = await find_or_create_customer_by_phone(
            session=session,
            restaurant_id=RESTAURANT_ID,
            phone='+34677777777',
        )
        print(f"Customer created: {customer.id}")
        customer.name = 'Debug Commit Test'
        await session.flush()
        print("After flush - customer in DB?")

        # Check with raw SQL within same session
        from sqlalchemy import text
        result = await session.execute(
            text("SELECT id, phone, name FROM customers WHERE id = :cid"),
            {"cid": str(customer.id)}
        )
        row = result.fetchone()
        print(f"Same session check: {row}")

        await session.commit()
        print("After commit")

        # Check with raw SQL after commit (same session)
        result2 = await session.execute(
            text("SELECT id, phone, name FROM customers WHERE id = :cid"),
            {"cid": str(customer.id)}
        )
        row2 = result2.fetchone()
        print(f"Same session after commit: {row2}")

    # Check with a fresh session
    print("\n=== Fresh session check ===")
    async with async_session_factory() as session2:
        result3 = await session2.execute(
            text("SELECT id, phone, name FROM customers WHERE phone = '34677777777'")
        )
        rows = result3.fetchall()
        print(f"Fresh session result: {rows}")

asyncio.run(test())
