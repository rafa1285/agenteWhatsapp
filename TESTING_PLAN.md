# Plan de Pruebas para el Flujo Completo de WhatsApp → App → Panel

## Objetivo
Verificar el flujo completo: envío de mensaje por WhatsApp → procesamiento por la app (FastAPI) → creación de reserva → visualización en el panel de control (Laravel).

## Prerrequisitos
1. Docker y Docker Compose instalados
2. Variables de entorno configuradas (ANTHROPIC_API_KEY, etc.)
3. Llaves JWT generadas en ambos repositorios

## Arquitectura de Pruebas
Utilizaremos el docker-compose.integration.yml que incluye:
- PostgreSQL (base de datos)
- Redis (caché/estado de conversación)
- Backend (FastAPI - agente WhatsApp)
- Panel (Laravel + Livewire)

## Fase 1: Preparación del Entorno

### 1.1 Generar llaves JWT
```bash
# En agenteWhatsappPanel
mkdir -p storage/keys
openssl genrsa -out storage/keys/private.pem 2048
openssl rsa -in storage/keys/private.pem -pubout -out storage/keys/public.pem

# Copiar la llave pública al backend (agenteWhatsapp)
cp agenteWhatsappPanel/storage/keys/public.pem agenteWhatsapp/storage/keys/
```

### 1.2 Configurar variables de entorno
Crear archivo `.env` en la raíz de cada proyecto basado en `.env.example`:
```bash
# agenteWhatsapp/.env
ANTHROPIC_API_KEY=tu_clave_aqui
WHATSAPP_API_TOKEN=tu_token_de_360dialog
WHATSAPP_WEBHOOK_VERIFY_TOKEN=mi_token_de_verificacion
BACKEND_WEBHOOK_SECRET=mi_secreto_de_webhook

# agenteWhatsappPanel/.env
APP_KEY=genera_una_key_con_php_artisan_key:generate
DB_CONNECTION=pgsql
DB_HOST=localhost
DB_PORT=5432
DB_DATABASE=agente_whatsapp
DB_USERNAME=postgres
DB_PASSWORD=postgres
REDIS_HOST=localhost
REDIS_PORT=6379
BACKEND_API_URL=http://localhost:8001
JWT_PRIVATE_KEY_PATH=/ruta/absoluta/a/storage/keys/private.pem
BACKEND_WEBHOOK_SECRET=mi_secreto_de_webhook
```

## Fase 2: Levantar Servicios de Integración

```bash
# Desde la raíz
docker compose -f agenteWhatsapp/docker-compose.integration.yml up -d
```

Verificar que los servicios estén saludables:
```bash
docker compose -f agenteWhatsapp/docker-compose.integration.yml ps
```

## Fase 3: Ejecutar Pruebas Automatizadas Existentes

### 3.1 Pruebas unitarias del backend
```bash
# Desde agenteWhatsapp
python -m pytest tests/ -v
```

### 3.2 Pruebas específicas del webhook de WhatsApp
```bash
# Desde agenteWhatsapp
python -m pytest tests/channels/whatsapp/ -v
```

## Fase 4: Prueba Manual End-to-End

### 4.1 Simular mensaje de WhatsApp mediante API directa

#### Paso 1: Obtener token JWT válido
```bash
# Generar token para pruebas (usando la llave privada del panel)
php -r "
require 'vendor/autoload.php';
use Firebase\JWT\JWT;
use Firebase\JWT\Key;

\$payload = [
    'iss' => 'reception-panel',
    'aud' => 'reception-api',
    'iat' => time(),
    'exp' => time() + 3600,
    'restaurant_id' => '2f177e23-7ace-4827-ac12-9f3a784d6531'
];

\$privateKey = file_get_contents('storage/keys/private.pem');
\$token = JWT::encode(\$payload, \$privateKey, 'RS256');
echo \$token;
"
```

#### Paso 2: Enviar mensaje de prueba al webhook
```bash
curl -X POST "http://localhost:8001/api/whatsapp/webhook" \
  -H "Content-Type: application/json" \
  -d '{
    "object": "whatsapp_business_account",
    "entry": [{
      "id": "acct-1",
      "changes": [{
        "field": "messages",
        "value": {
          "messaging_product": "whatsapp",
          "metadata": {
            "display_phone_number": "15551234567",
            "phone_number_id": "wa-100000"
          },
          "messages": [{
            "from": "34611111111",
            "id": "wamid.TEST123",
            "timestamp": "'$(date +%s)'",
            "type": "text",
            "text": {
              "body": "Hola, quiero reservar una mesa para dos personas mañana a las 7pm"
            }
          }]
        }
      }]
    }]
  }'
```

#### Paso 3: Verificar respuesta
Debería recibir: `{"status": "ok"}`

### 4.2 Verificar en la base de datos
```bash
# Conectar a PostgreSQL y verificar
docker exec -it agenteWhatsapp-panel-1 psql -U postgres -d agente_whatsapp

# Dentro de psql:
SELECT c.id, c.name, c.phone FROM customers c;
SELECT r.id, r.date, r.time, r.party_size, r.status FROM reservations r;
SELECT * FROM conversations;
SELECT * FROM webhook_messages;
```

### 4.3 Verificar en el panel de control
1. Acceder a: http://localhost:8002
2. Iniciar sesión (crear usuario primero si es necesario)
3. Navegar a la sección de Reservas
4. Verificar que aparezca la reserva creada

## Fase 5: Pruebas de Flujos Específicos

### 5.1 Flujo de reserva completa
1. Enviar mensaje: "Quiero reservar para 4 personas el viernes a las 8pm"
2. Verificar que el agente solicite confirmación de datos
3. Confirmar reserva
4. Verificar creación en DB y panel

### 5.2 Flujo de modificación
1. Crear reserva inicial
2. Enviar mensaje: "Quieres cambiar mi reserva a las 9pm en vez de 8pm"
3. Verificar procesamiento
4. Verificar actualización en panel

### 5.3 Flujo de cancelación
1. Crear reserva
2. Enviar mensaje: "Necesito cancelar mi reserva para mañana"
3. Verificar solicitud de confirmación
4. Confirmar cancelación
5. Verificar estado en panel

## Fase 6: Limpiar y Reiniciar

```bash
# Detener y eliminar contenedores
docker compose -f agenteWhatsapp/docker-compose.integration.yml down -v

# Volver a levantar si se necesitan más pruebas
docker compose -f agenteWhatsapp/docker-compose.integration.yml up -d
```

## Notas Importantes

1. Los tests usan un restaurante fijo con ID: `2f177e23-7ace-4827-ac12-9f3a784d6531`
2. El número de WhatsApp configurado en los tests es: `wa-100000`
3. El número de teléfono de prueba usado es: `+34611111111`
4. Para tests reales con 360dialog, necesitarás configurar un número real y webhook
5. Los recordatorios requieren un worker separado (no incluido en el compose básico)

## Troubleshooting

### Si los servicios no arrancan:
- Verificar logs: `docker compose -f agenteWhatsapp/docker-compose.integration.yml logs [service]`
- Asegurarse de que los puertos 5432, 6379, 8001, 8002 estén libres

### Si hay errores de JWT:
- Verificar que las llaves estén en las rutas correctas
- Confirmar que el algoritmo sea RS256 en ambos lados

### Si no se crean reservas:
- Revisar logs del backend: `docker compose -f agenteWhatsapp/docker-compose.integration.yml logs backend`
- Verificar conexión a base de datos
- Comprobar que los servicios de disponibilidad estén poblados (tables, shifts)