FROM python:3.12-slim AS build
WORKDIR /app
COPY pyproject.toml .
COPY src ./src
COPY migrations ./migrations
COPY alembic.ini .
RUN python -c 'import json, urllib.request; request = urllib.request.Request("https://api.github.com/repos/rygos/LifePilot/commits/main", headers={"Accept": "application/vnd.github+json", "User-Agent": "LifePilot-build"}); response = urllib.request.urlopen(request, timeout=8); print(json.load(response)["sha"])' > /app/version-commit || echo unknown > /app/version-commit
RUN pip wheel --no-cache-dir --wheel-dir /wheels .

FROM python:3.12-slim
WORKDIR /app
COPY --from=build /wheels /wheels
RUN pip install --no-cache-dir /wheels/* && rm -rf /wheels
COPY --from=build /app/version-commit ./version-commit
RUN mkdir -p /app/data
EXPOSE 8000 8002
COPY entrypoint.sh ./entrypoint.sh
CMD ["sh", "/app/entrypoint.sh"]
