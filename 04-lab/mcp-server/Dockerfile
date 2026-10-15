# Build context: 04-lab/mcp-server   (docker build -t weather-mcp .)
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    HOST=0.0.0.0 \
    PORT=8080

WORKDIR /app

RUN pip install --no-cache-dir uv

# Cài dependency đúng theo uv.lock (tái lập được)
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# Chỉ copy mã nguồn — KHÔNG copy .env (xem .dockerignore). WEATHERAPI_KEY được
# truyền lúc chạy: docker run -e WEATHERAPI_KEY ... hoặc secret của Cloud Run.
COPY weather.py ./

RUN useradd --create-home appuser
USER appuser

# Cloud Run ghi đè PORT; mặc định 8080
EXPOSE 8080

CMD ["/app/.venv/bin/python", "weather.py"]
