FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    GOOGLE_SERVICE_ACCOUNT_FILE=/secrets/service_account.json

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY server.py .

RUN useradd --create-home --uid 10001 mcp
USER mcp

# MCP-клиент общается с сервером через stdin/stdout:
# docker run -i --rm -v <ключ>:/secrets/service_account.json:ro google-sheets-mcp
ENTRYPOINT ["python", "server.py"]
