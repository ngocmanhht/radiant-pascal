import os
import sys
import time
import subprocess
import logging
from pathlib import Path

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)

INPUT_DIR = os.getenv("INPUT_DIR", "/app/input")
PLAYLIST_PATH = os.getenv("PLAYLIST_PATH", "/app/playlist.txt")
RTSP_URL = os.getenv("RTSP_URL", "rtsp://mediamtx:8554/live")
TRANSCODE = os.getenv("TRANSCODE", "true").lower() == "true"
VIDEO_BITRATE = os.getenv("VIDEO_BITRATE", "2M")
FPS = os.getenv("FPS", "30")

def get_mp4_files():
    """Scans INPUT_DIR for .mp4 files and returns sorted paths."""
    input_path = Path(INPUT_DIR)
    if not input_path.exists():
        logging.error(f"Input directory '{INPUT_DIR}' does not exist.")
        return []
    
    # Scan for .mp4 and .MP4 files
    files = sorted([f for f in input_path.iterdir() if f.is_file() and f.suffix.lower() == '.mp4'])
    return [str(f.resolve()) for f in files]

def generate_playlist(files):
    """Generates the concat playlist file for FFmpeg."""
    try:
        with open(PLAYLIST_PATH, "w") as f:
            for file_path in files:
                # Escape single quotes in path for FFmpeg concat format
                escaped_path = file_path.replace("'", "'\\''")
                f.write(f"file '{escaped_path}'\n")
        logging.info(f"Generated playlist at {PLAYLIST_PATH} with {len(files)} files.")
        return True
    except Exception as e:
        logging.error(f"Failed to generate playlist: {e}")
        return False

def build_ffmpeg_cmd():
    """Builds the FFmpeg command based on environment variables."""
    cmd = [
        "ffmpeg",
        "-re",                          # Read input at native frame rate (realtime)
        "-f", "concat",                 # Use concat demuxer
        "-safe", "0",                   # Allow absolute/unsafe paths in playlist
        "-loop", "1",                   # Loop the playlist indefinitely
        "-i", PLAYLIST_PATH
    ]

    if TRANSCODE:
        logging.info("Transcoding enabled. Mixed video sizes and formats will be scaled and padded to 1280x720.")
        cmd.extend([
            "-c:v", "libx264",
            "-preset", "veryfast",
            "-pix_fmt", "yuv420p",
            "-r", FPS,
            "-g", str(int(FPS) * 2),     # Keyframe interval (2 seconds)
            "-b:v", VIDEO_BITRATE,
            # Scale to fit 1280x720, padding with black bars if necessary, ensuring compatibility
            "-vf", "scale=1280:720:force_original_aspect_ratio=decrease,pad=1280:720:(ow-iw)/2:(oh-ih)/2,format=yuv420p",
            "-c:a", "aac",
            "-ar", "44100",
            "-b:a", "128k",
            "-ac", "2"
        ])
    else:
        logging.info("Direct copy mode enabled. Input files MUST have matching resolutions and codecs.")
        cmd.extend([
            "-c", "copy"
        ])

    # RTSP Output Configuration
    cmd.extend([
        "-f", "rtsp",
        "-rtsp_transport", "tcp",       # Use TCP to avoid packet drops
        RTSP_URL
    ])

    return cmd

def main():
    logging.info("Starting Python Live RTSP Streamer Controller...")
    
    current_files = []
    ffmpeg_process = None

    try:
        while True:
            # 1. Scan for files
            files = get_mp4_files()

            if not files:
                logging.warning(f"No .mp4 files found in '{INPUT_DIR}'. Waiting...")
                if ffmpeg_process:
                    logging.info("Stopping stream because input directory is empty.")
                    ffmpeg_process.terminate()
                    ffmpeg_process.wait()
                    ffmpeg_process = None
                    current_files = []
                time.sleep(5)
                continue

            # 2. Check if file list has changed
            if files != current_files:
                logging.info(f"Detected file changes in '{INPUT_DIR}'. Restarting stream...")
                
                # Terminate existing stream if running
                if ffmpeg_process:
                    logging.info("Terminating old FFmpeg process...")
                    ffmpeg_process.terminate()
                    try:
                        ffmpeg_process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        logging.warning("FFmpeg process didn't terminate in time, killing it...")
                        ffmpeg_process.kill()
                        ffmpeg_process.wait()
                    ffmpeg_process = None

                # Generate new playlist
                if generate_playlist(files):
                    current_files = files
                    # Start streaming
                    cmd = build_ffmpeg_cmd()
                    logging.info(f"Running command: {' '.join(cmd)}")
                    ffmpeg_process = subprocess.Popen(cmd)
                else:
                    logging.error("Failed to generate playlist. Retrying in 5 seconds...")
                    time.sleep(5)
                    continue

            # 3. Monitor running process
            if ffmpeg_process:
                # Read a bit of output to keep stdout clean and log any ffmpeg errors
                status = ffmpeg_process.poll()
                if status is not None:
                    logging.error(f"FFmpeg process exited with code {status}. Restarting stream...")
                    ffmpeg_process = None
                    current_files = []  # Force recreation next loop
                    time.sleep(2)
                    continue
            
            time.sleep(2)

    except KeyboardInterrupt:
        logging.info("Shutting down controller...")
    finally:
        if ffmpeg_process:
            ffmpeg_process.terminate()
            ffmpeg_process.wait()
        # Clean up playlist file if exists
        if os.path.exists(PLAYLIST_PATH):
            try:
                os.remove(PLAYLIST_PATH)
            except OSError:
                pass
        logging.info("Controller stopped.")

if __name__ == "__main__":
    main()
