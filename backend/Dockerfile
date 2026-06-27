FROM python:3.11-slim

# Install system dependencies needed by matplotlib, reportlab, and lxml
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libffi-dev \
    libxml2-dev \
    libxslt-dev \
    libpng-dev \
    libfreetype6-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies (cached layer if requirements unchanged)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source
COPY . .

# Create data directories for SQLite DB and generated files
RUN mkdir -p /app/data/samples /app/data/images

EXPOSE 8000

# Run with uvicorn; workers=1 keeps SQLite WAL safe (SQLite handles concurrency internally)
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
