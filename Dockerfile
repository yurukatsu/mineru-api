# Official UV image with Python 3.11 based on Debian Bookworm
FROM ghcr.io/astral-sh/uv:python3.11-bookworm

# Set environment variables to non-interactive to avoid prompts during installation
ENV DEBIAN_FRONTEND=noninteractive

# Update the package list and install necessary packages
RUN apt-get update && \
    apt-get install -y \
    libgl1 \
    libreoffice \
    fonts-noto-cjk \
    fonts-wqy-zenhei \
    fonts-wqy-microhei \
    fontconfig \
    libglib2.0-0 \
    libxrender1 \
    libsm6 \
    libxext6 \
    poppler-utils \
    && rm -rf /var/lib/apt/lists/*

# Install Python packages
WORKDIR /app
COPY pyproject.toml ./
RUN uv sync

COPY ./api /app/api

RUN wget https://github.com/opendatalab/MinerU/raw/master/scripts/download_models_hf.py -O download_models.py && \
    uv run download_models.py

EXPOSE 8000
