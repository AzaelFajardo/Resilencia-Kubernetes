# notification-service

## Rol

Simula la entrega de notificaciones y persiste el resultado en `notifications`.

## Endpoints reales

- `GET /health`
- `POST /notify`
- `POST /chaos/config`

## Body real de `POST /notify`

```json
{
  "order_id": 3,
  "amount": 89.99,
  "user_id": 1
}
```

## Notas

- Puede complementar datos del cliente consultando `user-service`
- `order-service` lo usa como ultimo paso del flujo
- Devuelve `sent` en caso exitoso
