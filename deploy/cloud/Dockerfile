FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml ./
COPY app_catch ./app_catch
RUN pip install --no-cache-dir '.[cloud]' && useradd --uid 10001 --create-home appcatch && mkdir -p /tmp/model-cache && chown 10001:10001 /tmp/model-cache
USER 10001
EXPOSE 8080
CMD ["uvicorn", "app_catch.cloud:create_app", "--factory", "--host", "0.0.0.0", "--port", "8080", "--workers", "1"]
