FROM python:3.12-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1

COPY services/data-seeder/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

COPY scripts /app/scripts

CMD ["python", "scripts/seed_database.py"]
