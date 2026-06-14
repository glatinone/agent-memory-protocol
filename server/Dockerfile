FROM python:3.11-slim

WORKDIR /app

COPY pyproject.toml .
COPY amp_server/ ./amp_server/

RUN pip install --no-cache-dir -e ".[dev]"

EXPOSE 8765

CMD ["uvicorn", "amp_server.main:app", "--host", "0.0.0.0", "--port", "8765"]
