# Imagen con Python + Chromium ya instalados
FROM mcr.microsoft.com/playwright/python:v1.47.0-jammy

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app.py home.html watch.html style.css fx.js ./

ENV PYTHONUNBUFFERED=1
CMD ["python", "app.py"]
