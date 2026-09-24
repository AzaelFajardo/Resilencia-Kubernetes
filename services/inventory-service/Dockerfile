# Base image used to package the service in a container.
# Build context: repo root's services/ directory (so the shared orchestrator
# module is copied alongside the service):
#   docker build -t inventory-service:latest -f services/inventory-service/Dockerfile services
FROM python:3.12-slim

# Defines the working directory inside the container.
WORKDIR /app

# Copies the dependency file first to make better use of the Docker cache.
COPY inventory-service/requirements.txt .
# Installs only what is required to run this microservice.
RUN pip install --no-cache-dir -r requirements.txt

# Copies the service code and the shared orchestrator module into the container.
COPY inventory-service/ ./
COPY shared/ /app/shared/

# Exposes the internal port expected by FastAPI and Uvicorn.
EXPOSE 8000

# Starts the application listening on all container interfaces.
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]