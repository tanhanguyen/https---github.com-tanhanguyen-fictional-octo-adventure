# Backend image: FastAPI + engine, served by uvicorn (plan 09 §1).
FROM python:3.10-slim

# Faster, quieter, no .pyc clutter in the layer.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Copy only what the package build needs first, so `pip install` is cached across
# source-only edits.
COPY pyproject.toml ./
COPY src ./src
COPY config ./config
RUN pip install --no-cache-dir -e .

# data/ (SQLite DBs + imported CSVs) is a mounted volume in compose; create the mount
# point so the container also runs standalone.
RUN mkdir -p data

EXPOSE 8000

# Access log OFF (noisy); app JSON logs go to stdout for `docker compose logs`.
CMD ["uvicorn", "bot.api.app:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
