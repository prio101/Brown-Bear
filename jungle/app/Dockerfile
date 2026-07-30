# syntax=docker/dockerfile:1

FROM python:3.12-slim AS builder
ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1
WORKDIR /build
COPY pyproject.toml ./
COPY brownbear ./brownbear
RUN pip install --prefix=/install .

FROM python:3.12-slim AS runtime
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1
RUN useradd --create-home --uid 10001 brownbear
COPY --from=builder /install /usr/local
WORKDIR /app
COPY alembic.ini ./
COPY alembic ./alembic
COPY brownbear ./brownbear
USER brownbear
EXPOSE 8080
CMD ["uvicorn", "brownbear.main:app", "--host", "0.0.0.0", "--port", "8080"]
