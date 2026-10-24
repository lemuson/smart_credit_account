FROM ghcr.io/astral-sh/uv:0.9.13 AS uv

FROM python:3.13-slim-bookworm AS dependencies
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

FROM python:3.13-slim-bookworm AS runtime
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
RUN groupadd --gid 10001 credit && useradd --uid 10001 --gid credit --no-create-home credit
COPY --from=dependencies /app/.venv /app/.venv
COPY --chown=credit:credit app ./app
COPY --chown=credit:credit migrations ./migrations
COPY --chown=credit:credit main.py alembic.ini ./
USER credit
EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=3s --start-period=15s --retries=5 \
    CMD ["python", "-c", "from urllib.request import urlopen; urlopen('http://127.0.0.1:8000/health', timeout=2).read()"]
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]

FROM dependencies AS test
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
RUN uv sync --frozen --no-install-project
COPY app ./app
COPY migrations ./migrations
COPY tests ./tests
COPY examples ./examples
COPY main.py alembic.ini ./
CMD ["sh", "-c", "pytest -q && python -m examples.http_smoke"]

FROM runtime AS production
