# Python & FFmpeg Live RTSP Streaming Server (Docker)

This project runs a live RTSP stream that reads `.mp4` files from the `input/` directory and streams them continuously in a loop. It is fully containerized using Docker and Docker Compose.

It includes:
1. **MediaMTX**: A high-performance media server that accepts the RTSP stream and republishes it for clients (supporting RTSP, RTMP, WebRTC, and HLS).
2. **Python Streamer**: A service that monitors the `input/` folder, creates a playlist, and streams videos via FFmpeg.

---

## Quick Start

### 1. Requirements
Ensure you have [Docker](https://www.docker.com/) and [Docker Compose](https://docs.docker.com/compose/) installed on your machine.

### 2. Put Video Files in `input/`
Put one or more `.mp4` video files into the `input/` folder.

### 3. Run the Server
Start the containers using Docker Compose:
```bash
docker compose up --build -d
```

---

## Streaming and Playback URLs

Once the server is running, the live stream is accessible at the following URLs:

### 📺 RTSP (Standard Players - VLC, ffmpeg, security cams systems)
* **URL**: `rtsp://localhost:8554/live`
* **In VLC**: Go to `File -> Open Network...` and enter the URL above.

### 🌐 WebRTC (Ultra Low Latency Browser Playback)
* **URL**: [http://localhost:8889/live](http://localhost:8889/live)
* Open this link in any browser to watch the stream with sub-second latency!

### 📱 HLS (Universal Browser / Mobile Playback)
* **URL**: `http://localhost:8888/live/index.m3u8`
* Playable in Safari or any HLS-capable player.

---

## Configuration Options

You can customize the streaming behavior by editing the environment variables in `docker-compose.yml`:

| Environment Variable | Default Value | Description |
| :--- | :--- | :--- |
| `TRANSCODE` | `true` | `true`: Scales and pads all videos to standard 720p (1280x720) so they can be concatenated seamlessly even if resolutions differ. <br>`false`: Direct copies codec data (0% CPU, but all files must have identical resolutions/codecs). |
| `VIDEO_BITRATE` | `2M` | Video stream bitrate (e.g. `2M` for 2Mbps). |
| `FPS` | `30` | Frame rate of the live stream. |

---

## Features

- **Dynamic Playlist Updates**: If you add, delete, or rename files in the `input/` folder, the Python script will automatically detect the changes, update the playlist, and restart the stream.
- **Continuous Loop**: The playlist loops indefinitely.
- **Robust Scaling**: When `TRANSCODE=true`, mixed portrait (vertical) and landscape (horizontal) videos are scaled and padded with black bars to maintain the aspect ratio without distorting.
