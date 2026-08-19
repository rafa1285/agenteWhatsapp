#!/usr/bin/env python
"""Test reservation creation flow via backend API."""

import datetime
import json
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
headers = {'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'}

BASE_URL = 'http://127.0.0.1:8001'

print('=== Step 1: Create customer ===')
phone = '+34611111111'
create_customer_url = f'{BASE_URL}/api/v1/customers?phone={phone}&name=Test%20Customer%20Flow'
response = httpx.post(create_customer_url, headers=headers, timeout=10)
print('Status:', response.status_code)
print('Response:', json.dumps(response.json(), indent=2))

if response.status_code == 201:
    customer_id = response.json().get('id')
    restaurant_id_from_customer = response.json().get('restaurant_id')
    print(f'Customer ID: {customer_id}')
    print(f'Customer restaurant_id: {restaurant_id_from_customer}')

    print()
    print('=== Step 2: Verify customer in DB via GET /api/v1/customers ===')
    get_customer_response = httpx.get(f'{BASE_URL}/api/v1/customers?search=6111111111', headers=headers, timeout=10)
    print('Status:', get_customer_response.status_code)
    print('Response:', json.dumps(get_customer_response.json(), indent=2))

    print()
    print('=== Step 3: Create reservation ===')
    # Use a valid table_id from the reservations list (cf07ad9b-1852-482a-8754-6be815907268)
    reservation_body = {
        'customer_id': customer_id,
        'date': '2026-08-23',
        'time': '14:00',
        'party_size': 2,
        'source_channel': 'web',
        'requested_table_id': 'cf07ad9b-1852-482a-8754-6be815907268'
    }
    print('Request body:', json.dumps(reservation_body, indent=2))
    create_reservation_url = f'{BASE_URL}/api/v1/reservations'
    response = httpx.post(
        create_reservation_url,
        json=reservation_body,
        headers=headers,
        timeout=10
    )
    print('Status:', response.status_code)
    print('Response:', json.dumps(response.json(), indent=2))
else:
    print('Failed to create customer, cannot proceed with reservation')
