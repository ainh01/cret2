FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PYTHONUNBUFFERED=1 \
    IMAGE_DIR=/app/data/images \
    SETTINGS_ENV_PATH=/app/data/settings.env
VOLUME ["/app/data"]
EXPOSE 3004

CMD ["python", "-m", "uvicorn", "app:app", "--host", "0.0.0.0", "--port", "3004"]
