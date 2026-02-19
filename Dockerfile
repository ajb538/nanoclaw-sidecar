FROM python:3.13-slim

WORKDIR /app

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Copy dependency files first (layer cache)
COPY pyproject.toml uv.lock ./

# Install production dependencies only
RUN uv sync --no-dev --frozen

# Copy application source
COPY src/ ./src/

EXPOSE 5000

CMD ["uv", "run", "uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "5000"]
