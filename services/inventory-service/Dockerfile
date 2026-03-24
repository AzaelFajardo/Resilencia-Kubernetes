FROM python:3.12-slim

# Defines the working directory inside the container.
WORKDIR /app

# Copies the dependency file first to make better use of the Docker cache.
COPY requirements.txt .
# Installs only what is required to run this microservice.
RUN pip install --no-cache-dir -r requirements.txt

# Copies the service code into the container.
COPY . .

# Exposes the internal port expected by FastAPI and Uvicorn.
EXPOSE 8000

# Starts the application listening on all container interfaces.
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
