FROM python:3.11-slim

WORKDIR /app

COPY pyproject.toml ./
RUN pip install --no-cache-dir fastapi "uvicorn[standard]" jinja2 pydantic pyyaml httpx python-multipart

COPY app ./app
COPY config.yaml ./config.yaml
COPY seed ./seed

# SQLite lives on this volume. It is a REBUILDABLE artifact (Premise 11, README):
# "Scan inboxes" rebuilds it from seed/, so an ephemeral filesystem is a non-issue.
# The decision log resets on a cold start on hosts that spin this volume down —
# documented, not hidden.
VOLUME ["/app/data"]
ENV DB_PATH=/app/data/app.db

EXPOSE 8000

# Shell form so $PORT expands: hosts like Render inject the port to bind to.
CMD exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}
