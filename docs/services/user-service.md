# user-service

## Rol

Consulta y valida usuarios reales guardados en PostgreSQL dentro de `users.data`.

## Endpoints reales

- `GET /health`
- `POST /users`
- `GET /users`
- `POST /users/generate`
- `GET /users/{user_id}`
- `GET /users/{user_id}/validate`
- `GET /users/{user_id}/orders` - historial de pedidos del cliente (lee la
  tabla `orders` compartida, la misma que usa `order-service` - sin llamada
  de red entre servicios). 404 si el cliente no existe; `[]` si existe pero
  no tiene pedidos. Cierra un requisito explícito de la propuesta ("User
  service: ... y el historial de pedidos") que faltaba hasta ahora.
- `POST /chaos/config`

## Uso principal

```powershell
Invoke-RestMethod http://localhost:8101/users/1/validate
```

## Notas

- Usa `services/user-service/database.py`
- Lee y escribe en la tabla `users`
- `order-service` depende de `GET /users/{user_id}/validate`
