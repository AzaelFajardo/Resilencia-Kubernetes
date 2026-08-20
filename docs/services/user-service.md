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
- `POST /chaos/config`

## Uso principal

```powershell
Invoke-RestMethod http://localhost:8101/users/1/validate
```

## Notas

- Usa `services/user-service/database.py`
- Lee y escribe en la tabla `users`
- `order-service` depende de `GET /users/{user_id}/validate`
