FROM python:3.13-slim
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends tesseract-ocr && rm -rf /var/lib/apt/lists/*
COPY services/api/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt
COPY services ./services
COPY scripts ./scripts
COPY examples ./examples
ENV PYTHONPATH=/app
EXPOSE 8000
CMD ["python", "-m", "uvicorn", "services.api.app.main:app", "--host", "0.0.0.0", "--port", "8000"]
