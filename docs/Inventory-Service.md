# Inventory Service Integration Notes

Este archivo no afecta el funcionamiento del microservicio jovenes.
Sirve como recordatorio de los ajustes pendientes para integrarlo con el resto del sistema.

## Cambios externos pendientes

- Actualizar `docker-compose.yml` para habilitar `inventory-service` dentro del flujo local cuando se quiera ejecutar junto con los otros microservicios.
- Ajustar `order-service` para que consulte `inventory-service` antes de completar una orden cuando se implemente esa integracion.
- Definir variables de entorno o URLs internas en el servicio orquestador para localizar `inventory-service` dentro de Docker o Kubernetes.
- Agregar manifiestos de Kubernetes o chart values de Helm para desplegar `inventory-service` en Minikube.
- Configurar probes de Kubernetes usando el endpoint `GET /health`.
- Exponer el servicio mediante un `Service` de Kubernetes con el puerto `8000`.
- Incluir pruebas de integracion y pruebas de carga futuras cuando se conecte al flujo de ordenes.

## Limites actuales del microservicio

- Solo consulta productos y disponibilidad.
- No reserva inventario.
- No descuenta stock.
- No actualiza productos.
- No usa base de datos.
- No comparte estado entre instancias.

## Endpoints disponibles

- `GET /health`
- `GET /inventory/{product_id}`
- `GET /inventory/{product_id}/availability`

## Autor

- Uriel Ortiz