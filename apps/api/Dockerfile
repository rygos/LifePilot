FROM python:3.12-slim AS build
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*
COPY .git /source/.git
RUN git -C /source rev-parse HEAD > /app/version-commit
COPY apps/api/pyproject.toml ./
COPY apps/api/src ./src
COPY apps/api/migrations ./migrations
COPY apps/api/alembic.ini .
RUN pip wheel --no-cache-dir --wheel-dir /wheels .

FROM python:3.12-slim
WORKDIR /app
COPY --from=build /wheels /wheels
RUN pip install --no-cache-dir /wheels/* && rm -rf /wheels
COPY --from=build /app/version-commit ./version-commit
RUN mkdir -p /app/data
EXPOSE 8000 8002
COPY apps/api/entrypoint.sh ./entrypoint.sh
CMD ["sh", "/app/entrypoint.sh"]
