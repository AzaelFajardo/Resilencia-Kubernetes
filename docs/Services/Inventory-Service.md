# Inventory Service Integration Notes

This file does not affect the current behavior of the microservice.
It serves as a reminder of the pending adjustments needed to integrate it with the rest of the system.

## Pending External Changes

- Update `docker-compose.yml` to enable `inventory-service` in the local flow when it needs to run together with the other microservices.
- Adjust `order-service` so it queries `inventory-service` before completing an order when that integration is implemented.
- Define environment variables or internal URLs in the orchestrator service so it can locate `inventory-service` inside Docker or Kubernetes.
- Add Kubernetes manifests or Helm chart values to deploy `inventory-service` in Minikube.
- Configure Kubernetes probes using the `GET /health` endpoint.
- Expose the service through a Kubernetes `Service` on port `8000`.
- Include future integration tests and load tests when it is connected to the order flow.

## Current Microservice Limits

- It only looks up products and availability.
- It does not reserve inventory.
- It does not decrease stock.
- It does not update products.
- It does not use a database.
- It does not share state across instances.

## Available Endpoints

- `GET /health`
- `GET /inventory/{product_id}`
- `GET /inventory/{product_id}/availability`

## Author

- Uriel Ortiz
