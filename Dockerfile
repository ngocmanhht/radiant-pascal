FROM python:3.10-slim

# Install FFmpeg
RUN apt-get update && \
    apt-get install -y --no-install-recommends ffmpeg && \
    rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy the stream script
COPY stream.py /app/stream.py

# Create input folder
RUN mkdir -p /app/input

# Run the stream script
CMD ["python", "stream.py"]
