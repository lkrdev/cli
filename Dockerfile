FROM python:3.12-slim
RUN apt-get update && apt-get install -y chromium-driver
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Set working directory and create necessary directories with proper permissions
WORKDIR /app

# Copy dependency files
COPY pyproject.toml uv.lock README.md LICENSE ./
COPY lkr ./lkr
ENV UV_PROJECT_ENVIRONMENT="/usr/local/"
RUN uv sync --frozen --no-dev --no-editable

CMD []