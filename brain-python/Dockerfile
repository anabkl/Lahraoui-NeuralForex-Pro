# brain-python/Dockerfile
FROM python:3.11-slim

LABEL maintainer="Anas Lahraoui <lahraoui.forex@example.com>"
LABEL description="NeuralForex-Pro Brain Service – FastAPI AI prediction engine"

WORKDIR /app

# Install Python dependencies first (layer cache optimisation)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source
COPY app/ ./app/

# Create weights directory
RUN mkdir -p /app/weights

# Expose the FastAPI port
EXPOSE 8000

# Run with uvicorn
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
