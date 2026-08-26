# Production multi-stage Dockerfile for DataPulse-India
FROM python:3.12-slim as builder

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml .
COPY README.md .
COPY datapulse ./datapulse

RUN pip install --no-cache-dir .

FROM python:3.12-slim as runner

WORKDIR /app

COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

COPY datapulse ./datapulse
COPY config ./config
COPY dashboard ./dashboard

ENV DATAPULSE_ENVIRONMENT=production
ENV PYTHONUNBUFFERED=1

ENTRYPOINT ["python", "-m", "datapulse.cli"]
CMD ["run", "--source", "mandi_prices"]
