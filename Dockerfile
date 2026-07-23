FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY pyproject.toml README.md ./
COPY app ./app

RUN pip install --no-cache-dir . \
    && python -m playwright install --with-deps chromium

RUN mkdir -p /app/data /app/reports /app/diagnostics

CMD ["python", "-m", "app.main", "--help"]
