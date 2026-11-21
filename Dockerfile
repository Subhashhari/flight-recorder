FROM node:lts AS ui
WORKDIR /ui
COPY ui/package*.json ./
RUN npm ci
COPY ui/ ./
RUN npm run build

FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1
RUN pip install --no-cache-dir uv
WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project
COPY src ./src
COPY config ./config
COPY data ./data
COPY docs ./docs
RUN uv sync --frozen --no-dev
COPY --from=ui /ui/dist ./ui_dist
ENV PATH="/app/.venv/bin:$PATH" UI_DIST=/app/ui_dist FLIGHTREC_ROOT=/app
EXPOSE 8000
CMD ["uvicorn", "flightrec.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
