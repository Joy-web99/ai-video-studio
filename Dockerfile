FROM python:3.11-slim

# Environment Variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DEBIAN_FRONTEND=noninteractive \
    PIP_NO_CACHE_DIR=1 \
    PORT=8000 \
    STUDIO_WORKSPACE=/app/workspace

# Install system dependencies: FFmpeg for video, Fonts for Bengali/Hindi text
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

# Set working directory
WORKDIR /app

# Install Python dependencies
COPY requirements.txt /app/requirements.txt
RUN pip install --upgrade pip && pip install --no-cache-dir -r /app/requirements.txt

# Copy all project files
COPY . /app

# Create workspace directories for outputs and uploads
RUN mkdir -p \
    /app/workspace/projects \
    /app/workspace/uploads \
    /app/workspace/outputs \
    /app/workspace/temp \
    /app/workspace/cache \
    /app/static \
    && chmod -R 777 /app/workspace

# Expose port
EXPOSE 8000

# Healthcheck to keep the server alive
HEALTHCHECK --interval=30s --timeout=10s --start-period=25s --retries=3 \
    CMD curl -f http://localhost:${PORT:-8000}/api/health || exit 1

# Start the FastAPI application
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --timeout-keep-alive 120"]
