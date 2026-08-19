#!/usr/bin/env python
"""Test JWT generation and backend API call."""

import datetime
from pathlib import Path

import httpx
import jwt

# Read private key from panel
private_key_path = Path(r'C:/laragon/www/agenteWhatsappPanel/storage/keys/private.pem')
private_key = private_key_path.read_text()

payload = {
    'iss': 'reception-panel',
    'aud': 'reception-api',
    'iat': int(datetime.datetime.now(datetime.UTC).timestamp()),
    'exp': int((datetime.datetime.now(datetime.UTC) + datetime.timedelta(hours=1)).timestamp()),
    'restaurant_id': '2f177e23-7ace-4827-ac12-9f3a784d6531',
}

token = jwt.encode(payload, private_key, algorithm='RS256')
print('Generated token:', token)
print()

# Test backend API
headers = {'Authorization': f'Bearer {token}'}
try:
    response = httpx.get('http://127.0.0.1:8001/api/v1/reservations', headers=headers, timeout=10)
    print('Status:', response.status_code)
    print('Response:', response.json())
except Exception as e:
    print('Error:', e)
