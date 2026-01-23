FROM python:3.11-slim

WORKDIR /app

# Install system dependencies if needed
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY requirements.txt .
RUN pip install --upgrade pip setuptools wheel
RUN pip install -r requirements.txt

# Copy application code
COPY . .

# Use shell form to expand $PORT environment variable
CMD gunicorn --bind 0.0.0.0:$PORT --workers 2 --timeout 120 app:app