"""
Meeting summarizer using GPT-4.

Takes a transcript and produces a structured summary with
key decisions, motions, action items, and public comments.
"""

import json
import os
from pathlib import Path
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

DATA_DIR = Path(__file__).parent.parent / "data"
SUMMARY_DIR = DATA_DIR / "summaries"

SUMMARY_PROMPT = """You are an expert at summarizing government meeting transcripts. 
Analyze the following transcript from a municipal government meeting and produce a structured summary.

Meeting: {meeting_name}
Date: {meeting_date}

TRANSCRIPT:
{transcript}

---

Produce a JSON response with the following structure:
{{
    "executive_summary": "A 2-3 paragraph overview of the meeting's key topics and outcomes",
    "key_topics": [
        {{
            "topic": "Brief topic title",
            "summary": "1-2 sentence summary of what was discussed",
            "timestamp_start": approximate start time in seconds (number or null)
        }}
    ],
    "decisions_and_votes": [
        {{
            "description": "What was decided or voted on",
            "outcome": "Passed/Failed/Tabled/etc",
            "vote_count": "e.g. 6-1 or unanimous (if mentioned)"
        }}
    ],
    "action_items": [
        {{
            "item": "What needs to be done",
            "responsible_party": "Who is responsible (if mentioned)",
            "deadline": "When (if mentioned)"
        }}
    ],
    "public_comments": [
        {{
            "speaker": "Name if mentioned, otherwise 'Public commenter'",
            "topic": "What they spoke about",
            "summary": "Brief summary of their comments"
        }}
    ],
    "notable_quotes": [
        {{
            "quote": "Direct or near-direct quote",
            "speaker": "Who said it",
            "context": "Brief context"
        }}
    ]
}}

Return ONLY the JSON, no markdown formatting or code blocks.
If a section has no items, use an empty array [].
"""


def get_client() -> OpenAI:
    """Get OpenAI client."""
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key or api_key == "sk-your-key-here":
        raise RuntimeError("OPENAI_API_KEY not set.")
    return OpenAI(api_key=api_key)


def truncate_transcript(text: str, max_tokens: int = 100000) -> str:
    """
    Truncate transcript to fit within token limits.
    Rough estimate: 1 token ≈ 4 chars for English.
    """
    max_chars = max_tokens * 4
    if len(text) <= max_chars:
        return text
    
    print(f"[summarizer] Transcript is {len(text)} chars, truncating to ~{max_tokens} tokens")
    return text[:max_chars] + "\n\n[... transcript truncated for length ...]"


def summarize_meeting(
    transcript: dict,
    meeting_name: str,
    meeting_date: str,
    clip_id: str,
    force: bool = False,
) -> dict:
    """
    Summarize a meeting transcript using GPT-4.
    
    Args:
        transcript: Dict with 'text' key containing the full transcript
        meeting_name: Name of the meeting
        meeting_date: Date of the meeting
        clip_id: Meeting clip ID for output filename
        force: If True, re-summarize even if summary exists
    
    Returns:
        Dict with structured summary
    """
    SUMMARY_DIR.mkdir(parents=True, exist_ok=True)
    output_path = SUMMARY_DIR / f"{clip_id}.json"
    
    if output_path.exists() and not force:
        print(f"[summarizer] Summary already exists: {output_path}")
        with open(output_path) as f:
            return json.load(f)
    
    client = get_client()
    
    transcript_text = truncate_transcript(transcript["text"])
    
    prompt = SUMMARY_PROMPT.format(
        meeting_name=meeting_name,
        meeting_date=meeting_date,
        transcript=transcript_text,
    )
    
    print(f"[summarizer] Generating summary for '{meeting_name}'...")
    
    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": "You are a government meeting analyst. Return only valid JSON."},
            {"role": "user", "content": prompt},
        ],
        temperature=0.3,
        max_tokens=4000,
    )
    
    raw_content = response.choices[0].message.content.strip()
    
    # Parse the JSON response — handle markdown code blocks if GPT wraps it
    if raw_content.startswith("```"):
        raw_content = raw_content.split("\n", 1)[1]  # remove first line
        raw_content = raw_content.rsplit("```", 1)[0]  # remove last ```
    
    try:
        summary = json.loads(raw_content)
    except json.JSONDecodeError as e:
        print(f"[summarizer] Failed to parse GPT response as JSON: {e}")
        print(f"[summarizer] Raw response: {raw_content[:500]}")
        summary = {
            "executive_summary": raw_content,
            "key_topics": [],
            "decisions_and_votes": [],
            "action_items": [],
            "public_comments": [],
            "notable_quotes": [],
            "parse_error": str(e),
        }
    
    # Add metadata
    summary["meeting_name"] = meeting_name
    summary["meeting_date"] = meeting_date
    summary["clip_id"] = clip_id
    
    # Save
    with open(output_path, "w") as f:
        json.dump(summary, f, indent=2)
    
    print(f"[summarizer] Saved summary: {output_path}")
    return summary


if __name__ == "__main__":
    import sys
    if len(sys.argv) >= 2:
        clip_id = sys.argv[1]
        transcript_path = DATA_DIR / "transcripts" / f"{clip_id}.json"
        if not transcript_path.exists():
            print(f"Transcript not found: {transcript_path}")
            sys.exit(1)
        with open(transcript_path) as f:
            transcript = json.load(f)
        summary = summarize_meeting(
            transcript, 
            f"Meeting {clip_id}", 
            "Unknown", 
            clip_id
        )
        print(json.dumps(summary, indent=2)[:1000])
    else:
        print("Usage: python summarizer.py <clip_id>")
