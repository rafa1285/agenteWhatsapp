import os
from twilio.rest import Client
from dotenv import load_dotenv

# Cargar variables desde el archivo .env
load_dotenv()

# Configuración desde el .env
ACCOUNT_SID = os.getenv('TWILIO_ACCOUNT_SID')
AUTH_TOKEN = os.getenv('TWILIO_AUTH_TOKEN')
VOICE_BASE_URL = os.getenv('VOICE_BASE_URL')

# Datos para la prueba
MY_PHONE_NUMBER = '+34635310524' 
TWILIO_PHONE_NUMBER = '+4915888620339' 

if not all([ACCOUNT_SID, AUTH_TOKEN, VOICE_BASE_URL]):
    print("Error: Faltan variables de entorno (SID, Token o VOICE_BASE_URL).")
    exit(1)

# Limpiar VOICE_BASE_URL por si tiene /api/voice/call al final
base_url = VOICE_BASE_URL.rstrip('/')
if '/api/voice/call' in base_url:
    webhook_url = base_url
else:
    webhook_url = f"{base_url}/api/voice/call"

client = Client(ACCOUNT_SID, AUTH_TOKEN)

try:
    print(f"Iniciando llamada de prueba al {MY_PHONE_NUMBER}...")
    print(f"Usando webhook: {webhook_url}")
    call = client.calls.create(
        from_=TWILIO_PHONE_NUMBER,
        to=MY_PHONE_NUMBER,
        url=webhook_url
    )
    print(f"¡Llamada iniciada con éxito! SID: {call.sid}")
    print("Deberías recibir la llamada en unos segundos.")
except Exception as e:
    print(f"Error al crear la llamada: {e}")
