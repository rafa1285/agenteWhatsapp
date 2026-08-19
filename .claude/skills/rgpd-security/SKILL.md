---
name: rgpd-security
description: Se activa al escribir o revisar cualquier código que lea, escriba o elimine datos de customers, reservations o conversations; y al escribir endpoints o webhooks expuestos públicamente (WhatsApp, Twilio, panel). Úsala antes de dar por bueno cualquier cambio que toque PII o superficie pública.
---

# RGPD y seguridad

Reglas obligatorias al tocar datos de clientes (`customers`), reservas
(`reservations`), conversaciones (`conversations`) o cualquier endpoint/webhook
público.

## Derecho al olvido

- **Confirmación explícita** antes de ejecutar el borrado de un cliente.
- Borrar/anonimizar los datos del cliente **y desvincularlo**.
- Las **reservas históricas se conservan sin PII** (obligación fiscal): se
  eliminan los datos personales del `customer` pero se mantiene el registro de
  la reserva desvinculado de la persona.
- Guardar un **log de trazabilidad** de la operación de olvido.

## PII y logs

- **Nunca loguear PII en texto plano** (teléfonos, nombres, alergias,
  direcciones): enmascarar en logs.
- Cuidado con excepciones/errores que puedan exponer datos de cliente.

## Aislamiento multi-tenant como seguridad

- El filtrado por `restaurant_id` es un **control de seguridad**, no solo de
  negocio: un tenant no debe poder leer ni modificar datos de otro. Toda query
  filtra por `restaurant_id` (ver [[backend-conventions]]).
- Endpoints y webhooks públicos validan siempre el tenant y el origen.

## Datos sensibles

- **Alergias y preferencias son datos de salud-adyacentes**: trato extra de
  confidencialidad; no exponerlos salvo donde sea estrictamente necesario.

## Voz (para cuando llegue el canal)

- **Grabación de llamadas: aviso obligatorio al inicio** de la llamada, antes
  de grabar.

## Secretos y configuración

- **Nunca hardcodear secretos ni commitear `.env`**. Secretos solo vía
  `app/core/settings.py` + `.env`.
- Revisar con una pasada de seguridad los cambios en estas áreas antes de
  commitear (endpoints públicos, webhooks, borrado de datos).
