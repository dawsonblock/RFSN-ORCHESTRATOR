FROM python:3.11-slim

LABEL maintainer="RFSN Team"
LABEL version="8.2"
LABEL description="RFSN GenAI Orchestrator - Production Streaming Build"

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    ffmpeg \
    libasound2-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for caching
COPY Python/requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY Python/ ./Python/
COPY config.json .
COPY Dashboard/ ./Dashboard/

# Create directories
RUN mkdir -p Models/piper memory

# Expose port
EXPOSE 8000

# Environment variables
ENV PYTHONUNBUFFERED=1
ENV RFSN_ENV=production

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/api/status || exit 1

# Run server
CMD ["python", "Python/orchestrator.py"]
