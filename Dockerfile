FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PYTHONUNBUFFERED=1
EXPOSE 3004

CMD ["python", "-m", "uvicorn", "app:app", "--host", "0.0.0.0", "--port", "3004"]
