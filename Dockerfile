# Cloud Run image. Untested until the GCP project exists (see the deployment notes in Makefile).
# Layout mirrors the repo so paths in app/config.py and app/main.py resolve:
#   /app/backend/app, /app/seed, /app/frontend/dist
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app/backend

COPY backend/requirements.txt /app/backend/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/app /app/backend/app
COPY seed /app/seed
COPY frontend /app/frontend

# Cloud Run sets PORT. Defaults: in-memory store and mock Gemini unless env overrides them.
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8080}"]
