# Base image used to package the service in a container.
# Build context: repo root's services/ directory (so the shared orchestrator
# module is copied alongside the service):
#   docker build -t order-service:latest -f services/order-service/Dockerfile services
FROM python:3.12-slim

# Defines the working directory inside the container.
WORKDIR /app

# Copies dependencies first to take advantage of the Docker layer cache.
COPY order-service/requirements.txt .
# Installs the packages required by the order microservice.
RUN pip install --no-cache-dir -r requirements.txt

# Copies the service code and the shared orchestrator module into the container.
COPY order-service/ ./
COPY shared/ /app/shared/

# Starts the FastAPI application with Uvicorn.
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]