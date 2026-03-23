FROM python:3.12-slim

# Define el directorio de trabajo dentro del contenedor.
WORKDIR /app

# Copia primero el archivo de dependencias para aprovechar mejor la cache de Docker.
COPY requirements.txt .
# Instala solo lo necesario para ejecutar este microservicio.
RUN pip install --no-cache-dir -r requirements.txt

# Copia el codigo del servicio al contenedor.
COPY . .

# Expone el puerto interno esperado por FastAPI/Uvicorn.
EXPOSE 8000

# Inicia la aplicacion escuchando en todas las interfaces del contenedor.
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
