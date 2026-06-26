FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py .
COPY VERSION .
COPY static ./static

EXPOSE 8443

# Runs uvicorn via app.py so DASH_PORT + TLS (self-signed cert) are set up at runtime.
CMD ["python", "app.py"]
