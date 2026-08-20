# inventory-service

## Rol

Consulta productos, revisa disponibilidad y modifica stock real en PostgreSQL.

## Endpoints reales

- `GET /health`
- `POST /inventory/generate`
- `GET /inventory/{product_id}`
- `GET /inventory/{product_id}/availability`
- `POST /inventory/{product_id}/reserve`
- `POST /inventory/{product_id}/release`
- `POST /chaos/config`

## Uso principal

```powershell
Invoke-RestMethod http://localhost:8102/inventory/1/availability
```

## Notas

- Usa `services/inventory-service/database.py`
- Lee y escribe en `products`
- `order-service` depende de disponibilidad, reserva y liberacion
