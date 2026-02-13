FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --upgrade pip setuptools wheel
RUN pip install -r requirements.txt

# Copy application code
COPY . .

# Expose port (documentation only, Railway overrides this)
EXPOSE 8080

# Run with shell to properly expand environment variables
CMD sh -c "gunicorn --bind 0.0.0.0:${PORT:-8080} --workers 2 --timeout 120 app:app"