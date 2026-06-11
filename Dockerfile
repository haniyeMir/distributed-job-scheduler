FROM ubuntu:latest
LABEL authors="ASUS"

ENTRYPOINT ["top", "-b"]

FROM python:3.11-slim

# Set working directory inside container
WORKDIR /app

# Install dependencies first (cached layer — only rebuilds if requirements.txt changes)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Expose Flask port
EXPOSE 5000

# Default command — overridden per service in docker-compose.yml
CMD ["python", "run.py"]