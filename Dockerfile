FROM python:3.11-slim

RUN useradd -m -u 1000 appuser

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src/ src/

RUN pip install --no-cache-dir .

USER appuser

ENTRYPOINT ["griptape-mcp"]
