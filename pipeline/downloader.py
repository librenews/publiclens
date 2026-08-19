"""
Audio downloader for Granicus meeting streams.

Uses ffmpeg to download HLS streams and extract audio as MP3.
"""

import os
import subprocess
import shutil
from pathlib import Path


DATA_DIR = Path(__file__).parent.parent / "data"
AUDIO_DIR = DATA_DIR / "audio"


def ensure_ffmpeg():
    """Check that ffmpeg is available."""
    if not shutil.which("ffmpeg"):
        raise RuntimeError(
            "ffmpeg is not installed or not on PATH. "
            "Install it with: brew install ffmpeg"
        )


def download_audio(stream_url: str, clip_id: str, force: bool = False) -> Path:
    """
    Download audio from an HLS stream URL using ffmpeg.
    
    Args:
        stream_url: The HLS playlist URL (m3u8) or direct MP4 URL
        clip_id: Meeting clip ID, used for the output filename
        force: If True, re-download even if file exists
    
    Returns:
        Path to the downloaded MP3 file
    """
    ensure_ffmpeg()
    
    AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    output_path = AUDIO_DIR / f"{clip_id}.mp3"
    
    if output_path.exists() and not force:
        print(f"[downloader] Audio already exists: {output_path}")
        return output_path
    
    print(f"[downloader] Downloading audio for clip_id={clip_id}...")
    print(f"[downloader] Source: {stream_url}")
    print(f"[downloader] Output: {output_path}")
    
    # ffmpeg command to extract audio only as MP3
    # Granicus streams require Referer header or they return 403
    cmd = [
        "ffmpeg",
        "-headers", "Referer: https://cityofstamford.granicus.com/\r\nUser-Agent: Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36\r\n",
        "-i", stream_url,
        "-vn",                  # no video
        "-acodec", "libmp3lame", # encode as MP3
        "-ab", "128k",          # 128kbps bitrate (good enough for speech)
        "-ar", "16000",         # 16kHz sample rate (optimal for Whisper)
        "-ac", "1",             # mono (speech doesn't need stereo)
        "-y",                   # overwrite output
        str(output_path),
    ]
    
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=1800,  # 30 minute timeout for long meetings
        )
        
        if result.returncode != 0:
            print(f"[downloader] ffmpeg error:\n{result.stderr[-500:]}")
            raise RuntimeError(f"ffmpeg failed with return code {result.returncode}")
        
        file_size = output_path.stat().st_size / (1024 * 1024)
        print(f"[downloader] Downloaded: {output_path} ({file_size:.1f} MB)")
        return output_path
        
    except subprocess.TimeoutExpired:
        print("[downloader] ffmpeg timed out after 30 minutes")
        if output_path.exists():
            output_path.unlink()
        raise


if __name__ == "__main__":
    # Test with a sample URL (replace with actual stream URL)
    import sys
    if len(sys.argv) >= 3:
        download_audio(sys.argv[1], sys.argv[2])
    else:
        print("Usage: python downloader.py <stream_url> <clip_id>")
