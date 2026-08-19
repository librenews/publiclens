"""
Transcript indexer for RAG search.

Chunks transcripts into overlapping segments, embeds them using
OpenAI embeddings, and stores in a local FAISS index.
"""

import json
import os
import pickle
from pathlib import Path
from typing import Optional

import faiss
import numpy as np
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

DATA_DIR = Path(__file__).parent.parent / "data"
INDEX_DIR = DATA_DIR / "index"

CHUNK_SIZE = 500       # target tokens per chunk
CHUNK_OVERLAP = 50     # overlap tokens between chunks
EMBED_MODEL = "text-embedding-3-small"
EMBED_DIM = 1536


def get_client() -> OpenAI:
    """Get OpenAI client."""
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key or api_key == "sk-your-key-here":
        raise RuntimeError("OPENAI_API_KEY not set.")
    return OpenAI(api_key=api_key)


def chunk_transcript(transcript: dict, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[dict]:
    """
    Split transcript into overlapping chunks for embedding.
    
    Uses segment boundaries to create natural chunk breaks.
    Each chunk includes timestamp info for citation.
    
    Returns list of chunk dicts with 'text', 'start_time', 'end_time', 'chunk_index'.
    """
    segments = transcript.get("segments", [])
    
    if not segments:
        # Fallback: chunk the raw text
        text = transcript["text"]
        words = text.split()
        chunks = []
        # Rough: 1 token ≈ 0.75 words
        words_per_chunk = int(chunk_size * 0.75)
        words_overlap = int(overlap * 0.75)
        
        i = 0
        chunk_idx = 0
        while i < len(words):
            chunk_words = words[i:i + words_per_chunk]
            chunks.append({
                "text": " ".join(chunk_words),
                "start_time": None,
                "end_time": None,
                "chunk_index": chunk_idx,
                "clip_id": transcript["clip_id"],
            })
            i += words_per_chunk - words_overlap
            chunk_idx += 1
        
        return chunks
    
    # Use segments for natural boundaries
    chunks = []
    current_text_parts = []
    current_start = segments[0]["start"] if segments else 0
    current_word_count = 0
    words_per_chunk = int(chunk_size * 0.75)
    chunk_idx = 0
    
    for seg in segments:
        seg_words = len(seg["text"].split())
        
        if current_word_count + seg_words > words_per_chunk and current_text_parts:
            # Emit current chunk
            chunks.append({
                "text": " ".join(current_text_parts),
                "start_time": current_start,
                "end_time": seg["start"],
                "chunk_index": chunk_idx,
                "clip_id": transcript["clip_id"],
            })
            chunk_idx += 1
            
            # Keep last segment as overlap
            overlap_parts = current_text_parts[-1:] if current_text_parts else []
            current_text_parts = overlap_parts
            current_start = seg["start"]
            current_word_count = sum(len(p.split()) for p in current_text_parts)
        
        current_text_parts.append(seg["text"])
        current_word_count += seg_words
    
    # Don't forget the last chunk
    if current_text_parts:
        chunks.append({
            "text": " ".join(current_text_parts),
            "start_time": current_start,
            "end_time": segments[-1]["end"] if segments else None,
            "chunk_index": chunk_idx,
            "clip_id": transcript["clip_id"],
        })
    
    return chunks


def embed_chunks(chunks: list[dict], batch_size: int = 100) -> np.ndarray:
    """
    Embed chunks using OpenAI embeddings API.
    
    Returns numpy array of shape (n_chunks, embed_dim).
    """
    client = get_client()
    all_embeddings = []
    
    for i in range(0, len(chunks), batch_size):
        batch = chunks[i:i + batch_size]
        texts = [c["text"] for c in batch]
        
        print(f"[indexer] Embedding batch {i//batch_size + 1}/{(len(chunks)-1)//batch_size + 1}")
        
        response = client.embeddings.create(
            model=EMBED_MODEL,
            input=texts,
        )
        
        batch_embeddings = [item.embedding for item in response.data]
        all_embeddings.extend(batch_embeddings)
    
    return np.array(all_embeddings, dtype=np.float32)


def build_index(transcript: dict, clip_id: str, force: bool = False) -> tuple:
    """
    Build a FAISS index from a transcript.
    
    Args:
        transcript: Dict with 'text' and 'segments'
        clip_id: Meeting clip ID
        force: If True, rebuild even if index exists
    
    Returns:
        Tuple of (faiss_index, chunks_list)
    """
    INDEX_DIR.mkdir(parents=True, exist_ok=True)
    index_path = INDEX_DIR / f"{clip_id}.faiss"
    chunks_path = INDEX_DIR / f"{clip_id}_chunks.pkl"
    
    if index_path.exists() and chunks_path.exists() and not force:
        print(f"[indexer] Index already exists: {index_path}")
        index = faiss.read_index(str(index_path))
        with open(chunks_path, "rb") as f:
            chunks = pickle.load(f)
        return index, chunks
    
    print(f"[indexer] Building index for clip_id={clip_id}...")
    
    # Chunk the transcript
    chunks = chunk_transcript(transcript)
    print(f"[indexer] Created {len(chunks)} chunks")
    
    if not chunks:
        raise ValueError("No chunks created from transcript")
    
    # Embed chunks
    embeddings = embed_chunks(chunks)
    
    # Build FAISS index
    index = faiss.IndexFlatIP(EMBED_DIM)  # Inner product (cosine sim on normalized vectors)
    
    # Normalize embeddings for cosine similarity
    faiss.normalize_L2(embeddings)
    index.add(embeddings)
    
    # Save
    faiss.write_index(index, str(index_path))
    with open(chunks_path, "wb") as f:
        pickle.dump(chunks, f)
    
    print(f"[indexer] Saved index ({index.ntotal} vectors): {index_path}")
    return index, chunks


def search(query: str, clip_id: str, top_k: int = 5) -> list[dict]:
    """
    Search the index for relevant chunks.
    
    Args:
        query: User's question
        clip_id: Meeting clip ID to search
        top_k: Number of results to return
    
    Returns:
        List of chunk dicts with added 'score' field
    """
    index_path = INDEX_DIR / f"{clip_id}.faiss"
    chunks_path = INDEX_DIR / f"{clip_id}_chunks.pkl"
    
    if not index_path.exists():
        raise FileNotFoundError(f"No index found for clip_id={clip_id}")
    
    index = faiss.read_index(str(index_path))
    with open(chunks_path, "rb") as f:
        chunks = pickle.load(f)
    
    # Embed query
    client = get_client()
    response = client.embeddings.create(
        model=EMBED_MODEL,
        input=[query],
    )
    query_embedding = np.array([response.data[0].embedding], dtype=np.float32)
    faiss.normalize_L2(query_embedding)
    
    # Search
    scores, indices = index.search(query_embedding, min(top_k, len(chunks)))
    
    results = []
    for score, idx in zip(scores[0], indices[0]):
        if idx < 0:
            continue
        chunk = chunks[idx].copy()
        chunk["score"] = float(score)
        results.append(chunk)
    
    return results


def format_timestamp(seconds: Optional[float]) -> str:
    """Format seconds as HH:MM:SS."""
    if seconds is None:
        return "N/A"
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    if h > 0:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


if __name__ == "__main__":
    import sys
    if len(sys.argv) >= 3:
        clip_id = sys.argv[1]
        query = " ".join(sys.argv[2:])
        
        results = search(query, clip_id)
        print(f"\nSearch results for: '{query}'\n")
        for r in results:
            ts = format_timestamp(r.get("start_time"))
            print(f"[{ts}] (score: {r['score']:.3f})")
            print(f"  {r['text'][:200]}...")
            print()
    else:
        print("Usage: python indexer.py <clip_id> <search query>")
