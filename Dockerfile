FROM python:3.10-slim

# Copy pre-compiled static FFmpeg and FFprobe from mwader/static-ffmpeg
COPY --from=mwader/static-ffmpeg:latest /ffmpeg /usr/local/bin/
COPY --from=mwader/static-ffmpeg:latest /ffprobe /usr/local/bin/

# Set working directory
WORKDIR /app

# Copy the stream script
COPY stream.py /app/stream.py

# Create input folder
RUN mkdir -p /app/input

# Run the stream script
CMD ["python", "stream.py"]
