# Producto 1 — Recepcionista IA por WhatsApp y Teléfono

**Cliente piloto:** Er Pichi de Cai (Alhaurín de la Torre)
**Tipo de producto:** SaaS multi-tenant de automatización con IA para restaurantes
**Estado del documento:** Especificación funcional y técnica actualizada

---

## 1. Objetivo del producto

Sustituir la atención manual de reservas y consultas frecuentes de un restaurante, atendiendo por WhatsApp y teléfono de forma autónoma, 24/7, sin depender de plataformas externas de reservas (TheFork, OpenTable) ni de sus comisiones.

## 2. Canales

- WhatsApp (texto), vía WhatsApp Business API
- Teléfono (voz), vía desvío de llamadas a número virtual (TwiML estándar y Media Streams)

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
| Recordatorios | Automático 24h antes de la reserva, más variantes (ver sección 11) |
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
id, name, public_phone, whatsapp_number_id, voice_number, timezone, opening_time / closing_time, prompt_tone, active, no_show_threshold, auto_confirm_enabled, supported_languages, large_group_threshold, live_transfer_enabled, transfer_phone, transfer_hours, confirmation_deadline, preorder_enabled.

### 7.2 `tables` (mesas)
id, restaurant_id, name, zone (indoor/terrace/bar), min_capacity, max_capacity, position_x, position_y.

### 7.3 `shifts` (turnos de servicio)
id, restaurant_id, weekday / special_date, start_time, end_time, average_table_duration, max_capacity.

### 7.4 `customers`
id, restaurant_id, phone (clave única de reconocimiento), name, allergies, preferences, preferred_table_id, preferred_language, visit_count, last_visit, no_show_count, requires_prior_confirmation, last_complaint_date, estimated_average_ticket, last_order.

### 7.5 `reservations`
id, restaurant_id, customer_id, table_id, date, time, party_size, preferred_zone, status (pending / pending_confirmation / confirmed / modified / cancelled / completed / no_show), source_channel (whatsapp/voice/web), notes, assignment_reason, has_preorder, checked_in_at, created_at, updated_at.

### 7.6 `reminders`
id, reservation_id, type (24h_reminder / mandatory_confirmation / release_notice / post_visit), status (pending/sent/failed/cancelled), scheduled_send_at, sent_at, channel (whatsapp/sms).

### 7.7 `conversations`
id, restaurant_id, customer_id (nullable), channel, transcript, outcome (reservation_created/query/complaint/escalated), date.

### 7.8 `escalations`
id, restaurant_id, conversation_id, reason, status (pending/resolved), date.

### 7.9 `owner_users`
id, restaurant_id, email, password_hash, role (owner/manager).

### 7.10 `menu_items` (módulo precomanda)
id, restaurant_id, name, category, price, allergens, available.

### 7.11 `preorders` (módulo precomanda)
id, reservation_id, customer_id, items, status (suggested/customer_confirmed/sent_to_kitchen/delivered/cancelled), origin, created_at.

---

## 8. Lógica de negocio

### 8.1 Asignación de mesa (orden de prioridad)
1. Petición específica del cliente.
2. Mesa habitual (`preferred_table_id`).
3. Algoritmo estándar de disponibilidad.
4. Alternativa si no hay disponibilidad.

### 8.2 Gestión de no-shows
Al superar `no_show_threshold` → `requires_prior_confirmation = true`. Exige confirmación obligatoria antes de `confirmation_deadline`.

### 8.3 Multi-idioma
Detección automática del idioma entrante o uso de `preferred_language`.

### 8.4 Derecho al olvido (RGPD)
Anonimización de `customers` y desvinculación de `reservations` históricas. Log de trazabilidad legal.

---

## 9. Flujos de conversación — WhatsApp

(Mantenidos según especificación original: Reservas, Datos incompletos, Disponibilidad, No-shows, Modificaciones, FAQs via RAG, Grupos grandes, Quejas, Fuera de dominio, Multi-idioma, Fallo técnico, Precomandas).

---

## 10. Flujos de conversación — Voz / Teléfono

Reutilizan la lógica de WhatsApp, adaptando la capa de interacción.

### 10.1 Modo TwiML (Estándar)
- **Tornos**: Interacción basada en `<Gather>` y `<Say>`.
- **Silencios**: Repregunta a los ~4s, cuelga a los ~8s adicionales.
- **Baja Confianza**: Petición de repetición si el STT de Twilio es insuficiente.
- **Confirmación**: Toda reserva por voz genera confirmación escrita por WhatsApp.

### 10.2 Modo Media Stream (Avanzado)
- **Pipeline**: Audio Twilio → Deepgram (STT) → Claude (LLM) → ElevenLabs (TTS) → Audio Twilio.
- **Barge-in**: Detención inmediata del audio del agente al detectar habla del usuario.
- **Estado**: PARCIAL (Pendiente de implementación de `run_conversation_stream`).
- **RGPD**: Aviso de grabación obligatorio al inicio.

### 10.3 Escalación y Transferencia
- Si `live_transfer_enabled = true` y está en `transfer_hours`, se ejecuta `<Dial>` al `transfer_phone`.
- Si falla o está desactivado, se genera escalación urgente.

---

## 11. Recordatorios automáticos

| Tipo | Disparo | Objetivo |
|---|---|---|
| `24h_reminder` | 24h antes | Reducir no-shows |
| `mandatory_confirmation` | Mismo día | Solo clientes con riesgo de no-show |
| `release_notice` | No confirmación | Informar liberación de mesa |
| `post_visit` | Post-visita | Feedback / reseña |

**Worker**: Celery + Redis Beat. Procesa recordatorios `PENDING` vencidos con reintentos automáticos.

---

## 12. Memoria de clientes recurrentes

- Búsqueda por teléfono inmediata.
- Actualización de `visit_count` y `preferred_table_id` (tras 2+ visitas a misma zona).
- Registro inmediato de alergias y preferencias.
- Integración natural de la memoria en el diálogo.

---

## 13. Módulo opcional — Comanda anticipada / Precomanda

Sugerencia de repetir pedido o envío de carta tras confirmar reserva. Validación humana obligatoria antes de enviar a cocina.

---

## 14. Panel web del dueño

Secciones: Hoy, Reservas, Mesas y turnos (Plano visual), Clientes, Escalaciones, Carta/Precomanda, Configuración y Estadísticas.
Roles: Dueño (Acceso total) y Encargado (Acceso operativo).
Auth: JWT RS256.

---

## 15. Arquitectura técnica

### Stack de Componentes
- **LLM**: Claude Haiku 4.5 (tool-calling).
- **STT (Streaming)**: Deepgram.
- **TTS (Streaming)**: ElevenLabs.
- **Vector Store**: Qdrant.
- **Embeddings**: OpenAI (`text-embedding-3-small`).
- **WhatsApp API**: 360dialog / Meta.
- **Voz**: Twilio.
- **Worker**: Celery + Redis.
- **Backend**: FastAPI (Python) + SQLAlchemy (PostgreSQL).
- **Panel**: Laravel + Livewire.

### Comunicación Panel $\leftrightarrow$ Backend
HTTP interno con JWT compartido en red privada. Comparten la misma base PostgreSQL.

---

## 16. Costes estimados por restaurante cliente

| Concepto | Coste/mes estimado | Nota |
|---|---|---|
| Twilio (Número + Minutos) | 15-35 € | |
| ElevenLabs (Voz) | 10-25 € | |
| Deepgram (STT) | sin dato | Pendiente de tarifa |
| Claude (Tokens) | 5-15 € | |
| Qdrant / OpenAI | sin dato | Pendiente de tarifa |
| WhatsApp API | 0-15 € | Según conversaciones |
| Infraestructura | 5-10 € | |
| **Total estimado** | **~60-100 €** | Conservador |

---

## 17. Modelo de pricing propuesto

- **Setup inicial:** 490-790 € (único).
- **Suscripción base:** 149 €/mes.
- **Add-on precomanda:** A definir.

---

## 18. Roadmap de construcción

1. Estructura FastAPI → 2. Modelos SQLAlchemy → 3. Motor Reservas → 4. Cliente Claude → 5. Definition Tools → 6. Orquestador → 7. Webhook WhatsApp → 8. E2E Local → 9. Canal Voz (TwiML → Stream) → 10. Recordatorios → 11. Panel Web → 12. Integración → 13. Piloto → 14. Productización.

---

## 19. Riesgos y mitigaciones

- **Acento/Ruido**: Confirmación doble por WhatsApp.
- **Control del Dueño**: Modo copiloto inicial.
- **RGPD**: Datos UE, DPA con proveedores (Deepgram, ElevenLabs, Qdrant, OpenAI: región y DPA pendientes de verificar), derecho al olvido.
- **Dependencia LLM**: Capa de modelo abstraída.

---

## Historial de Cambios

- **2026-10-17**: Actualización de arquitectura de voz a modular (STT Deepgram, TTS ElevenLabs), integración de base de datos vectorial (Qdrant) para FAQs y actualización de estado de implementación (Sincronización con código actual).
