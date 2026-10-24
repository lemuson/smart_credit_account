FROM ghcr.io/astral-sh/uv:0.11.3 AS uv
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy

WORKDIR /service
COPY --from=uv /uv /uvx /bin/
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project
COPY app app
COPY mock_backend mock_backend
COPY scripts scripts
COPY knowledge_base knowledge_base
COPY docs docs
RUN uv sync --frozen --no-dev

RUN addgroup --system app && adduser --system --ingroup app app \
    && mkdir -p /service/data/chroma && chown -R app:app /service
USER app
ENV PATH="/service/.venv/bin:$PATH"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]

