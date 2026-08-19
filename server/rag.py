"""
RAG (Retrieval-Augmented Generation) module.

Handles the chat flow: embed query → search index → build prompt → call LLM.
"""

import json
import os
from pathlib import Path
from typing import Optional

from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

# Add parent to path for pipeline imports
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from pipeline.indexer import search, format_timestamp


DATA_DIR = Path(__file__).parent.parent / "data"

SYSTEM_PROMPT = """You are PublicLens, an AI assistant that helps citizens understand government meetings.
You answer questions about a specific government meeting based on the transcript provided as context.

Rules:
1. ONLY answer based on the provided transcript context. Do not make up information.
2. If the context doesn't contain enough information to answer, say so clearly.
3. When referencing specific parts of the meeting, include the timestamp in [HH:MM:SS] format.
4. Be concise but thorough. Use bullet points for lists.
5. If asked about votes or decisions, be precise about the outcome.
6. Maintain a neutral, informative tone — you're helping citizens understand their government."""

USER_PROMPT_TEMPLATE = """Here is context from the meeting transcript, with timestamps:

{context}

---

Meeting: {meeting_name}
Date: {meeting_date}

User's question: {question}

Answer the question based only on the transcript context above. Include timestamps [HH:MM:SS] when referencing specific parts."""


def get_client() -> OpenAI:
    """Get OpenAI client."""
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key or api_key == "sk-your-key-here":
        raise RuntimeError("OPENAI_API_KEY not set.")
    return OpenAI(api_key=api_key)


def load_meeting_data(clip_id: str) -> dict:
    """Load all meeting data (metadata, summary, transcript info)."""
    data = {"clip_id": clip_id}
    
    # Meeting metadata
    meta_path = DATA_DIR / f"meeting_{clip_id}.json"
    if meta_path.exists():
        with open(meta_path) as f:
            data["meeting"] = json.load(f)
    
    # Summary
    summary_path = DATA_DIR / "summaries" / f"{clip_id}.json"
    if summary_path.exists():
        with open(summary_path) as f:
            data["summary"] = json.load(f)
    
    # Transcript stats (don't load full text, it's huge)
    transcript_path = DATA_DIR / "transcripts" / f"{clip_id}.json"
    if transcript_path.exists():
        with open(transcript_path) as f:
            t = json.load(f)
            data["transcript_stats"] = {
                "num_segments": t.get("num_segments", 0),
                "text_length": len(t.get("text", "")),
            }
    
    return data


def chat(
    question: str,
    clip_id: str,
    conversation_history: Optional[list[dict]] = None,
    top_k: int = 6,
) -> dict:
    """
    Answer a question about a meeting using RAG.
    
    Args:
        question: User's question
        clip_id: Meeting clip ID to search
        conversation_history: Optional list of prior messages for context
        top_k: Number of transcript chunks to retrieve
    
    Returns:
        Dict with 'answer', 'sources' (cited chunks with timestamps)
    """
    client = get_client()
    
    # Load meeting info
    meeting_data = load_meeting_data(clip_id)
    meeting_name = meeting_data.get("meeting", {}).get("name", f"Meeting {clip_id}")
    meeting_date = meeting_data.get("meeting", {}).get("date", "Unknown")
    
    # Search for relevant chunks
    try:
        results = search(question, clip_id, top_k=top_k)
    except FileNotFoundError:
        return {
            "answer": "No search index found for this meeting. Please run the pipeline first.",
            "sources": [],
        }
    
    # Build context from search results
    context_parts = []
    sources = []
    
    for r in results:
        ts_start = format_timestamp(r.get("start_time"))
        ts_end = format_timestamp(r.get("end_time"))
        
        context_parts.append(f"[{ts_start} - {ts_end}]\n{r['text']}")
        sources.append({
            "text": r["text"][:200] + ("..." if len(r["text"]) > 200 else ""),
            "start_time": r.get("start_time"),
            "end_time": r.get("end_time"),
            "timestamp": ts_start,
            "score": r.get("score", 0),
        })
    
    context = "\n\n---\n\n".join(context_parts)
    
    # Build messages
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    
    # Add conversation history if provided
    if conversation_history:
        for msg in conversation_history[-6:]:  # keep last 3 exchanges
            messages.append(msg)
    
    # Add the current question with context
    user_prompt = USER_PROMPT_TEMPLATE.format(
        context=context,
        meeting_name=meeting_name,
        meeting_date=meeting_date,
        question=question,
    )
    messages.append({"role": "user", "content": user_prompt})
    
    # Call GPT
    response = client.chat.completions.create(
        model="gpt-4o",
        messages=messages,
        temperature=0.2,
        max_tokens=1500,
    )
    
    answer = response.choices[0].message.content
    
    return {
        "answer": answer,
        "sources": sources,
        "meeting_name": meeting_name,
        "meeting_date": meeting_date,
    }


if __name__ == "__main__":
    import sys
    if len(sys.argv) >= 3:
        clip_id = sys.argv[1]
        question = " ".join(sys.argv[2:])
        result = chat(question, clip_id)
        print(f"\n{'='*60}")
        print(f"Q: {question}")
        print(f"{'='*60}")
        print(f"\n{result['answer']}")
        print(f"\n--- Sources ({len(result['sources'])}) ---")
        for s in result['sources']:
            print(f"  [{s['timestamp']}] {s['text'][:100]}...")
    else:
        print("Usage: python rag.py <clip_id> <question>")
