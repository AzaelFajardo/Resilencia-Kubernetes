# User Service – Integration Notes

## Objetivo
Documento de referencia para la integración futura de `user-service` con el resto de los microservicios.  
No afecta el funcionamiento actual del servicio.

---

## Cambios externos pendientes

- Actualizar `docker-compose.yml` para incluir `user-service` en el flujo local.
- Ajustar `order-service` u otros servicios para validar usuarios antes de procesar operaciones.
- Definir variables de entorno / URLs internas en el orquestador (Docker / Kubernetes).
- Integrar `user-service` con servicios que requieran autenticación o validación de usuarios.
- Agregar manifiestos de Kubernetes o valores de Helm para despliegue en Minikube.
- Configurar probes de Kubernetes usando `GET /health`.
- Exponer el servicio mediante un `Service` en el puerto `8000`.
- Implementar pruebas de integración.
- Implementar pruebas de carga.

---

## Límites actuales del microservicio

- Solo consulta usuarios por ID.
- Solo valida si un usuario existe y está activo.
- No crea usuarios.
- No actualiza usuarios.
- No elimina usuarios.
- No usa base de datos (datos en memoria).
- No maneja autenticación real (tokens, JWT, etc.).
- No comparte estado entre instancias.

---

## Endpoints disponibles

- `GET /health`
- `GET /users/{user_id}`
- `GET /users/{user_id}/validate`

## Autor

- Uriel Ortiz