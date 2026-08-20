# payment-service

## Rol

Simula el cobro y persiste cada intento en la tabla `payments`.

## Endpoints reales

- `GET /health`
- `POST /pay`
- `POST /chaos/config`

## Body real de `POST /pay`

```json
{
  "order_id": 3,
  "amount": 89.99,
  "user_id": 1
}
```

## Notas

- Persiste pagos exitosos y fallidos
- Usa `users/{user_id}` como apoyo si falta contexto del cliente
- `order-service` interpreta `status=success` como pago aceptado
