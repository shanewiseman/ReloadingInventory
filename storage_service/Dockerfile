FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    COVERAGE_FILE=/tmp/.coverage \
    PYTEST_ADDOPTS="-o cache_dir=/tmp/pytest_cache"
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY storage_service ./storage_service
COPY rendering_app ./rendering_app
COPY reloading_mcp ./reloading_mcp
COPY migrations ./migrations
COPY alembic.ini .
COPY tests ./tests
COPY pytest.ini .

EXPOSE 5001
CMD ["sh", "-c", "flask --app storage_service.app db upgrade && gunicorn --bind 0.0.0.0:5001 --workers 2 'storage_service.app:create_app()'"]
