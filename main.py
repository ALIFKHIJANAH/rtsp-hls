
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from fastapi import FastAPI, BackgroundTasks, HTTPException
from pydantic import BaseModel
import subprocess
import os

app = FastAPI()

origins = [
    "*"
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)
HLS_DIR = "hls"
# Create directory with error handling for Docker environments
try:
    os.makedirs(HLS_DIR, exist_ok=True)
    os.chmod(HLS_DIR, 0o755)
except PermissionError:
    # If we can't set permissions (like in Docker), continue anyway
    print(f"Warning: Could not set permissions on {HLS_DIR}, continuing...")
    if not os.path.exists(HLS_DIR):
        os.makedirs(HLS_DIR, exist_ok=True)

# Health check endpoint
@app.get("/")
async def root():
    return {
        "message": "RTSP to HLS Converter Service", 
        "version": "1.0.0",
        "endpoints": {
            "health": "/health",
            "convert": "POST /convert/",
            "docs": "/docs"
        }
    }

@app.get("/health")
async def health_check():
    # Check if HLS directory is writable
    try:
        test_file = f"{HLS_DIR}/.health_test"
        with open(test_file, 'w') as f:
            f.write('test')
        os.remove(test_file)
        hls_status = "writable"
    except Exception as e:
        hls_status = f"not writable: {str(e)}"
    
    return {
        "status": "healthy", 
        "message": "RTSP2HLS service is running",
        "hls_directory": hls_status,
        "hls_path": os.path.abspath(HLS_DIR)
    }

# Pydantic model for request body
class ConvertRequest(BaseModel):
    rtsp_url: str

@app.get("/convert/")
async def convert_info():
    return {
        "message": "RTSP to HLS Conversion Endpoint",
        "method": "POST",
        "required_payload": {
            "rtsp_url": "string - The RTSP stream URL to convert"
        },
        "example": {
            "rtsp_url": "rtsp://example.com:554/stream"
        },
        "response": {
            "hls_url": "The URL of the generated HLS playlist"
        }
    }

@app.post("/convert/")
async def convert_rtsp_to_hls(background_tasks: BackgroundTasks, request: ConvertRequest):
    rtsp_url = request.rtsp_url
    stream_id = abs(hash(rtsp_url))  # Always positive
    stream_dir = f"{HLS_DIR}/{stream_id}"
    
    # Ensure stream directory exists with proper permissions
    try:
        os.makedirs(stream_dir, exist_ok=True)
        os.chmod(stream_dir, 0o755)
        # Test write permissions
        test_file = f"{stream_dir}/.test"
        with open(test_file, 'w') as f:
            f.write('test')
        os.remove(test_file)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Cannot create output directory: {str(e)}")

    background_tasks.add_task(run_ffmpeg, rtsp_url, stream_dir)

    # Use environment variable for host or default to localhost
    host = os.getenv('HOST_URL', 'localhost:8000')
    protocol = "https" if "dokploy" in host or "." in host else "http"
    hls_url = f"{protocol}://{host}/hls/{stream_id}/index.m3u8"
    return {"hls_url": hls_url}

def run_ffmpeg(rtsp_url, output_dir):
    # Ensure output directory exists and is writable
    try:
        os.makedirs(output_dir, exist_ok=True)
        os.chmod(output_dir, 0o755)
    except PermissionError:
        # Continue if we can't set permissions (Docker environment)
        print(f"Warning: Could not set permissions on {output_dir}")
        if not os.path.exists(output_dir):
            os.makedirs(output_dir, exist_ok=True)
    
    output_file = f'{output_dir}/index.m3u8'
    
    cmd = [
        'ffmpeg',
        '-y',  # Overwrite output files
        '-loglevel', 'info',  # Reduce log verbosity
        '-rtsp_transport', 'tcp',  # Use TCP for better reliability
        '-i', rtsp_url,
        '-t', '30',         # Limit recording to 30 seconds
        '-c:v', 'libx264',  # Use h264 encoder instead of copy
        '-preset', 'veryfast',  # Fast encoding
        '-crf', '23',       # Good quality
        '-maxrate', '1M',   # Max bitrate
        '-bufsize', '2M',   # Buffer size
        '-g', '50',         # GOP size
        '-sc_threshold', '0',  # Disable scene detection
        '-an',              # No audio
        '-f', 'hls',        # HLS format
        '-hls_time', '2',   # Segment duration
        '-hls_list_size', '0',  # Keep all segments
        '-hls_segment_type', 'mpegts',
        '-hls_flags', 'delete_segments+append_list',  # Clean up old segments
        output_file
    ]
    
    print(f"Starting FFmpeg for stream: {rtsp_url}")
    print(f"Output directory: {output_dir}")
    print(f"Command: {' '.join(cmd)}")
    
    try:
        # Run with timeout and capture output
        result = subprocess.run(
            cmd, 
            capture_output=True, 
            text=True, 
            timeout=60,  # 60 second timeout
            check=True
        )
        print(f"FFmpeg completed successfully for {output_file}")
        print(f"FFmpeg stdout: {result.stdout}")
    except subprocess.TimeoutExpired:
        print(f"FFmpeg timeout for {rtsp_url}")
    except subprocess.CalledProcessError as e:
        print(f"FFmpeg error for {rtsp_url}:")
        print(f"Return code: {e.returncode}")
        print(f"stdout: {e.stdout}")
        print(f"stderr: {e.stderr}")
    except Exception as e:
        print(f"Unexpected error running FFmpeg: {str(e)}")

# Serve HLS segments and playlist
app.mount("/hls", StaticFiles(directory=HLS_DIR), name="hls")

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
