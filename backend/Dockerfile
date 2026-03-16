FROM python:3.12-slim

# Install system dependencies:
# - postgresql-client: provides pg_isready for the entrypoint healthcheck loop
# - curl: useful for container healthchecks and debugging
RUN apt-get update && apt-get install -y --no-install-recommends \
    postgresql-client \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy dependency files first so Docker can cache this layer.
# Dependencies only reinstall when pyproject.toml changes, not on every code change.
COPY pyproject.toml .

# Install uv then use it to install dependencies from pyproject.toml.
# uv is significantly faster than pip for this.
RUN pip install uv --no-cache-dir \
    && uv pip install --system --no-cache -e .

# Copy the rest of the application code
COPY . .

# Make the entrypoint executable
RUN chmod +x docker/entrypoint.sh

EXPOSE 8000

ENTRYPOINT ["docker/entrypoint.sh"]
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
