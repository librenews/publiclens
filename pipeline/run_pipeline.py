"""
PublicLens Pipeline CLI

Orchestrates the full pipeline: scrape → download → transcribe → summarize → index.

Usage:
    python run_pipeline.py --clip_id 16177
    python run_pipeline.py --clip_id 16177 --force
    python run_pipeline.py --list                    # list available meetings
    python run_pipeline.py --clip_id 16177 --stream_url <URL>  # skip stream URL extraction
"""

import argparse
import json
import sys
from pathlib import Path

# Add parent to path so we can import pipeline modules
sys.path.insert(0, str(Path(__file__).parent.parent))

from pipeline.scraper import scrape_meeting_list, extract_stream_url, get_meeting_by_clip_id
from pipeline.downloader import download_audio
from pipeline.transcriber import transcribe_audio
from pipeline.summarizer import summarize_meeting
from pipeline.indexer import build_index


DATA_DIR = Path(__file__).parent.parent / "data"


def list_meetings(view_id: str = "4"):
    """List all available meetings."""
    meetings = scrape_meeting_list(view_id)
    print(f"\n{'='*80}")
    print(f"  Found {len(meetings)} meetings (view_id={view_id})")
    print(f"{'='*80}\n")
    
    for m in meetings:
        print(f"  clip_id={m.clip_id:>6}  |  {m.date:>12}  |  {m.duration:>8}  |  {m.name}")
    
    print(f"\n  Run: python run_pipeline.py --clip_id <ID>\n")


def run_pipeline(
    clip_id: str,
    view_id: str = "4",
    stream_url: str = None,
    force: bool = False,
):
    """Run the full pipeline for a single meeting."""
    
    print(f"\n{'='*80}")
    print(f"  PublicLens Pipeline — clip_id={clip_id}")
    print(f"{'='*80}\n")
    
    # ── Step 1: Get meeting metadata ──────────────────────────
    print("─── Step 1/5: Scraping meeting metadata ───")
    meeting = get_meeting_by_clip_id(clip_id, view_id)
    
    if not meeting:
        print(f"[ERROR] Meeting clip_id={clip_id} not found on the page.")
        print(f"[INFO]  Use --list to see available meetings.")
        sys.exit(1)
    
    print(f"  Meeting: {meeting.name}")
    print(f"  Date:    {meeting.date}")
    print(f"  Duration: {meeting.duration}")
    
    # Use provided stream URL or the one we extracted
    final_stream_url = stream_url or meeting.stream_url
    
    if not final_stream_url:
        print(f"\n[ERROR] Could not extract stream URL automatically.")
        print(f"[INFO]  The stream URL is loaded dynamically via JavaScript.")
        print(f"[INFO]  To get it manually:")
        print(f"  1. Open: {meeting.video_url}")
        print(f"  2. Open browser DevTools → Network tab")
        print(f"  3. Filter for 'm3u8' or 'mp4'")
        print(f"  4. Copy the URL and re-run with:")
        print(f"     python run_pipeline.py --clip_id {clip_id} --stream_url <URL>")
        sys.exit(1)
    
    # Save meeting metadata
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    meta_path = DATA_DIR / f"meeting_{clip_id}.json"
    with open(meta_path, "w") as f:
        json.dump(meeting.to_dict(), f, indent=2)
    print(f"  Saved metadata: {meta_path}")
    
    # ── Step 2: Download audio ────────────────────────────────
    print(f"\n─── Step 2/5: Downloading audio ───")
    audio_path = download_audio(final_stream_url, clip_id, force=force)
    
    # ── Step 3: Transcribe ────────────────────────────────────
    print(f"\n─── Step 3/5: Transcribing with Whisper ───")
    transcript = transcribe_audio(audio_path, clip_id, force=force)
    print(f"  Transcript: {len(transcript['text'])} chars, {transcript['num_segments']} segments")
    
    # ── Step 4: Summarize ─────────────────────────────────────
    print(f"\n─── Step 4/5: Generating summary ───")
    summary = summarize_meeting(
        transcript,
        meeting.name,
        meeting.date,
        clip_id,
        force=force,
    )
    print(f"  Summary generated with {len(summary.get('key_topics', []))} topics")
    
    # ── Step 5: Index for search ──────────────────────────────
    print(f"\n─── Step 5/5: Building search index ───")
    index, chunks = build_index(transcript, clip_id, force=force)
    print(f"  Index built with {len(chunks)} chunks")
    
    # ── Done ──────────────────────────────────────────────────
    print(f"\n{'='*80}")
    print(f"  ✅ Pipeline complete for: {meeting.name}")
    print(f"{'='*80}")
    print(f"\n  Files created:")
    print(f"    Metadata:    data/meeting_{clip_id}.json")
    print(f"    Audio:       data/audio/{clip_id}.mp3")
    print(f"    Transcript:  data/transcripts/{clip_id}.json")
    print(f"    Summary:     data/summaries/{clip_id}.json")
    print(f"    Index:       data/index/{clip_id}.faiss")
    print(f"\n  Start the chat server:")
    print(f"    python server/app.py --clip_id {clip_id}")
    print()


def main():
    parser = argparse.ArgumentParser(
        description="PublicLens — Government meeting summarizer pipeline"
    )
    parser.add_argument("--clip_id", type=str, help="Granicus clip ID to process")
    parser.add_argument("--view_id", type=str, default="4", help="Granicus view ID (default: 4 = Board of Finance)")
    parser.add_argument("--stream_url", type=str, help="Direct HLS/MP4 stream URL (skip auto-extraction)")
    parser.add_argument("--list", action="store_true", help="List available meetings")
    parser.add_argument("--force", action="store_true", help="Re-process even if outputs exist")
    
    args = parser.parse_args()
    
    if args.list:
        list_meetings(args.view_id)
        return
    
    if not args.clip_id:
        parser.print_help()
        print("\n  Example: python run_pipeline.py --clip_id 16177")
        return
    
    run_pipeline(
        clip_id=args.clip_id,
        view_id=args.view_id,
        stream_url=args.stream_url,
        force=args.force,
    )


if __name__ == "__main__":
    main()
