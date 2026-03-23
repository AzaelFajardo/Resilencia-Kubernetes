FROM python:3.12-slim

# Define el directorio de trabajo dentro del contenedor para ejecutar el servicio.
WORKDIR /app

# Copia primero las dependencias para aprovechar la cache de capas de Docker.
COPY requirements.txt .
# Instala solo las librerias necesarias para este microservicio.
RUN pip install --no-cache-dir -r requirements.txt

# Copia el codigo del servicio al contenedor.
COPY . .

# Expone el puerto usado por Uvicorn dentro del contenedor.
EXPOSE 8000

# Inicia FastAPI con Uvicorn escuchando en todas las interfaces del contenedor.
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
