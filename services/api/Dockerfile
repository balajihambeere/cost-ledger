FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev gcc \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
COPY packages ./packages
RUN pip install --no-cache-dir -e .

COPY services ./services
COPY simulation ./simulation
COPY database ./database

ENV PYTHONPATH=/app/packages:/app/services:/app/simulation
ENV PYTHONUNBUFFERED=1

EXPOSE 8000

CMD ["uvicorn", "api.app.main:app", "--host", "0.0.0.0", "--port", "8000"]
