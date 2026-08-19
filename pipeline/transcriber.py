"""
Transcription module using OpenAI Whisper API.

Handles audio chunking (Whisper has a 25MB limit) and produces
timestamped transcripts.
"""

import json
import os
from pathlib import Path
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

DATA_DIR = Path(__file__).parent.parent / "data"
TRANSCRIPT_DIR = DATA_DIR / "transcripts"

# Whisper API file size limit
MAX_FILE_SIZE = 25 * 1024 * 1024  # 25 MB


def get_client() -> OpenAI:
    """Get OpenAI client."""
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key or api_key == "sk-your-key-here":
        raise RuntimeError(
            "OPENAI_API_KEY not set. Add your key to the .env file."
        )
    return OpenAI(api_key=api_key)


def split_audio(audio_path: Path, max_size: int = MAX_FILE_SIZE) -> list[Path]:
    """
    Split audio into chunks if it exceeds the Whisper file size limit.
    
    Uses ffmpeg to split into segments. Each segment is ~20 minutes
    to stay well under the 25MB limit at 128kbps mono.
    
    Returns list of chunk file paths.
    """
    import subprocess
    
    file_size = audio_path.stat().st_size
    
    if file_size <= max_size:
        return [audio_path]
    
    print(f"[transcriber] Audio file is {file_size / (1024*1024):.1f} MB, splitting into chunks...")
    
    # Calculate segment duration based on file size
    # At 128kbps mono, 25MB ≈ 26 minutes. Use 20 min segments for safety.
    segment_duration = 1200  # 20 minutes in seconds
    
    chunks_dir = audio_path.parent / f"{audio_path.stem}_chunks"
    chunks_dir.mkdir(exist_ok=True)
    
    cmd = [
        "ffmpeg",
        "-i", str(audio_path),
        "-f", "segment",
        "-segment_time", str(segment_duration),
        "-c", "copy",
        "-y",
        str(chunks_dir / f"{audio_path.stem}_%03d.mp3"),
    ]
    
    subprocess.run(cmd, capture_output=True, text=True, check=True)
    
    chunks = sorted(chunks_dir.glob("*.mp3"))
    print(f"[transcriber] Split into {len(chunks)} chunks")
    return chunks


def transcribe_audio(audio_path: Path, clip_id: str, force: bool = False) -> dict:
    """
    Transcribe an audio file using OpenAI Whisper API.
    
    Args:
        audio_path: Path to the MP3 audio file
        clip_id: Meeting clip ID, used for the output filename
        force: If True, re-transcribe even if transcript exists
    
    Returns:
        Dict with 'text' (full transcript) and 'segments' (timestamped segments)
    """
    TRANSCRIPT_DIR.mkdir(parents=True, exist_ok=True)
    output_path = TRANSCRIPT_DIR / f"{clip_id}.json"
    
    if output_path.exists() and not force:
        print(f"[transcriber] Transcript already exists: {output_path}")
        with open(output_path) as f:
            return json.load(f)
    
    client = get_client()
    chunks = split_audio(audio_path)
    
    all_segments = []
    all_text_parts = []
    time_offset = 0.0
    
    for i, chunk_path in enumerate(chunks):
        print(f"[transcriber] Transcribing chunk {i+1}/{len(chunks)}: {chunk_path.name}")
        
        with open(chunk_path, "rb") as audio_file:
            response = client.audio.transcriptions.create(
                model="whisper-1",
                file=audio_file,
                response_format="verbose_json",
                timestamp_granularities=["segment"],
                language="en",
            )
        
        # Process segments with time offset for chunked files
        if hasattr(response, 'segments') and response.segments:
            for seg in response.segments:
                segment_dict = {
                    "start": seg.start + time_offset,
                    "end": seg.end + time_offset,
                    "text": seg.text.strip(),
                }
                all_segments.append(segment_dict)
            
            # Update time offset for next chunk
            last_end = max(s.end for s in response.segments)
            time_offset += last_end
        
        all_text_parts.append(response.text)
    
    # Clean up chunk files if we split
    if len(chunks) > 1:
        chunks_dir = chunks[0].parent
        for chunk in chunks:
            chunk.unlink()
        chunks_dir.rmdir()
    
    transcript = {
        "clip_id": clip_id,
        "text": " ".join(all_text_parts),
        "segments": all_segments,
        "num_segments": len(all_segments),
    }
    
    # Save transcript
    with open(output_path, "w") as f:
        json.dump(transcript, f, indent=2)
    
    print(f"[transcriber] Saved transcript: {output_path}")
    print(f"[transcriber] {len(all_segments)} segments, {len(transcript['text'])} chars")
    
    return transcript


if __name__ == "__main__":
    import sys
    if len(sys.argv) >= 3:
        audio_path = Path(sys.argv[1])
        clip_id = sys.argv[2]
        result = transcribe_audio(audio_path, clip_id)
        print(f"\nTranscript preview (first 500 chars):\n{result['text'][:500]}")
    else:
        print("Usage: python transcriber.py <audio_path> <clip_id>")
