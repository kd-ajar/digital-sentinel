FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and simple consumer
COPY infrastructure/docker/ingest/requirements.txt .
COPY src/ingest/kafkaDocker/simple_sse_consumer.py .

RUN pip install --no-cache-dir -r requirements.txt

# Set environment variables
ENV PYTHONUNBUFFERED=1

CMD ["python", "simple_sse_consumer.py"]
