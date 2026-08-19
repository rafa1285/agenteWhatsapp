#!/usr/bin/env python
"""Debug customer creation via API - trace commits and rollbacks."""
import datetime

import httpx
import jwt

# Monkey-patch session to trace commits
import sqlalchemy.ext.asyncio.session as sess_mod

_orig_commit = sess_mod.AsyncSession.commit
async def _traced_commit(self):
    print(f"  >> API SESSION COMMIT called (session id={id(self)})", flush=True)
    import traceback; traceback.print_stack(limit=8)
    result = await _orig_commit(self)
    print(f"  >> API SESSION COMMIT returned {result}", flush=True)
    return result
sess_mod.AsyncSession.commit = _traced_commit

_orig_flush = sess_mod.AsyncSession.flush
async def _traced_flush(self, *args, **kwargs):
    print(f"  >> API SESSION FLUSH called (session id={id(self)})", flush=True)
    result = await _orig_flush(self, *args, **kwargs)
    print(f"  >> API SESSION FLUSH returned {result}", flush=True)
    return result
sess_mod.AsyncSession.flush = _traced_flush

_orig_rollback = sess_mod.AsyncSession.rollback
async def _traced_rollback(self):
    print(f"  >> API SESSION ROLLBACK called (session id={id(self)})", flush=True)
    import traceback; traceback.print_stack(limit=8)
    result = await _orig_rollback(self)
    print(f"  >> API SESSION ROLLBACK returned {result}", flush=True)
    return result
sess_mod.AsyncSession.rollback = _traced_rollback

# Now make the API call

payload = {
    'iss': 'reception-panel',
    'aud': 'reception-api',
    'iat': int(datetime.datetime.now(datetime.UTC).timestamp()),
    'exp': int((datetime.datetime.now(datetime.UTC) + datetime.timedelta(hours=1)).timestamp()),
    'restaurant_id': '2f177e23-7ace-4827-ac12-9f3a784d6531',
}
token = jwt.encode(payload, open(r'C:/laragon/www/agenteWhatsappPanel/storage/keys/private.pem').read(), algorithm='RS256')
headers = {'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'}

print("Making API call...")
response = httpx.post('http://127.0.0.1:8001/api/v1/customers?phone=+34688888888&name=APIDebug', headers=headers, timeout=10)
print(f"Status: {response.status_code}")
print(f"Response: {response.text}")
