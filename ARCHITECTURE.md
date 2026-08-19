# PublicLens — Technical Architecture

> AI-powered government meeting intelligence. Transcribe, summarize, and chat with public meeting recordings.

---

## System Overview

PublicLens is a **5-stage pipeline** that transforms government meeting video streams into searchable, conversational knowledge — and a **web interface** for exploring that knowledge.

```
┌──────────────┐    ┌──────────────┐    ┌──────────────┐    ┌──────────────┐    ┌──────────────┐
│   Scraper    │───▶│  Downloader  │───▶│ Transcriber  │───▶│  Summarizer  │───▶│   Indexer    │
│  (Granicus)  │    │  (ffmpeg)    │    │  (Whisper)   │    │  (GPT-4o)    │    │   (FAISS)    │
└──────────────┘    └──────────────┘    └──────────────┘    └──────────────┘    └──────────────┘
       │                   │                   │                   │                   │
   meeting            audio.mp3          transcript.json      summary.json        index.faiss
   metadata           from HLS            + segments           structured         vector search
```

---

## Pipeline Stages

### 1. Scraper (`pipeline/scraper.py`)

**What it does:** Extracts meeting metadata and video stream URLs from the Granicus municipal platform.

| Detail | Value |
|---|---|
| **Source** | `cityofstamford.granicus.com/ViewPublisher.php` |
| **Parser** | BeautifulSoup (HTML scraping) |
| **Output** | Meeting name, date, duration, `clip_id`, HLS stream URL |

**How it works:**
- Fetches the meeting list page for a given `view_id` (each board/committee has a unique ID)
- Parses the HTML table of meetings to extract metadata
- For each meeting, fetches the MediaPlayer page and extracts the HLS `.m3u8` stream URL from embedded JavaScript

### 2. Downloader (`pipeline/downloader.py`)

**What it does:** Downloads audio from HLS video streams using `ffmpeg`.

| Detail | Value |
|---|---|
| **Input** | HLS `.m3u8` stream URL |
| **Tool** | `ffmpeg` (system dependency) |
| **Output** | MP3 audio file (`128kbps mono`) |
| **Storage** | `data/audio/{clip_id}.mp3` |

**Why audio-only?** Transcription models only need audio. Downloading the full video would be 5–10× larger and slower.

### 3. Transcriber (`pipeline/transcriber.py`)

**What it does:** Converts audio to timestamped text using OpenAI's Whisper API.

| Detail | Value |
|---|---|
| **Model** | `whisper-1` (OpenAI API) |
| **Output format** | `verbose_json` — includes per-segment timestamps |
| **Chunking** | Audio files >25MB are split into ~20-minute segments via `ffmpeg` |
| **Output** | `data/transcripts/{clip_id}.json` |

**Whisper output structure:**
```json
{
  "clip_id": "16177",
  "text": "Full transcript text...",
  "num_segments": 730,
  "segments": [
    {"start": 0.0, "end": 3.52, "text": "Good evening everyone..."},
    {"start": 3.52, "end": 8.91, "text": "I'd like to call this meeting to order..."}
  ]
}
```

Each segment has a `start` and `end` time in seconds, which are used later for timestamp-linked video seeking.

### 4. Summarizer (`pipeline/summarizer.py`)

**What it does:** Generates a structured summary of the meeting using GPT-4o.

| Detail | Value |
|---|---|
| **Model** | `gpt-4o` |
| **Temperature** | `0.3` (low for factual accuracy) |
| **Max tokens** | `4000` |
| **Output** | `data/summaries/{clip_id}.json` |

#### Summarizer System Prompt

```
You are a government meeting analyst. Return only valid JSON.
```

#### Summarizer User Prompt

The full transcript (truncated to ~100k tokens if needed) is passed with this structured prompt:

```
You are an expert at summarizing government meeting transcripts.
Analyze the following transcript from a municipal government meeting
and produce a structured summary.

Meeting: {meeting_name}
Date: {meeting_date}

TRANSCRIPT:
{transcript}

---

Produce a JSON response with the following structure:
{
    "executive_summary": "A 2-3 paragraph overview...",
    "key_topics": [
        {
            "topic": "Brief topic title",
            "summary": "1-2 sentence summary",
            "timestamp_start": approximate start time in seconds
        }
    ],
    "decisions_and_votes": [
        {
            "description": "What was decided or voted on",
            "outcome": "Passed/Failed/Tabled/etc",
            "vote_count": "e.g. 6-1 or unanimous"
        }
    ],
    "action_items": [...],
    "public_comments": [...],
    "notable_quotes": [...]
}
```

**Key design decisions:**
- Structured JSON output enables the UI to render decisions, votes, and topics as distinct visual elements
- Low temperature (0.3) minimizes hallucination on factual content
- Transcript truncation (~100k tokens) handles long meetings while staying within context limits

### 5. Indexer (`pipeline/indexer.py`)

**What it does:** Chunks the transcript, embeds it, and stores vectors in a FAISS index for semantic search.

| Detail | Value |
|---|---|
| **Embedding model** | `text-embedding-3-small` (OpenAI, 1536 dimensions) |
| **Vector store** | FAISS `IndexFlatIP` (inner product / cosine similarity) |
| **Chunk size** | ~500 tokens with 50-token overlap |
| **Chunk boundaries** | Aligned to transcript segment boundaries (natural speech breaks) |
| **Output** | `data/index/{clip_id}.faiss` + `{clip_id}_chunks.pkl` |

#### Chunking Strategy

```
Segment 1 ──┐
Segment 2   ├── Chunk A (≤500 tokens)
Segment 3 ──┘
Segment 3 ──┐   ← overlap (last segment repeated)
Segment 4   ├── Chunk B (≤500 tokens)
Segment 5 ──┘
```

- Chunks are built from **transcript segments** (natural speech boundaries from Whisper)
- Each chunk stores `start_time` and `end_time` for video timestamp linking
- Overlap ensures context isn't lost at chunk boundaries
- Embeddings are L2-normalized before indexing for cosine similarity search

---

## RAG Chat Flow

When a user asks a question, the system follows a **Retrieval-Augmented Generation** pattern:

```
User Question
     │
     ▼
┌─────────────────┐
│  1. Embed Query  │  ← text-embedding-3-small
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  2. FAISS Search │  ← top-6 chunks by cosine similarity
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ 3. Build Prompt  │  ← system prompt + context chunks + question
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ 4. GPT-4o Call   │  ← generates answer grounded in context
└────────┬────────┘
         │
         ▼
   Answer + Sources
   (with timestamps)
```

### Step-by-step detail

**Step 1 — Embed the question:** The user's question is embedded using `text-embedding-3-small`, producing a 1536-dimensional vector.

**Step 2 — Vector search:** FAISS performs a cosine similarity search against the meeting's pre-built index, returning the **top 6 most relevant chunks** (configurable via `top_k`).

**Step 3 — Prompt construction:** The retrieved chunks are formatted with their timestamps and injected into the prompt:

```
[0:35 - 2:10]
The board discussed the approval of previous meeting minutes from July 9th...

---

[1:28:02 - 1:31:10]
Motion to approve the resolution amending the capital project for fiscal year...
```

**Step 4 — LLM generation:** GPT-4o generates an answer constrained to the provided context.

### Chat System Prompt

```
You are PublicLens, an AI assistant that helps citizens understand
government meetings. You answer questions about a specific government
meeting based on the transcript provided as context.

Rules:
1. ONLY answer based on the provided transcript context. Do not make
   up information.
2. If the context doesn't contain enough information to answer, say
   so clearly.
3. When referencing specific parts of the meeting, include the
   timestamp in [HH:MM:SS] format.
4. Be concise but thorough. Use bullet points for lists.
5. If asked about votes or decisions, be precise about the outcome.
6. Maintain a neutral, informative tone — you're helping citizens
   understand their government.
```

### Chat User Prompt Template

```
Here is context from the meeting transcript, with timestamps:

{context}

---

Meeting: {meeting_name}
Date: {meeting_date}

User's question: {question}

Answer the question based only on the transcript context above.
Include timestamps [HH:MM:SS] when referencing specific parts.
```

**Key design decisions:**
- **Temperature 0.2** — even lower than summarization, because chat answers must be factual
- **1500 max tokens** — keeps answers concise
- **6 retrieved chunks** — balances context richness vs. prompt length
- **Conversation history** — last 3 exchanges (6 messages) are included for multi-turn context
- **Grounding instruction** — "ONLY answer based on the provided transcript context" prevents hallucination

---

## Frontend Architecture

### Video Player

| Detail | Value |
|---|---|
| **Library** | [HLS.js](https://github.com/video-dev/hls.js) (CDN) |
| **Source** | Granicus HLS `.m3u8` stream (streamed directly, not downloaded) |
| **Timestamp linking** | Clickable `▶ 1:28:02 – 1:31:10` buttons in chat responses |
| **Seek behavior** | `video.currentTime = seconds` with auto-play |

Timestamps in AI responses (both `[HH:MM:SS]` single and `[HH:MM:SS - HH:MM:SS]` range format) are detected via regex and rendered as interactive buttons. Clicking a timestamp seeks the embedded video player to that exact moment.

### UI Flow

```
Board Selection → Meeting Selection → Meeting Detail + Chat
     (sidebar)        (sidebar)         (sidebar + main area)
```

The sidebar shows a 3-level drill-down:
1. **Boards** — Board of Finance, Board of Representatives, etc.
2. **Meetings** — sorted by date, showing name + duration
3. **Meeting Detail** — summary, key topics, decisions & votes

The main area shows:
- **Video player** (collapsible) streaming from Granicus CDN
- **Chat interface** with suggestion chips and conversation history

### Conversation Persistence

**Conversations are not persisted.** Chat history is stored **client-side only**, in a JavaScript array (`conversationHistory`) that lives in browser memory. It is:

- **Cleared** when the user navigates to a different meeting
- **Lost** on page refresh or tab close
- **Never saved** to disk or a database on the server

During a session, the last **3 exchanges** (6 messages) are sent with each new request to give the model conversational context for follow-up questions. The server itself is **stateless** — it receives the history from the client on every request and does not maintain any session state.

**Why this design:**
- Privacy-first: no user data is stored or logged
- Simplicity: no database, no authentication, no session management
- Appropriate for an MVP — persistence would be a natural v2 feature (per-user accounts, saved conversations, starred meetings)

**What persisting would require:**
- A database (SQLite/PostgreSQL) to store conversation threads
- User accounts or anonymous session tokens
- API endpoints for loading/saving chat history

---

## FAISS Index Storage

Each meeting gets its own isolated FAISS index, stored as **two files**:

```
data/index/
├── {clip_id}.faiss          # Binary vector index (FAISS native format)
└── {clip_id}_chunks.pkl     # Python pickle of chunk metadata
```

#### The `.faiss` file

Contains the raw embedding vectors in FAISS's native binary format. Written/read by `faiss.write_index()` / `faiss.read_index()`.

| Property | Value |
|---|---|
| **Index type** | `IndexFlatIP` (flat inner product — brute-force, exact search) |
| **Dimensions** | 1536 (OpenAI `text-embedding-3-small`) |
| **Normalization** | L2-normalized before insertion → inner product = cosine similarity |
| **Typical size** | ~100KB–500KB per meeting (depends on transcript length) |

**Why `IndexFlatIP` (brute-force)?** With only 6–20 chunks per meeting, approximate nearest-neighbor algorithms (IVF, HNSW) add complexity with zero benefit. Exact search over <50 vectors is instantaneous.

#### The `_chunks.pkl` file

A Python pickle containing the list of chunk metadata dicts:

```python
[
    {
        "text": "The board discussed the approval of previous meeting minutes...",
        "start_time": 35.2,       # seconds into the video
        "end_time": 130.8,        # seconds into the video
        "chunk_index": 0,
        "clip_id": "16177"
    },
    ...
]
```

At query time, FAISS returns vector indices (e.g., `[3, 0, 7]`). These indices map into this chunk list to retrieve the text and timestamps.

#### Why per-meeting indexes?

Each meeting has its own separate index rather than one large shared index. This:
- **Prevents cross-contamination** — a question about one meeting never retrieves chunks from a different meeting
- **Simplifies management** — adding/removing meetings is just adding/deleting files
- **Keeps search fast** — searching 20 vectors is negligible regardless of how many total meetings exist

---

## Hallucination Mitigation

Hallucination — the model generating plausible-sounding but fabricated information — is the primary risk in any LLM-powered system dealing with public records. PublicLens employs **seven layers of defense**:

### 1. Retrieval-Augmented Generation (RAG) — not free-form generation

The model never answers from its own training data. Every answer is grounded in **specific transcript chunks** retrieved via semantic search. The prompt explicitly states:

```
ONLY answer based on the provided transcript context. Do not make up information.
```

Without RAG, asking "What did the Board of Finance discuss?" would produce a plausible but fabricated answer from the model's general knowledge of municipal finance. With RAG, the model can only reference what was actually said in the meeting.

### 2. Low temperature (0.2–0.3)

| Use case | Temperature | Why |
|---|---|---|
| Chat answers | `0.2` | Minimizes creative generation; strongly favors the most probable (factual) tokens |
| Summarization | `0.3` | Slightly higher to allow natural language flow, but still constrained |

Standard chatbot temperatures (0.7–1.0) encourage varied, creative outputs. Our low temperatures make the model stick closely to the source material.

### 3. Explicit refusal instruction

The system prompt includes:

```
If the context doesn't contain enough information to answer, say so clearly.
```

This trains the model to say "I don't know" rather than guess. In practice, when a user asks about something not in the retrieved chunks, the model responds with "The transcript provided does not contain information about..."

### 4. Timestamp-grounded citations

The prompt instructs:

```
When referencing specific parts of the meeting, include the timestamp in [HH:MM:SS] format.
```

This creates a **verifiability mechanism**. Every claim in the response is tied to a specific moment in the video. Users can click the timestamp button to watch that exact segment and verify the AI's characterization. If the model hallucinates a claim, the timestamp would either be missing, wrong, or lead to unrelated content — making the hallucination detectable.

### 5. Source transparency

Every chat response includes a "Jump to transcript" section showing the raw source chunks that were retrieved, with clickable timestamps. This lets users:
- See exactly what context the model was working from
- Identify if the model extrapolated beyond the source material
- Verify the original wording vs. the AI's paraphrase

### 6. Scoped context window

The model only receives **6 relevant chunks** (~3,000 tokens of transcript) per query — not the full meeting. This:
- Reduces the surface area for the model to confuse or blend unrelated topics
- Makes it easy for users to read the same source material and check the answer
- Prevents the model from being overwhelmed by a 2-hour transcript and making cross-contamination errors

### 7. Structured output for summaries

The summarization step forces GPT-4o to return **structured JSON** with specific fields (`decisions_and_votes`, `public_comments`, `action_items`). Structured output constrains the model to fill predefined categories rather than free-form narrative, which:
- Reduces the opportunity for narrative hallucination
- Makes omissions visible (empty arrays are shown as-is)
- Allows programmatic validation of the output format

### What we don't yet do (future improvements)

| Technique | Description | Status |
|---|---|---|
| **Cross-reference checking** | Compare AI summary against official meeting minutes/agendas | Planned |
| **Confidence scoring** | Flag low-confidence answers based on retrieval similarity scores | Planned |
| **Multi-model verification** | Run the same query through multiple models and flag disagreements | Not started |
| **User feedback loop** | Allow users to flag incorrect answers for review | Not started |
| **Chunked fact extraction** | Extract individual claims and verify each against source text | Research phase |

---

## Technology Stack

| Layer | Technology | Purpose |
|---|---|---|
| **Data acquisition** | BeautifulSoup, requests | Scrape Granicus meeting metadata |
| **Audio extraction** | ffmpeg (CLI) | Download HLS streams → MP3 |
| **Transcription** | OpenAI Whisper API | Speech-to-text with timestamps |
| **Summarization** | GPT-4o | Structured meeting summaries |
| **Embeddings** | text-embedding-3-small | Semantic vector representations |
| **Vector search** | FAISS (faiss-cpu) | Fast nearest-neighbor search |
| **Chat / RAG** | GPT-4o | Grounded Q&A from transcript context |
| **Backend** | Flask | REST API server |
| **Frontend** | Vanilla HTML/CSS/JS | No framework, lightweight |
| **Video playback** | HLS.js | Stream Granicus videos in-browser |

### System Dependencies

- Python 3.11+
- ffmpeg (for audio extraction and chunking)
- OpenAI API key (Whisper, GPT-4o, embeddings)

### Data Storage (Local)

```
data/
├── meeting_{clip_id}.json       # Meeting metadata (name, date, stream URL)
├── audio/{clip_id}.mp3          # Downloaded audio
├── transcripts/{clip_id}.json   # Whisper transcript + segments
├── summaries/{clip_id}.json     # GPT-4o structured summary
└── index/
    ├── {clip_id}.faiss          # FAISS vector index
    └── {clip_id}_chunks.pkl     # Serialized chunk metadata
```

---

## Pipeline CLI

```bash
# Process a single meeting
python pipeline/run_pipeline.py --clip_id 16177

# Process a meeting from a specific board
python pipeline/run_pipeline.py --clip_id 16162 --view_id 14

# Run the chat server
python server/app.py --port 3001
```

---

## Cost Estimate (per meeting)

| Step | API | Approximate Cost |
|---|---|---|
| Transcription | Whisper | ~$0.36 / hour of audio |
| Summarization | GPT-4o | ~$0.10–$0.30 per summary |
| Embedding (index) | text-embedding-3-small | ~$0.01 per meeting |
| Chat query (each) | GPT-4o + embedding | ~$0.02–$0.05 per question |

A typical 1-hour meeting costs approximately **$0.50** to fully process.
