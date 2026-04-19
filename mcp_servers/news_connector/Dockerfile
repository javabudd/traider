# syntax=docker/dockerfile:1.7
#
# Build context is this directory (mcp_servers/news_connector/).
# From ../../docker-compose.yml: `build: { context: ./mcp_servers/news_connector }`.

FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Install Python deps first so code edits don't invalidate this layer.
# Stub the package tree so the hatchling editable install has a path to
# link against; the real source is copied in below.
COPY pyproject.toml /app/
RUN mkdir -p src/news_connector \
    && touch src/news_connector/__init__.py \
    && pip install --no-cache-dir -e .

COPY src /app/src

EXPOSE 8770

ENTRYPOINT ["news-connector"]
CMD ["--transport", "streamable-http", "--host", "0.0.0.0", "--port", "8770"]
