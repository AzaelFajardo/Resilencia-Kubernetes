# Base image used to package the service in a container.
FROM python:3.12-slim

# Defines the working directory inside the container.
WORKDIR /app

# Copies dependencies first to take advantage of the Docker layer cache.
COPY requirements.txt .
# Installs the packages required by the order microservice.
RUN pip install --no-cache-dir -r requirements.txt

# Copies the service code into the container.
COPY . .

# Starts the FastAPI application with Uvicorn.
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
