# ==============================================================================
# AI Video Production Studio - Production Dockerfile (Part A1)
# Supports: FastAPI + Asyncio, FFmpeg Cinema Engine, DSP Beat-Sync,
#           yt-dlp Reference Analyzer, Edge-TTS & Native Bangla Subtitles
# Compatible with: Render.com, Hugging Face Spaces, Railway & Local Docker
# ==============================================================================

FROM python:3.11-slim

# Prevent Python from writing .pyc files and enable real-time unbuffered logs
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DEBIAN_FRONTEND=noninteractive \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PORT=8000 \
    STUDIO_WORKSPACE=/app/workspace

# Install core system media engines, audio/image libs, and Bangla + English fonts
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libsm6 \
    libxext6 \
    libgl1 \
    libglib2.0-0 \
    libsndfile1 \
    curl \
    ca-certificates \
    fontconfig \
    fonts-noto-core \
    fonts-lohit-bengali \
    fonts-dejavu-core \
    && fc-cache -fv \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Set main application directory
WORKDIR /app

# Install Python dependencies first (optimizes Docker layer caching)
COPY requirements.txt /app/requirements.txt
RUN pip install --upgrade pip && \
    pip install --no-cache-dir -r /app/requirements.txt

# Copy entire project source code
COPY . /app

# Create runtime directories for projects, uploads, generated videos, and cache
# Full write permissions ensure smooth execution on both Render and HF Spaces
RUN mkdir -p \
    /app/workspace/projects \
    /app/workspace/uploads \
    /app/workspace/outputs \
    /app/workspace/temp \
    /app/workspace/cache \
    /app/workspace/providers \
    && chmod -R 777 /app/workspace

# Expose default container port
EXPOSE 8000

# Healthcheck to monitor backend stability
HEALTHCHECK --interval=30s --timeout=10s --start-period=20s --retries=3 \
    CMD curl -f http://localhost:${PORT:-8000}/api/health || exit 1

# Launch FastAPI Uvicorn server dynamically binding to cloud platform $PORT
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --timeout-keep-alive 120 --log-level info"]

