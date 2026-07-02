FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY rendering_app ./rendering_app
COPY Analysis ./Analysis

EXPOSE 5000
CMD ["sh", "-c", "exec gunicorn --bind 0.0.0.0:5000 --workers ${RENDERER_WORKERS:-2} --timeout ${RENDERER_TIMEOUT_SECONDS:-210} 'rendering_app.app:create_app()'"]
