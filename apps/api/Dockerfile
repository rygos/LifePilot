FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml .
COPY src ./src
COPY migrations ./migrations
COPY alembic.ini .
RUN pip install --no-cache-dir .
RUN mkdir -p /app/data
EXPOSE 8000 8002
COPY entrypoint.sh ./entrypoint.sh
CMD ["sh", "/app/entrypoint.sh"]
