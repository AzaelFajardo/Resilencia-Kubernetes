# User Service - Integration Notes

## Objective
Reference document for the future integration of `user-service` with the rest of the microservices.
It does not affect the current behavior of the service.

---

## Pending External Changes

- Update `docker-compose.yml` to include `user-service` in the local flow.
- Adjust `order-service` or other services to validate users before processing operations.
- Define environment variables or internal URLs in the orchestrator (Docker / Kubernetes).
- Integrate `user-service` with services that require authentication or user validation.
- Add Kubernetes manifests or Helm values for deployment in Minikube.
- Configure Kubernetes probes using `GET /health`.
- Expose the service through a `Service` on port `8000`.
- Implement integration tests.
- Implement load tests.

---

## Current Microservice Limits

- It only looks up users by ID.
- It only validates whether a user exists and is active.
- It does not create users.
- It does not update users.
- It does not delete users.
- It does not use a database (in-memory data).
- It does not handle real authentication (tokens, JWT, etc.).
- It does not share state across instances.

---

## Available Endpoints

- `GET /health`
- `GET /users/{user_id}`
- `GET /users/{user_id}/validate`

## Author

- Uriel Ortiz
