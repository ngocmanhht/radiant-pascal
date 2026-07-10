# Multi-Stream RTSP Server with FastAPI and Swagger (Docker)

This project runs a containerized live RTSP stream manager. It allows you to:
1. **Host Multiple Streams**: Create folder paths under `inputs/` (e.g., `inputs/live`, `inputs/live1`, `inputs/my-stream`). Each folder will automatically stream to `rtsp://<SERVER_IP>:8554/<folder_name>` in an infinite loop.
2. **Manage Videos via REST API**: Upload, replace, and delete `.mp4` video files in any stream folder dynamically using a Swagger Web UI or direct API requests.

---

## Ports Exposed

- **`8554` (RTSP)**: The port used to pull/view live streams.
- **`8000` (FastAPI Web API)**: The port used to manage files and view documentation.

---

## Quick Start

### 1. Run the Server
Build and start the containers using Docker Compose:
```bash
docker compose up --build -d
```

### 2. Open the Swagger API Documentation
Open your web browser and navigate to:
👉 **`http://<SERVER_IP>:8000/docs`**

Here, you can interactively test the endpoints:
- `GET /streams`: View all active streams, files inside them, and RTSP stream play URLs.
- `POST /streams/create`: Create a new stream folder (e.g., `live2`).
- `POST /streams/{stream_name}/upload`: Upload or replace a `.mp4` file for a stream.
- `DELETE /streams/{stream_name}/files/{filename}`: Delete a video file.
- `DELETE /streams/{stream_name}`: Delete a stream and all its files.

---

## How It Works (Multi-Stream Folder Mapping)

The application monitors the `inputs/` directory on your server. Any folder inside it is treated as an active RTSP path:

- `./inputs/live/` ➡️ streams to ➡️ `rtsp://<SERVER_IP>:8554/live`
- `./inputs/live1/` ➡️ streams to ➡️ `rtsp://<SERVER_IP>:8554/live1`
- `./inputs/custom/` ➡️ streams to ➡️ `rtsp://<SERVER_IP>:8554/custom`

### Rules:
- **Starting Stream**: Once you add at least one `.mp4` file to a folder, the streaming process begins automatically.
- **Dynamic Updates**: If you add, delete, or upload a video file via the API, the system automatically regenerates the playlist and restarts that specific stream without affecting other streams.
- **Transcoding**: By default, videos are scaled/padded to `1280x720` at `30fps` on-the-fly (`TRANSCODE=true`), allowing you to mix videos of different formats and resolutions seamlessly.

---

## API Usage Examples (cURL)

### 1. List Streams and Files
```bash
curl -X GET "http://<SERVER_IP>:8000/streams"
```

### 2. Create a New Stream Path
```bash
curl -X POST "http://<SERVER_IP>:8000/streams/create?stream_name=live2"
```

### 3. Upload/Replace an MP4 Video File
```bash
curl -X POST "http://<SERVER_IP>:8000/streams/live/upload" \
  -H "accept: application/json" \
  -H "Content-Type: multipart/form-data" \
  -F "file=@your_video.mp4;type=video/mp4"
```

### 4. Delete a Video File
```bash
curl -X DELETE "http://<SERVER_IP>:8000/streams/live/files/your_video.mp4"
```
