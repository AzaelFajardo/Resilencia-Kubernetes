FROM python:3.12-slim

# Defines the working directory inside the container for running the service.
WORKDIR /app

# Copies dependencies first to take advantage of the Docker layer cache.
COPY requirements.txt .
# Installs only the libraries needed for this microservice.
RUN pip install --no-cache-dir -r requirements.txt

# Copies the service code into the container.
COPY . .

# Exposes the port used by Uvicorn inside the container.
EXPOSE 8000

# Starts FastAPI with Uvicorn listening on all container interfaces.
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
