FROM python:3.10-slim

# Copy pre-compiled static FFmpeg and FFprobe from mwader/static-ffmpeg
COPY --from=mwader/static-ffmpeg:latest /ffmpeg /usr/local/bin/
COPY --from=mwader/static-ffmpeg:latest /ffprobe /usr/local/bin/

# Set working directory
WORKDIR /app

# Install Python dependencies for FastAPI API
RUN pip install --no-cache-dir fastapi uvicorn python-multipart

# Copy the application code
COPY app.py /app/app.py

# Create base inputs folder
RUN mkdir -p /app/inputs

# Run Uvicorn web server
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
