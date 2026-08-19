# Producto 1 — Recepcionista IA por WhatsApp y Teléfono

**Cliente piloto:** Er Pichi de Cai (Alhaurín de la Torre)
**Tipo de producto:** SaaS multi-tenant de automatización con IA para restaurantes
**Estado del documento:** Especificación funcional y técnica cerrada — Pasos 1 a 8 completados

---

## 1. Objetivo del producto

Sustituir la atención manual de reservas y consultas frecuentes de un restaurante, atendiendo por WhatsApp y teléfono de forma autónoma, 24/7, sin depender de plataformas externas de reservas (TheFork, OpenTable) ni de sus comisiones.

## 2. Canales

- WhatsApp (texto), vía WhatsApp Business API
- Teléfono (voz), vía desvío de llamadas a número virtual

## 3. Actores

| Actor | Rol |
|---|---|
| Cliente | Interactúa con el agente para reservar, consultar, modificar o cancelar |
| Dueño / encargado | Recibe avisos, gestiona el panel web, resuelve escaladas |
| Agente IA | Ejecuta la conversación y las acciones sobre el motor de reservas |

## 4. Funcionalidades incluidas (v1 completa)

| Área | Funcionalidad |
|---|---|
| Reservas | Crear, consultar, modificar, cancelar |
| Disponibilidad | Comprobación real contra mesas / turnos / aforo configurado |
| Confirmaciones | Automáticas al crear o modificar una reserva |
| Recordatorios | Automático 24h antes de la reserva, más variantes (ver sección 8) |
| Memoria | Reconocimiento de clientes recurrentes (teléfono, historial, preferencias, alergias) |
| Escalado | Aviso al dueño cuando el agente no puede resolver algo |
| Panel web | Reservas, mesas, disponibilidad, clientes, estadísticas, configuración |
| Multi-restaurante | Arquitectura multi-tenant desde el diseño inicial |
| Comanda anticipada (módulo opcional) | Sugerencia de repetir pedido, envío de carta, precomanda con check-in |

## 5. Fuera de alcance (explícito)

- Pedidos a domicilio o delivery
- Gestión de inventario / proveedores
- Facturación o contabilidad
- Gestión de personal / turnos de empleados
- Integraciones con plataformas externas de reservas (TheFork, OpenTable)

## 6. Eventos críticos gestionados

- Restaurante completo en el horario solicitado → ofrecer alternativa
- Petición ambigua ("para esta noche tarde") → pedir aclaración, nunca asumir
- Grupo grande (umbral configurable) → escalado al dueño, no autoconfirmado
- Queja o tono negativo → escalado inmediato, el agente no intenta resolver
- Cancelación con poca antelación → registrado para estadística de no-shows
- Fallo de conexión con el motor de reservas → mensaje de respaldo + aviso al dueño

---

## 7. Modelo de datos

### 7.1 `restaurants`
| Campo | Descripción |
|---|---|
| id | Identificador |
| name | Nombre del restaurante |
| public_phone | Teléfono de contacto |
| whatsapp_number_id | ID del número de WhatsApp Business |
| voice_number | Número Twilio asignado |
| timezone | Zona horaria del restaurante |
| opening_time / closing_time | Horario general (o tabla aparte si varía por día) |
| prompt_tone | Personalidad del agente (formal, cercano, con gracia andaluza, etc.) |
| active | Booleano |
| no_show_threshold | Nº de no-shows a partir del cual se exige confirmación previa |
| auto_confirm_enabled | Booleano (default true); si es false, ninguna reserva se autoconfirma y las nuevas quedan en `pending_confirmation` |
| supported_languages | Lista de idiomas atendidos (ej. ["es","en"]) |
| large_group_threshold | Nº de comensales a partir del cual se escala al dueño |
| live_transfer_enabled | Booleano, configurable por el dueño |
| transfer_phone | Número al que se transfiere la llamada si está activo |
| transfer_hours | Franja en la que el dueño acepta transferencias |
| confirmation_deadline | Hora límite para confirmación obligatoria de reservas con riesgo de no-show |
| preorder_enabled | Booleano, activa/desactiva el módulo de comanda anticipada |

### 7.2 `tables` (mesas)
id, restaurant_id, name, zone (indoor/terrace/bar), min_capacity, max_capacity, position_x, position_y (coordenadas para el plano visual del panel)

### 7.3 `shifts` (turnos de servicio)
id, restaurant_id, weekday / special_date, start_time, end_time, average_table_duration, max_capacity

### 7.4 `customers`
id, restaurant_id, phone (clave única de reconocimiento), name, allergies, preferences, preferred_table_id, preferred_language, visit_count, last_visit, no_show_count, requires_prior_confirmation, last_complaint_date, estimated_average_ticket (preparado para integración futura con TPV), last_order

### 7.5 `reservations`
id, restaurant_id, customer_id, table_id (asignada siempre en el momento de crear la reserva), date, time, party_size, preferred_zone, status (pending / pending_confirmation / confirmed / modified / cancelled / completed / no_show), source_channel (whatsapp/voice/web), notes, assignment_reason (specific_request / habitual_table / standard_availability), has_preorder, checked_in_at, created_at, updated_at

### 7.6 `reminders`
id, reservation_id, type (24h_reminder / mandatory_confirmation / release_notice / post_visit), status (pending/sent/failed/cancelled), scheduled_send_at, sent_at, channel (whatsapp/sms)

### 7.7 `conversations`
id, restaurant_id, customer_id (nullable), channel, transcript, outcome (reservation_created/query/complaint/escalated), date

### 7.8 `escalations`
id, restaurant_id, conversation_id, reason, status (pending/resolved), date

### 7.9 `owner_users`
id, restaurant_id, email, password_hash, role (owner/manager)

### 7.10 `menu_items` (módulo precomanda)
id, restaurant_id, name, category (starter/main/beverage/dessert), price, allergens, available

### 7.11 `preorders` (módulo precomanda)
id, reservation_id, customer_id, items (lista de plato/cantidad/notas), status (suggested/customer_confirmed/sent_to_kitchen/delivered/cancelled), origin (repeat_last/ai_suggestion/manual_choice), created_at

### Relaciones clave
- Un `restaurant` tiene muchas `tables`, `shifts`, `customers`, `reservations`, `owner_users`, `menu_items`
- Una `reservation` pertenece a un `customer` y a una `table`
- Una `reservation` puede generar uno o varios `reminders` y un `preorder`
- Una `conversation` puede generar una `escalation`

---

## 8. Lógica de negocio

### 8.1 Asignación de mesa (orden de prioridad)
1. Petición específica del cliente en la conversación (si está libre)
2. Mesa habitual del cliente recurrente, vía `preferred_table_id` (si está libre)
3. Algoritmo estándar de disponibilidad por mejor ajuste de aforo
4. Si la preferida/solicitada no está libre → se informa y se ofrece alternativa

`preferred_table_id` solo se fija tras repetir la misma zona 2+ veces (evita fijar preferencia por una visita casual).

### 8.2 Gestión de no-shows
- Cada no-show incrementa `no_show_count`
- Al superar `no_show_threshold` → `requires_prior_confirmation = true`
- Reservas futuras de ese cliente exigen confirmación explícita el mismo día antes de `confirmation_deadline`; si no confirma, la reserva se cancela y la mesa se libera automáticamente

### 8.3 Multi-idioma
- El agente detecta el idioma del mensaje entrante o usa `preferred_language` si el cliente ya existe
- Respuestas, confirmaciones y recordatorios se generan en ese idioma
- El panel web permanece siempre en español (usuario = dueño)

### 8.4 Derecho al olvido (RGPD)
- El cliente puede solicitarlo directamente al agente por WhatsApp
- Requiere confirmación explícita antes de ejecutar
- Se anonimiza/elimina el registro de `customers`; las `reservations` históricas se desvinculan del cliente (se conservan sin datos personales por obligación fiscal)
- Se genera un log de "derecho al olvido ejercido" con fecha, para trazabilidad legal

---

## 9. Flujos de conversación — WhatsApp

1. **Reserva nueva (camino feliz)**: identifica intención → busca cliente por teléfono → extrae entidades → comprueba disponibilidad → asigna mesa según prioridad → crea reserva → confirma con resumen
2. **Datos incompletos**: nunca asume comensales/hora por defecto; siempre pregunta; resuelve expresiones relativas ("esta noche") confirmando la fecha exacta
3. **Mesa/hora no disponible**: ofrece alternativas de horario o de zona
4. **Cliente con no-shows**: crea reserva en estado `pending_confirmation`, exige confirmación con plazo, libera automáticamente si no se confirma
5. **Consultar / modificar / cancelar**: localiza reserva por teléfono; si hay varias, pregunta cuál; nunca cancela sin confirmación explícita
6. **FAQs (RAG)**: horario, ubicación, parking, alérgenos, menú del día, mascotas, WiFi, formas de pago, aforo para grupos
7. **Grupo grande**: por encima del umbral, no autoconfirma — genera escalación y notifica al dueño
8. **Queja / tono negativo**: no intenta resolver, escala inmediatamente con transcript completo
9. **Fuera de dominio**: redirige con humor/amabilidad, nunca ignora
10. **Multi-idioma**: detecta idioma, responde en el mismo, actualiza `preferred_language`
11. **Fallo técnico**: mensaje de respaldo con los datos ya capturados + escalación `technical_failure`
12. **Sugerencia de repetir pedido / carta** (módulo precomanda): tras confirmar reserva, ofrece repetir último pedido o enviar carta
13. **Check-in con precomanda** (módulo precomanda, disparado manualmente desde el panel): confirma con el camarero si se envía a cocina lo ya pedido
14. **Pedido anticipado directo**: el cliente pide comida al reservar; se verifica contra `menu_items` y se confirma antes de crear el `preorder`

**Reglas transversales:** nunca inventar disponibilidad; toda confirmación incluye fecha/hora/comensales/zona; máximo 2 intentos de clarificación antes de escalar a humano.

---

## 10. Flujos de conversación — Voz / Teléfono

Reutilizan toda la lógica de negocio de WhatsApp; cambia la capa de interacción.

1. **Reserva por voz (camino feliz)**: mismo pipeline de extracción; siempre se cierra con confirmación escrita por WhatsApp/SMS tras colgar
2. **Repetición y verificación de datos críticos**: todo dato sensible (fecha, hora, comensales, nombre) se repite en voz alta antes de ejecutar cualquier acción
3. **Silencios**: si no hay respuesta en ~4s pregunta si sigue ahí; a los 8s adicionales cuelga y registra la llamada como incompleta
4. **Interrupciones (barge-in)**: el agente detiene el audio inmediatamente si el cliente interrumpe
5. **Baja confianza del STT**: si la transcripción de un dato crítico tiene baja confianza, se pide repetición, nunca se asume
6. **Queja / escalada urgente**: si `live_transfer_enabled = true` y dentro de `transfer_hours`, intenta transferir la llamada; si no contesta en ~15s o la opción está desactivada, genera escalación urgente y notifica al dueño
7. **Cliente recurrente reconocido por Caller ID**: personalización inmediata ("¿reservamos otra vez en tu terraza de siempre?")
8. **Fallo técnico durante la llamada**: informa del problema, conserva los datos capturados, escala con transcript completo

**Reglas transversales:** toda reserva por voz genera confirmación escrita; latencia objetivo de respuesta < 1,5s; todas las llamadas se graban y transcriben; aviso de grabación obligatorio al inicio (RGPD/LOPD).

---

## 11. Recordatorios automáticos

| Tipo | Disparo | Objetivo |
|---|---|---|
| `24h_reminder` | 24h antes de la reserva | Reducir no-shows |
| `mandatory_confirmation` | Mismo día, hora límite configurable | Solo clientes con `requires_prior_confirmation` |
| `release_notice` | Si no se confirma la obligatoria | Informar liberación de mesa |
| `post_visit` | Reserva completada + horas configurables | Feedback / reseña Google |

**Worker programado:** revisa cada pocos minutos los `reminders` pendientes cuya fecha de envío ya llegó; verifica que la reserva sigue activa antes de enviar; reintento máximo de 2 veces si falla el envío; fallback a SMS si el número no tiene WhatsApp.

**Cascada de cancelación:** si la reserva se cancela o modifica antes de la hora programada, los recordatorios asociados se cancelan automáticamente.

---

## 12. Memoria de clientes recurrentes

- Se busca por teléfono en cada interacción, antes de responder nada
- `visit_count` se incrementa al completarse la reserva (no al crearla)
- `preferred_table_id` se actualiza solo tras repetir zona 2+ veces
- Alergias/preferencias mencionadas en conversación se guardan de inmediato (dato de seguridad, no espera a que termine la reserva)
- `last_complaint_date` marca al cliente para tratamiento más cuidadoso en interacciones futuras
- Regla de naturalidad: el agente nunca debe sonar como una base de datos hablando ("según mis registros...") — siempre integra la memoria de forma conversacional natural

---

## 13. Módulo opcional — Comanda anticipada / Precomanda

Activable/desactivable por restaurante vía `preorder_enabled`. Vendible como add-on de precio superior.

- **Al reservar:** el agente sugiere repetir el último pedido o envía la carta (`menu_items`) por WhatsApp para elegir con antelación
- **Check-in manual (Opción A):** el camarero/encargado marca "cliente en mesa" desde el panel; si hay precomanda, se muestra aviso destacado para confirmar envío a cocina con un clic
- **Pedido anticipado directo:** el cliente puede pedir comida al mismo tiempo que reserva; se valida contra el catálogo antes de confirmar
- **Regla de seguridad:** ningún pedido pasa a cocina sin validación humana explícita (mínimo un clic)

---

## 14. Panel web del dueño

### Secciones
1. **Hoy** — vista principal: reservas del turno, alertas (alergia/celebración/precomanda), check-in, contador de escalaciones
2. **Reservas** — listado, filtros, edición/creación/cancelación manual, histórico de no-shows
3. **Mesas y turnos** — configuración de mesas y turnos, **plano visual de sala** (arrastrar mesas, estado en tiempo real: libre/reservada/ocupada/con precomanda)
4. **Clientes** — buscador, ficha completa, borrado manual de datos
5. **Escalaciones** — bandeja de avisos con transcript completo, marcar como resuelto
6. **Carta y precomanda** *(si el módulo está activo)* — gestión de `menu_items`, activación del módulo, precomandas pendientes de check-in
7. **Configuración** — datos del restaurante, umbrales, idiomas, transferencia en vivo, tono del agente, gestión de usuarios
8. **Estadísticas** — reservas por día/semana, tasa de no-shows, recurrentes vs. nuevos, consultas frecuentes al agente, ocupación media por turno, platos más pedidos en precomanda

### Roles
- **Dueño:** acceso total, incluida configuración y gestión de usuarios
- **Encargado:** acceso operativo (Hoy, Reservas, Mesas, Escalaciones, Clientes, Carta), sin configuración ni gestión de usuarios

### Autenticación
Login con email + contraseña, recuperación de contraseña incluida desde v1. 2FA no obligatorio en v1, diseño abierto a añadirlo.

### Nota técnica de estadísticas
Se recomienda precalcular las métricas en un job diario en lugar de calcularlas al vuelo, para no sobrecargar la base de datos en cada carga del panel.

---

## 15. Arquitectura técnica

```
┌─────────────┐   ┌──────────────────┐
│  Teléfono   │   │     WhatsApp      │
│ (desvío a   │   │ (Business API     │
│ nº virtual) │   │  vía 360dialog)   │
└──────┬──────┘   └────────┬─────────┘
       │                   │
┌──────▼──────┐     ┌──────▼─────────┐
│ Twilio Voice │     │ Webhook         │
│ + STT/TTS    │     │ 360dialog       │
└──────┬──────┘     └──────┬─────────┘
       │                   │
       └────────┬──────────┘
                ▼
      ┌──────────────────┐
      │  FastAPI (core)   │   Python, multi-tenant
      │  Orquestador de   │   config por restaurante
      │  conversación     │
      └────────┬─────────┘
               ▼
      ┌──────────────────┐     ┌─────────────────┐
      │  Claude Haiku 4.5 │────▶│ Tools:           │
      │  + tool-calling   │     │ check_availability│
      │                   │     │ create_booking    │
      │                   │     │ cancel/modify      │
      │                   │     │ answer_faq (RAG)   │
      └──────────────────┘     └────────┬────────┘
                                        ▼
                          ┌──────────────────────────┐
                          │  PostgreSQL               │
                          │  Motor de reservas propio  │
                          └─────────────┬────────────┘
                                        ▼
                          ┌──────────────────────────┐
                          │  Panel web (Laravel +      │
                          │  Livewire, Sanctum, Spatie)│
                          └──────────────────────────┘
```

### Stack definitivo

| Componente | Elección | Justificación |
|---|---|---|
| LLM del agente | **Claude Haiku 4.5** | Mejor fiabilidad en tool-calling que GPT-4o-mini; coste diferencial bajo al volumen de un restaurante |
| WhatsApp Business API (BSP) | **360dialog** | Sin markup sobre tarifas de Meta; pensado para quien construye su propia capa de IA |
| Voz (STT+LLM+TTS) | **ElevenLabs Conversational AI** (fase 1) | Mejor relación calidad de voz/coste/velocidad de implementación; migrable a stack modular (Deepgram + LLM + TTS) si el volumen crece |
| Backend / agente | **FastAPI (Python)** | Tool-calling nativo, async, encaja con el stack habitual del desarrollador |
| Base de datos | **PostgreSQL** | Relacional, soporte JSON para campos flexibles (preferencias, alergias) |
| Cache / estado de conversación | **Redis** (opcional recomendado) | Contexto de conversación activa sin sobrecargar Postgres |
| Panel web | **Laravel + Livewire** (Sanctum + Spatie Permissions) | Desarrollo más rápido dado el dominio previo de PHP/Laravel; CRUD, roles y auth nativos |
| Hosting | **Railway / Render o Hetzner + Coolify** | Suficiente para 1-20 restaurantes sin la complejidad de un cloud enterprise |
| Automatización interna (no del producto) | **n8n** (opcional, uso interno) | Solo para operaciones comerciales propias (onboarding de clientes nuevos, notificaciones internas); descartado como núcleo del agente por falta de memoria de sesión robusta, límites de ejecución y dificultad de mantenimiento multi-tenant a escala |

### Comunicación panel (Laravel) ↔ agente (FastAPI)
HTTP interno con JWT compartido, en red privada del mismo servidor. Ambos servicios leen/escriben en la misma base PostgreSQL (Laravel vía Eloquent, FastAPI vía SQLAlchemy).

---

## 16. Costes estimados por restaurante cliente

| Concepto | Coste/mes estimado |
|---|---|
| Número virtual + minutos de voz (Twilio) | 15-35 € |
| Voz STT+TTS (ElevenLabs) | 10-25 € |
| LLM (Claude Haiku 4.5, tokens) | 5-15 € |
| WhatsApp API (360dialog + Meta) | 0-15 € (tramo gratuito de conversaciones de servicio) |
| Infraestructura (prorrateada, multi-tenant) | 5-10 € |
| **Total estimado por cliente** | **35-100 € (conservador: ~60-70 €)** |

## 17. Modelo de pricing propuesto

- **Setup inicial:** 490-790 € (único) — configuración, número, desvío de llamadas, carga de carta/FAQs, pruebas
- **Suscripción base:** 149 €/mes (hasta ~400 conversaciones; excedente a 0,30 €/conversación)
- **Add-on módulo precomanda:** precio superior, a definir según valor percibido
- **Permanencia:** 3 meses mínimo
- **Prueba:** 15 días gratis + demo en directo llamando al propio número del restaurante

---

## 18. Roadmap de construcción

1. Estructura del proyecto FastAPI (carpetas, dependencias, configuración base)
2. Modelos de datos (SQLAlchemy — tablas de la sección 7)
3. Motor de reservas (funciones puras: check_availability, create_reservation, modify, cancel)
4. Conexión con Claude Haiku (cliente LLM, prompt de sistema base)
5. Definición de tools (funciones expuestas al LLM para tool-calling)
6. Orquestador de conversación (LLM + tools + memoria de contexto)
7. Webhook de WhatsApp (recepción vía 360dialog, respuesta)
8. Prueba end-to-end en local (conversación completa de reserva simulada)
9. Canal de voz (Twilio + ElevenLabs)
10. Recordatorios automáticos (worker programado)
11. Panel web (Laravel + Livewire)
12. Integración y pruebas conjuntas
13. Piloto real con Er Pichi de Cai
14. Productización para réplica multi-cliente (onboarding, plantillas de configuración)

---

## 19. Riesgos y mitigaciones

- **Voz con acento/ruido de calle:** confirmación doble por WhatsApp tras la llamada
- **El dueño quiere control:** modo "copiloto" opcional los primeros 15 días (el agente propone, el dueño valida)
- **RGPD:** datos en la UE, DPA con proveedores, cláusula de encargado de tratamiento en el contrato con cada restaurante, derecho al olvido implementado desde v1
- **Dependencia de un solo LLM:** abstraer la capa de modelo para poder cambiar de proveedor
- **Riesgo n8n/herramientas no-code:** descartado como núcleo por falta de fiabilidad en memoria de sesión y escalabilidad multi-tenant a este nivel de complejidad

---

*Documento de especificación técnica y funcional — Producto 1: Recepcionista IA por WhatsApp y Teléfono. Todas las decisiones reflejadas aquí han sido confirmadas explícitamente durante el proceso de diseño (Pasos 1-8).*
