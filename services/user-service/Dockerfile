# Base image used to package the service in a container.
# Build context: repo root's services/ directory (so the shared orchestrator
# module is copied alongside the service):
#   docker build -t user-service:latest -f services/user-service/Dockerfile services
FROM python:3.12-slim

# Defines the working directory inside the container for running the service.
WORKDIR /app

# Copies dependencies first to take advantage of the Docker layer cache.
COPY user-service/requirements.txt .
# Installs only the libraries needed for this microservice.
RUN pip install --no-cache-dir -r requirements.txt

# Copies the service code and the shared orchestrator module into the container.
COPY user-service/ ./
COPY shared/ /app/shared/

# Exposes the port used by Uvicorn inside the container.
EXPOSE 8000

# Starts FastAPI with Uvicorn listening on all container interfaces.
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]