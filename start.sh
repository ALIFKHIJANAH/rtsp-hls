#!/bin/bash

# Print environment info for debugging
echo "Starting RTSP2HLS service..."
echo "Python version: $(python --version)"
echo "Working directory: $(pwd)"
echo "Port: ${PORT:-8000}"
echo "Host: 0.0.0.0"

# Create HLS directory
mkdir -p hls

# Start the application
exec uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000} --log-level info