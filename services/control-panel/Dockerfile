# control-panel: FastAPI backend + static SPA, monitoring and administering the stack.
# Build context: this service's own directory (services/control-panel).
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
