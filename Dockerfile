FROM python:3.11-slim-bookworm
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PIP_NO_CACHE_DIR=1 PORT=10000
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg ca-certificates gcc \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install -U pip && pip install -r requirements.txt
COPY . .
RUN useradd -m appuser && chown -R appuser /app && mkdir -p /tmp/thumbs && chown appuser /tmp/thumbs
USER appuser
EXPOSE 10000
CMD ["python", "bot.py"]
