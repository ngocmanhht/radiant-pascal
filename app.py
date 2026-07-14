import os
import sys
import shutil
import asyncio
import logging
import subprocess
from pathlib import Path
from typing import Dict, List
from contextlib import asynccontextmanager
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import JSONResponse

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("stream-manager")

INPUTS_DIR = Path(os.getenv("INPUTS_DIR", "/app/inputs"))
TRANSCODE = os.getenv("TRANSCODE", "true").lower() == "true"
VIDEO_BITRATE = os.getenv("VIDEO_BITRATE", "2M")
FPS = os.getenv("FPS", "30")
RTSP_SERVER_URL = os.getenv("RTSP_SERVER_URL", "rtsp://mediamtx:8554")

# Dictionary to hold active stream processes:
# { stream_name: { "process": Popen, "files": List[str], "playlist_path": Path } }
active_streams: Dict[str, dict] = {}

def generate_playlist(playlist_path: Path, files: List[str]) -> bool:
    """Generates the concat playlist file for FFmpeg."""
    try:
        with open(playlist_path, "w") as f:
            for file_path in files:
                escaped_path = file_path.replace("'", "'\\''")
                f.write(f"file '{escaped_path}'\n")
        logger.info(f"Generated playlist at {playlist_path} with {len(files)} files.")
        return True
    except Exception as e:
        logger.error(f"Failed to generate playlist: {e}")
        return False

def build_ffmpeg_cmd(playlist_path: Path, rtsp_url: str) -> List[str]:
    """Builds the FFmpeg command based on configuration."""
    cmd = [
        "ffmpeg",
        "-re",                          # Read input at native frame rate (realtime)
        "-probesize", "32",             # Minimize input probing size for instant startup
        "-analyzeduration", "0",        # Skip stream analysis duration for instant startup
        "-f", "concat",                 # Use concat demuxer
        "-safe", "0",                   # Allow absolute/unsafe paths
        "-stream_loop", "-1",           # Loop the stream indefinitely
        "-i", str(playlist_path)
    ]

    if TRANSCODE:
        cmd.extend([
            "-c:v", "libx264",
            "-preset", "ultrafast",      # Fastest encoding preset (minimum CPU latency)
            "-tune", "zerolatency",      # Optimize for real-time low-latency streaming
            "-bf", "0",                  # Disable B-frames to prevent lag/stutter in RTSP
            "-pix_fmt", "yuv420p",
            "-r", FPS,
            "-vsync", "cfr",             # Force Constant Frame Rate to prevent stream stuttering
            "-g", str(int(FPS) * 2),     # Keyframe interval (GOP)
            "-b:v", VIDEO_BITRATE,
            "-maxrate", VIDEO_BITRATE,
            "-bufsize", "4M",            # Smooth bitrate spikes to prevent congestion
            # Scale and pad to standard 1280x720 to support mixing different resolutions safely
            "-vf", "scale=1280:720:force_original_aspect_ratio=decrease,pad=1280:720:(ow-iw)/2:(oh-ih)/2,format=yuv420p",
            "-c:a", "aac",
            "-ar", "44100",
            "-b:a", "128k",
            "-ac", "2"
        ])
    else:
        cmd.extend([
            "-c", "copy"
        ])

    cmd.extend([
        "-f", "rtsp",
        "-rtsp_transport", "tcp",
        "-pkt_size", "1300",             # Prevent RTP packets from exceeding MTU limits (fixes remuxing overhead in mediamtx)
        rtsp_url
    ])

    return cmd

def stop_stream(stream_name: str):
    """Gracefully terminates the FFmpeg process for a stream."""
    if stream_name in active_streams:
        stream = active_streams[stream_name]
        process = stream["process"]
        logger.info(f"Stopping stream '{stream_name}'...")
        process.terminate()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            logger.warning(f"FFmpeg process for '{stream_name}' did not exit. Killing it...")
            process.kill()
            process.wait()
        
        # Clean up playlist file
        playlist_path = stream.get("playlist_path")
        if playlist_path and playlist_path.exists():
            try:
                playlist_path.unlink()
            except OSError:
                pass
        
        active_streams.pop(stream_name, None)

async def monitor_streams_loop():
    """Background task to watch directories, handle changes, and maintain streams."""
    logger.info("Starting background stream monitor...")
    while True:
        try:
            INPUTS_DIR.mkdir(parents=True, exist_ok=True)
            
            # Find all subdirectories
            subdirs = [d for d in INPUTS_DIR.iterdir() if d.is_dir()]
            subdir_names = {d.name for d in subdirs}
            
            # 1. Clean up inactive streams (folders deleted)
            for stream_name in list(active_streams.keys()):
                if stream_name not in subdir_names:
                    logger.info(f"Folder for stream '{stream_name}' was removed. Stopping stream...")
                    stop_stream(stream_name)

            # 2. Check and stream active folders
            for subdir in subdirs:
                stream_name = subdir.name
                if stream_name.startswith('.'):
                    continue  # Ignore hidden folders
                
                mp4_files = sorted([
                    str(f.resolve()) for f in subdir.iterdir()
                    if f.is_file() and f.suffix.lower() == '.mp4'
                ])

                # Stop stream if empty
                if not mp4_files:
                    if stream_name in active_streams:
                        logger.warning(f"No MP4 files found in stream folder '{stream_name}'. Stopping stream...")
                        stop_stream(stream_name)
                    continue

                current_stream = active_streams.get(stream_name)
                files_changed = current_stream is None or current_stream["files"] != mp4_files

                if files_changed:
                    logger.info(f"Stream '{stream_name}': files changed or new stream. Initiating stream...")
                    stop_stream(stream_name)
                    
                    playlist_path = subdir / "playlist.txt"
                    if generate_playlist(playlist_path, mp4_files):
                        rtsp_url = f"{RTSP_SERVER_URL}/{stream_name}"
                        cmd = build_ffmpeg_cmd(playlist_path, rtsp_url)
                        logger.info(f"Starting FFmpeg for '{stream_name}' -> {rtsp_url}")
                        try:
                            # FFmpeg will inherit python stdout/stderr and output directly to container logs
                            process = subprocess.Popen(cmd)
                            active_streams[stream_name] = {
                                "process": process,
                                "files": mp4_files,
                                "playlist_path": playlist_path
                            }
                        except Exception as e:
                            logger.error(f"Failed to spawn FFmpeg process for '{stream_name}': {e}")
                    else:
                        logger.error(f"Could not generate playlist for stream '{stream_name}'")
                else:
                    # Files didn't change, verify FFmpeg process status
                    process = current_stream["process"]
                    if process.poll() is not None:
                        logger.error(f"FFmpeg process for '{stream_name}' crashed (code {process.returncode}). Restarting...")
                        rtsp_url = f"{RTSP_SERVER_URL}/{stream_name}"
                        playlist_path = current_stream["playlist_path"]
                        cmd = build_ffmpeg_cmd(playlist_path, rtsp_url)
                        try:
                            process = subprocess.Popen(cmd)
                            active_streams[stream_name]["process"] = process
                        except Exception as e:
                            logger.error(f"Failed to restart FFmpeg process for '{stream_name}': {e}")

        except Exception as e:
            logger.error(f"Error in stream monitor loop: {e}", exc_info=True)
            
        await asyncio.sleep(5)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Start background task on startup
    monitor_task = asyncio.create_task(monitor_streams_loop())
    yield
    # Cleanup task and terminate streams on shutdown
    monitor_task.cancel()
    try:
        await monitor_task
    except asyncio.CancelledError:
        pass
    
    for stream_name in list(active_streams.keys()):
        stop_stream(stream_name)
    logger.info("Application shutdown completed.")

app = FastAPI(
    title="Multi-Stream RTSP Manager",
    description="Manage multiple loop-streamed RTSP feeds from folders via dynamic REST API.",
    version="1.0.0",
    lifespan=lifespan
)

@app.get("/streams")
def list_streams():
    """List all streams, their active state, containing video files, and play URLs."""
    result = {}
    if INPUTS_DIR.exists():
        for d in INPUTS_DIR.iterdir():
            if d.is_dir() and not d.name.startswith('.'):
                stream_name = d.name
                mp4_files = [f.name for f in d.iterdir() if f.is_file() and f.suffix.lower() == '.mp4']
                is_active = stream_name in active_streams
                result[stream_name] = {
                    "active": is_active,
                    "files": sorted(mp4_files),
                    "rtsp_url": f"rtsp://{os.getenv('HOST_IP', 'localhost')}:8554/{stream_name}" if is_active else None
                }
    return result

@app.post("/streams/create")
def create_stream(stream_name: str):
    """Creates a new folder for a new RTSP stream path."""
    # Sanitize stream name
    clean_name = "".join(c for c in stream_name if c.isalnum() or c in ('-', '_')).strip()
    if not clean_name:
        raise HTTPException(status_code=400, detail="Invalid stream name. Only alphanumeric characters, hyphens, and underscores are allowed.")
    
    stream_dir = INPUTS_DIR / clean_name
    if stream_dir.exists():
        return {"message": f"Stream folder '{clean_name}' already exists."}
    
    try:
        stream_dir.mkdir(parents=True, exist_ok=True)
        return {"message": f"Stream folder '{clean_name}' created successfully. Put video files in it to start streaming."}
    except Exception as e:
        logger.error(f"Failed to create stream folder: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to create stream folder: {str(e)}")

@app.post("/streams/{stream_name}/upload")
async def upload_video(stream_name: str, file: UploadFile = File(...)):
    """Uploads or replaces an MP4 file in a stream's folder. Triggers playlist rebuild automatically."""
    clean_name = "".join(c for c in stream_name if c.isalnum() or c in ('-', '_')).strip()
    stream_dir = INPUTS_DIR / clean_name
    
    if not stream_dir.exists() or not stream_dir.is_dir():
        raise HTTPException(status_code=404, detail=f"Stream '{clean_name}' does not exist. Create it first.")
        
    if not file.filename.lower().endswith('.mp4'):
        raise HTTPException(status_code=400, detail="Invalid file type. Only MP4 (.mp4) videos are supported.")
        
    # Sanitize filename
    clean_filename = "".join(c for c in file.filename if c.isalnum() or c in ('.', '-', '_')).strip()
    target_path = stream_dir / clean_filename
    
    try:
        # Delete any existing .mp4 files in this stream directory to guarantee only 1 video exists
        for existing_file in stream_dir.iterdir():
            if existing_file.is_file() and existing_file.suffix.lower() == '.mp4':
                try:
                    existing_file.unlink()
                    logger.info(f"Removed old video file '{existing_file.name}' to ensure single-video replacement.")
                except Exception as ex:
                    logger.warning(f"Could not delete old video file {existing_file.name}: {ex}")

        # Save uploaded file
        with open(target_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        
        logger.info(f"Successfully uploaded/replaced file '{clean_filename}' in stream '{clean_name}'")
        return {"message": f"File '{clean_filename}' uploaded successfully to stream '{clean_name}'."}
    except Exception as e:
        logger.error(f"File upload failed: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to write file to disk: {str(e)}")

@app.delete("/streams/{stream_name}/files/{filename}")
def delete_video(stream_name: str, filename: str):
    """Deletes a video file from a stream folder. Rebuilds stream playlist or stops if empty."""
    clean_name = "".join(c for c in stream_name if c.isalnum() or c in ('-', '_')).strip()
    clean_filename = "".join(c for c in filename if c.isalnum() or c in ('.', '-', '_')).strip()
    
    file_path = INPUTS_DIR / clean_name / clean_filename
    if not file_path.exists():
        raise HTTPException(status_code=404, detail=f"File '{clean_filename}' not found in stream '{clean_name}'.")
        
    try:
        file_path.unlink()
        logger.info(f"Deleted file '{clean_filename}' from stream '{clean_name}'")
        return {"message": f"File '{clean_filename}' deleted successfully from stream '{clean_name}'."}
    except Exception as e:
        logger.error(f"Failed to delete file: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to delete file: {str(e)}")

@app.delete("/streams/{stream_name}")
def delete_stream(stream_name: str):
    """Stops the stream and completely deletes its folder and all contents."""
    clean_name = "".join(c for c in stream_name if c.isalnum() or c in ('-', '_')).strip()
    stream_dir = INPUTS_DIR / clean_name
    
    if not stream_dir.exists():
        raise HTTPException(status_code=404, detail=f"Stream folder '{clean_name}' not found.")
        
    try:
        stop_stream(clean_name)
        shutil.rmtree(stream_dir)
        logger.info(f"Deleted stream '{clean_name}' and all its data.")
        return {"message": f"Stream '{clean_name}' and all files deleted successfully."}
    except Exception as e:
        logger.error(f"Failed to delete stream: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to delete stream: {str(e)}")
