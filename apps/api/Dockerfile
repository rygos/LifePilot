FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml .
COPY src ./src
COPY migrations ./migrations
COPY alembic.ini .
RUN pip install --no-cache-dir .
RUN mkdir -p /app/data
EXPOSE 8000 8002
CMD ["sh", "-c", "alembic upgrade head && uvicorn lifepilot.main:app --host 0.0.0.0 --port 8000 & python -c 'from lifepilot.main import run_mcp; run_mcp()'"]
