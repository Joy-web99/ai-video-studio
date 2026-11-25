FROM python:3.11-slim

# Environment Variables (Forcing only binary wheels to save RAM)
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DEBIAN_FRONTEND=noninteractive \
    PIP_NO_CACHE_DIR=1 \
    PORT=8000 \
    STUDIO_WORKSPACE=/app/workspace \
    PIP_ONLY_BINARY=:all: \
    PIP_PREFER_BINARY=1

# Install system dependencies: FFmpeg and Bengali Fonts
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libgl1 \
    libglib2.0-0 \
    libsndfile1 \
    curl \
    ca-certificates \
    fontconfig \
    fonts-noto-core \
    fonts-noto-extra \
    fonts-lohit-beng-bengali \
    fonts-dejavu-core \
    && fc-cache -fv \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 1. Upgrade build tools first (Crucial for scipy to understand it should use wheels)
RUN pip install --upgrade pip setuptools wheel

# 2. Force install scipy and numpy as pre-built wheels (No compilation at all)
RUN pip install --no-cache-dir --only-binary=scipy,numpy scipy==1.15.1 numpy==2.2.0

# 3. Install the rest of the requirements
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY . /app

# Create workspace directories
RUN mkdir -p \
    /app/workspace/projects \
    /app/workspace/uploads \
    /app/workspace/outputs \
    /app/workspace/temp \
    /app/workspace/cache \
    /app/static \
    && chmod -R 777 /app/workspace

EXPOSE 8000

# Healthcheck
HEALTHCHECK --interval=30s --timeout=10s --start-period=25s --retries=3 \
    CMD curl -f http://localhost:${PORT:-8000}/api/health || exit 1

# Start the application
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --timeout-keep-alive 120"]
