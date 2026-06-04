# order-service

## Rol

Orquesta la orden completa y persiste el resultado en la tabla `orders`.

## Endpoints reales

- `GET /health`
- `GET /circuit-breaker/payment`
- `POST /orders`
- `POST /chaos/config`

## Body real de `POST /orders`

```json
{
  "user_id": 1,
  "product_id": 1,
  "quantity": 1
}
```

## Flujo

1. Valida usuario
2. Revisa disponibilidad
3. Reserva stock
4. Procesa pago
5. Envia notificacion
6. Persiste orden
7. Responde con `success`, `warning`, `held` o `error`

## Uso principal

```powershell
Invoke-RestMethod -Method Post -Uri http://localhost:8000/orders `
  -ContentType 'application/json' `
  -Body '{"user_id":1,"product_id":1,"quantity":1}'
```
